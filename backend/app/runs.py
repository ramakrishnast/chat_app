"""One chat turn: stream the graph's run as SSE, keep the thread consistent if it stops."""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import anyio
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.pregel import Pregel

from agentkit.models import MODEL_KEY, THINKING_KEY
from app.history import ENDED_KEY
from app.store import ThreadStore
from app.streaming import PROTOCOL_VERSION, STREAM_MODES, StreamTranslator, sse
from app.titles import generate_title

log = logging.getLogger(__name__)


def run_config(thread_id: str, model_id: str, thinking: bool) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id, MODEL_KEY: model_id, THINKING_KEY: thinking}}


async def repair_thread(
    graph: Pregel, config: RunnableConfig, translator: StreamTranslator, reason: str
) -> None:
    """`reason` is "stopped" (the user pressed stop) or "error" (the graph raised)."""
    """After a stop or failure: save what the main agent finished but the thread doesn't have
    yet (an agent running inside a node only hands its messages over when the node ends),
    keep the partial answer, and answer tool calls that never got a result (providers
    reject a history with unanswered tool calls)."""
    try:
        state = await graph.aget_state(config)
        saved = (state.values or {}).get("messages") or []
        saved_ids = {m.id for m in saved}
        missing = [m for m in translator.main_messages() if m.id not in saved_ids]
        messages = [*saved, *missing]
        answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
        fixes: list[Any] = list(missing)
        fixes += [
            ToolMessage(
                content="Not run: the reply was "
                + ("stopped" if reason == "stopped" else "interrupted by an error")
                + " before this tool finished.",
                tool_call_id=call["id"],
                name=call["name"],
                status="error",
                response_metadata={ENDED_KEY: reason},
            )
            for message in messages
            if isinstance(message, AIMessage)
            for call in message.tool_calls
            if call.get("id") and call["id"] not in answered
        ]
        unfinished = translator.unfinished_answer()
        if unfinished:
            message_id, text = unfinished
            fixes.append(
                AIMessage(content=text, id=message_id, response_metadata={ENDED_KEY: reason})
            )
        if fixes:
            await graph.aupdate_state(
                config, {"messages": fixes}, as_node=translator.last_root_node
            )
    except Exception:
        log.exception("could not tidy the thread after the run ended early")


async def stream_run(
    *,
    graph: Pregel,
    store: ThreadStore,
    thread_id: str,
    content: str,
    model_id: str,
    thinking: bool,
    first_turn: bool,
    placeholder_title: str,
    active: set[str],
) -> AsyncIterator[str]:
    config = run_config(thread_id, model_id, thinking)
    user = HumanMessage(content=content, id=str(uuid.uuid4()))
    translator = StreamTranslator()
    status = "complete"
    answer: list[str] = []

    active.add(thread_id)
    try:
        yield sse(
            {
                "type": "run_start",
                "protocol": PROTOCOL_VERSION,
                "run_id": str(uuid.uuid4()),
                "thread_id": thread_id,
                "model": model_id,
                "thinking": thinking,
            }
        )
        yield sse(
            {
                "type": "user_message",
                "message": {
                    "id": user.id,
                    "role": "user",
                    "created_at": datetime.now(UTC).isoformat(),
                    "status": "complete",
                    "parts": [{"type": "text", "text": content}],
                },
            }
        )
        try:
            try:
                async for part in graph.astream(
                    {"messages": [user]},
                    config,
                    stream_mode=STREAM_MODES,
                    subgraphs=True,
                    version="v2",
                ):
                    for event in translator.feed(part):
                        if event["type"] == "text" and event["parent_tool_call_id"] is None:
                            answer.append(event["delta"])
                        yield sse(event)
            except Exception as exc:
                status = "error"
                log.exception("graph run failed", extra={"thread_id": thread_id})
                yield sse({"type": "error", "message": str(exc) or type(exc).__name__})
                await repair_thread(graph, config, translator, "error")
        except (asyncio.CancelledError, GeneratorExit):
            # The client pressed stop (closed the connection).
            with anyio.CancelScope(shield=True):
                await repair_thread(graph, config, translator, "stopped")
            raise
    finally:
        active.discard(thread_id)

    if first_turn and status == "complete":
        title = await generate_title(model_id, content, "".join(answer))
        if title and await store.set_title_if(thread_id, title=title, current=placeholder_title):
            yield sse({"type": "title", "title": title})
    await store.update(thread_id)  # bump updated_at
    yield sse({"type": "done", "status": status})
