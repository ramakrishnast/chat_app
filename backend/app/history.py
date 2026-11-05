"""Rebuild the chat transcript (in the contract's message shape) from checkpointer state."""

from datetime import datetime
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.pregel import Pregel

from agentkit.subagents import SUBAGENT_KEY
from app.streaming import text_and_reasoning, tool_output_text

# Set in response_metadata on messages the app writes when a run ends early.
ENDED_KEY = "chat_ended"  # "stopped" | "error"


async def first_seen(graph: Pregel, config: RunnableConfig) -> dict[str, datetime]:
    """Message id -> time of the first checkpoint that contained it."""
    seen: dict[str, datetime] = {}
    snapshots = [s async for s in graph.aget_state_history(config)]
    for snapshot in reversed(snapshots):  # oldest first
        if not snapshot.created_at:
            continue
        created = datetime.fromisoformat(snapshot.created_at)
        for message in (snapshot.values or {}).get("messages", []) or []:
            if isinstance(message, BaseMessage) and message.id and message.id not in seen:
                seen[message.id] = created
    return seen


def to_chat_messages(
    messages: list[BaseMessage], timestamps: dict[str, datetime]
) -> list[dict[str, Any]]:
    """Group state messages into turns: each user message, then one assistant turn holding the
    AI text, reasoning and tool calls (with results) that followed it."""

    def stamp(message: BaseMessage) -> str | None:
        ts = timestamps.get(message.id or "")
        return ts.isoformat() if ts else None

    turns: list[dict[str, Any]] = []
    assistant: dict[str, Any] | None = None
    tools: dict[str, dict[str, Any]] = {}

    for message in messages:
        if isinstance(message, HumanMessage):
            assistant = None
            turns.append(
                {
                    "id": message.id,
                    "role": "user",
                    "created_at": stamp(message),
                    "status": "complete",
                    "parts": [{"type": "text", "text": message.text}],
                }
            )
            continue
        if not isinstance(message, AIMessage | ToolMessage):
            continue  # system messages and custom types stay out of the transcript
        if assistant is None:
            assistant = {
                "id": message.id,
                "role": "assistant",
                "created_at": stamp(message),
                "status": "complete",
                "parts": [],
            }
            turns.append(assistant)

        ended = (message.response_metadata or {}).get(ENDED_KEY)
        if ended in ("stopped", "error"):
            assistant["status"] = ended

        if isinstance(message, ToolMessage):
            part = tools.get(message.tool_call_id)
            if part is not None:
                part["result"] = tool_output_text(message)
                part["status"] = "error" if message.status == "error" else "success"
                artifact = getattr(message, "artifact", None)
                if isinstance(artifact, dict) and artifact.get(SUBAGENT_KEY):
                    part["agent"] = artifact[SUBAGENT_KEY]  # written by agentkit.subagent_tool
                    part["parts"] = artifact.get("parts") or []
            continue

        text, reasoning = text_and_reasoning(message)
        if reasoning:
            assistant["parts"].append({"type": "reasoning", "text": reasoning})
        if text:
            assistant["parts"].append({"type": "text", "text": text})
        for call in message.tool_calls:
            part = {
                "type": "tool",
                "tool_call_id": call.get("id"),
                "name": call.get("name"),
                "args": call.get("args") or {},
                "result": None,
                "status": "running",
                "agent": None,
                "parts": [],
            }
            tools[str(call.get("id"))] = part
            assistant["parts"].append(part)
    return turns
