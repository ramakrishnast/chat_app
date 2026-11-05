"""A scripted chat model that streams like a real one, including tool calls.

Used by the test suite, and selectable as the `fake:echo` model so the whole app can be
tried without Ollama or an API key. Each call pops the next scripted AIMessage. Without a
script it plays a tiny demo agent: "write ..." goes to a `writer` tool, arithmetic to a
`calculator` tool, tool results are summarised, and anything else is echoed.
"""

import asyncio
import itertools
import json
import re
from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Any

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.messages.tool import tool_call_chunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field


def _last_user_text(messages: Sequence[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return message.text
    return ""


class ScriptedChatModel(BaseChatModel):
    script: list[AIMessage] = Field(default_factory=list)
    thinking: str = ""  # streamed as reasoning before each reply when set
    delay: float = 0.0  # seconds between streamed chunks
    bound_tools: list[str] = Field(default_factory=list)
    _calls: Any = None

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def model_post_init(self, context: Any) -> None:
        self._calls = itertools.count()  # shared by copies made in bind_tools

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "ScriptedChatModel":
        names = [getattr(t, "name", None) or getattr(t, "__name__", "") for t in tools]
        return self.model_copy(update={"bound_tools": names})

    def _next(self, messages: Sequence[BaseMessage]) -> AIMessage:
        index = next(self._calls)
        if index < len(self.script):
            return self.script[index]
        return self._demo(messages)

    def _demo(self, messages: Sequence[BaseMessage]) -> AIMessage:
        last = messages[-1] if messages else None
        if isinstance(last, ToolMessage):
            return AIMessage(f"The **{last.name}** tool returned:\n\n{last.text}")
        text = _last_user_text(messages)
        if text.rstrip().endswith("Title:"):  # the app asking for a chat title
            first = text.removeprefix("User:").split("\n")[0].split()
            return AIMessage(" ".join(first[:5]).rstrip(".?!") or "New chat")
        system = messages[0].text if messages and isinstance(messages[0], SystemMessage) else ""
        if "writer" in system.lower() and not self.bound_tools:
            return AIMessage(
                f"A short piece about *{text[:60]}*:\n\nWords line up and rhyme,\n"
                "streaming in one token at a time,\nthen settle into place."
            )
        call_id = f"call_{next(self._calls)}"
        if "writer" in self.bound_tools and re.match(r"\s*(write|draft|compose)\b", text, re.I):
            return AIMessage(
                "I'll hand this to the writer.",
                tool_calls=[{"name": "writer", "args": {"task": text}, "id": call_id}],
            )
        expression = re.search(r"[\d(][\d\s+*/().%-]*[\d)]", text)
        if "calculator" in self.bound_tools and expression and re.search(r"[+*/%-]", expression[0]):
            return AIMessage(
                "Let me calculate that.",
                tool_calls=[
                    {
                        "name": "calculator",
                        "args": {"expression": expression[0].strip()},
                        "id": call_id,
                    }
                ],
            )
        return AIMessage(f"You said: {text}")

    def _chunks(self, reply: AIMessage) -> Iterator[AIMessageChunk]:
        if self.thinking:
            for word in self.thinking.split(" "):
                yield AIMessageChunk(
                    content="", additional_kwargs={"reasoning_content": word + " "}
                )
        words = reply.text.split(" ") if reply.text else []
        for i, word in enumerate(words):
            yield AIMessageChunk(content=word if i == len(words) - 1 else word + " ")
        for i, call in enumerate(reply.tool_calls):
            yield AIMessageChunk(
                content="",
                tool_call_chunks=[
                    tool_call_chunk(
                        name=call["name"], args=json.dumps(call["args"]), id=call["id"], index=i
                    )
                ],
            )
        yield AIMessageChunk(content="", chunk_position="last")

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next(messages))])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        for chunk in self._chunks(self._next(messages)):
            if run_manager and chunk.text:
                run_manager.on_llm_new_token(chunk.text, chunk=ChatGenerationChunk(message=chunk))
            yield ChatGenerationChunk(message=chunk)

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        for chunk in self._chunks(self._next(messages)):
            if self.delay:
                await asyncio.sleep(self.delay)
            generation = ChatGenerationChunk(message=chunk)
            if run_manager:
                await run_manager.on_llm_new_token(chunk.text, chunk=generation)
            yield generation
