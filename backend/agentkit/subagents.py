from typing import Annotated, Any

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, InjectedToolCallId, StructuredTool
from pydantic import BaseModel, Field

# Read by the backend's stream translator to nest a subagent's output under its tool call.
SUBAGENT_KEY = "subagent"
PARENT_TOOL_CALL_KEY = "parent_tool_call_id"


class _Task(BaseModel):
    task: str = Field(description="A complete, self-contained description of what to do.")
    tool_call_id: Annotated[str, InjectedToolCallId]


def subagent_tool(graph: Any, *, name: str, description: str) -> BaseTool:
    """Wrap a compiled subagent graph (state with `messages`) as a tool for a supervisor.

    The subagent gets the task as a fresh conversation, runs with the caller's config (so it
    streams to the UI and uses the same model), and its last message is the tool result.
    Its transcript is kept as the ToolMessage artifact, so reloaded chats can show its work.
    """

    async def run(
        task: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        config: RunnableConfig,
    ) -> tuple[str, dict[str, Any]]:
        from app.history import to_chat_messages  # lazy: app.history imports this module

        metadata = {
            **(config.get("metadata") or {}),
            SUBAGENT_KEY: name,
            PARENT_TOOL_CALL_KEY: tool_call_id,
        }
        result = await graph.ainvoke(
            {"messages": [HumanMessage(task)]}, {**config, "metadata": metadata}
        )
        messages = result.get("messages") or []
        answer = messages[-1].text if messages else ""
        turns = to_chat_messages(messages, {})
        parts = [p for turn in turns if turn["role"] == "assistant" for p in turn["parts"]]
        return answer, {SUBAGENT_KEY: name, "parts": parts}

    return StructuredTool.from_function(
        coroutine=run,
        name=name,
        description=description,
        args_schema=_Task,
        response_format="content_and_artifact",
    )
