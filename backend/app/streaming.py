"""Translate LangGraph `astream(..., version="v2")` parts into the chat stream contract.

The graph runs with stream_mode=["messages", "updates", "tasks"] and subgraphs=True:
  messages -> `text` / `reasoning` deltas, token by token, from any LLM call at any depth
  updates  -> `tool_call` (complete args) and `tool_result`, once per id
  tasks    -> `step_start` / `step_end` for every node, so the UI can show progress

Every event says where it came from: `ns` (node path, outermost first) and
`parent_tool_call_id`, which is set when the event belongs to a subagent working on that
tool call. Events with no parent are the supervisor's own answer. See docs/stream-contract.md.
"""

import json
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from agentkit.subagents import PARENT_TOOL_CALL_KEY, SUBAGENT_KEY

PROTOCOL_VERSION = 1
STREAM_MODES = ["messages", "updates", "tasks"]


def ns_path(ns: Sequence[str]) -> list[str]:
    """('tools:3f2a…', 'writer:91c0…') -> ['tools', 'writer']"""
    return [segment.split(":", 1)[0] for segment in ns]


def blocks(message: BaseMessage) -> list[dict[str, Any]]:
    try:
        return list(message.content_blocks)  # normalised across Ollama, OpenAI, Anthropic
    except Exception:  # a provider shape langchain doesn't know; fall back to plain text
        return [{"type": "text", "text": message.text}]


def text_and_reasoning(message: BaseMessage) -> tuple[str, str]:
    text, reasoning = [], []
    for block in blocks(message):
        if block.get("type") == "text":
            text.append(block.get("text") or "")
        elif block.get("type") == "reasoning":
            reasoning.append(block.get("reasoning") or "")
    return "".join(text), "".join(reasoning)


def tool_output_text(message: ToolMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    text = message.text
    return text if text else json.dumps(content, default=str)


def _messages_in(update: Any) -> list[BaseMessage]:
    if not isinstance(update, dict):
        return []
    value = update.get("messages")
    if isinstance(value, BaseMessage):
        return [value]
    if isinstance(value, list | tuple):
        return [m for m in value if isinstance(m, BaseMessage)]
    return []


class StreamTranslator:
    def __init__(self) -> None:
        self._tool_calls: set[str] = set()
        self._tool_results: set[str] = set()
        self._pending: list[tuple[str, int]] = []  # (tool_call_id, ns depth), oldest first
        self._ns_parent: dict[tuple[str, ...], str] = {}
        self._main_text: dict[str, str] = {}  # message id -> streamed answer text
        self._completed: set[str] = set()  # message ids that reached the graph state
        self.last_root_node: str | None = None

    # -------------------------------------------------------------- attribution

    def _parent(self, ns: tuple[str, ...], meta: dict[str, Any] | None = None) -> str | None:
        if meta and meta.get(PARENT_TOOL_CALL_KEY):
            self._ns_parent[ns] = meta[PARENT_TOOL_CALL_KEY]
            return str(meta[PARENT_TOOL_CALL_KEY])
        for i in range(len(ns), 0, -1):
            if ns[:i] in self._ns_parent:
                return self._ns_parent[ns[:i]]
        # A subgraph called from inside a tool without subagent_tool(): attribute it to the
        # oldest tool call still running at a shallower depth.
        for call_id, depth in self._pending:
            if depth < len(ns):
                return call_id
        return None

    # -------------------------------------------------------------- translation

    def feed(self, part: dict[str, Any]) -> list[dict[str, Any]]:
        kind = part.get("type")
        ns = tuple(part.get("ns") or ())
        data = part.get("data")
        if kind == "messages":
            return self._on_message(ns, data)
        if kind == "updates":
            return self._on_updates(ns, data)
        if kind == "tasks":
            return self._on_task(ns, data)
        return []

    def _on_task(self, ns: tuple[str, ...], data: Any) -> list[dict[str, Any]]:
        if not isinstance(data, dict) or str(data.get("name", "")).startswith("__"):
            return []
        event: dict[str, Any] = {
            "step_id": data.get("id"),
            "node": data.get("name"),
            "ns": ns_path(ns),
            "parent_tool_call_id": self._parent(ns),
        }
        if "input" in data:
            if not ns:
                self.last_root_node = data.get("name")
            return [{"type": "step_start", **event}]
        error = data.get("error")
        return [{"type": "step_end", **event, "error": str(error) if error else None}]

    def _on_message(self, ns: tuple[str, ...], data: Any) -> list[dict[str, Any]]:
        try:
            message, meta = data
        except (TypeError, ValueError):
            return []
        if not isinstance(message, AIMessage):
            return []  # user input and tool results come through `updates`
        text, reasoning = text_and_reasoning(message)
        if not text and not reasoning:
            return []
        meta = meta if isinstance(meta, dict) else {}
        parent = self._parent(ns, meta)
        base = {
            "message_id": message.id,
            "ns": ns_path(ns),
            "node": meta.get("langgraph_node"),
            "parent_tool_call_id": parent,
            "agent": meta.get(SUBAGENT_KEY) if parent else None,
        }
        events = []
        if reasoning:
            events.append({"type": "reasoning", **base, "delta": reasoning})
        if text:
            events.append({"type": "text", **base, "delta": text})
            if parent is None and message.id:
                self._main_text[message.id] = self._main_text.get(message.id, "") + text
        return events

    def _on_updates(self, ns: tuple[str, ...], data: Any) -> list[dict[str, Any]]:
        if not isinstance(data, dict):
            return []
        events: list[dict[str, Any]] = []
        for node, update in data.items():
            if node == "__interrupt__":
                events.append({"type": "interrupt", "value": json.dumps(update, default=str)})
                continue
            for message in _messages_in(update):
                if message.id:
                    self._completed.add(message.id)
                if isinstance(message, AIMessage):
                    events += self._tool_calls_of(ns, node, message)
                elif isinstance(message, ToolMessage):
                    events += self._tool_result_of(ns, message)
        return events

    def _tool_calls_of(self, ns: tuple[str, ...], node: str, message: AIMessage) -> list[dict]:
        events = []
        parent = self._parent(ns)
        for call in message.tool_calls:
            call_id = call.get("id")
            if not call_id or call_id in self._tool_calls:
                continue
            self._tool_calls.add(call_id)
            self._pending.append((call_id, len(ns)))
            events.append(
                {
                    "type": "tool_call",
                    "tool_call_id": call_id,
                    "name": call.get("name"),
                    "args": call.get("args") or {},
                    "message_id": message.id,
                    "ns": ns_path(ns),
                    "node": node,
                    "parent_tool_call_id": parent,
                }
            )
        return events

    def _tool_result_of(self, ns: tuple[str, ...], message: ToolMessage) -> list[dict]:
        call_id = message.tool_call_id
        if call_id in self._tool_results:
            return []
        self._tool_results.add(call_id)
        self._pending = [(c, d) for c, d in self._pending if c != call_id]
        return [
            {
                "type": "tool_result",
                "tool_call_id": call_id,
                "name": message.name,
                "content": tool_output_text(message),
                "status": "error" if message.status == "error" else "success",
                "ns": ns_path(ns),
                "parent_tool_call_id": self._parent(ns),
            }
        ]

    # -------------------------------------------------------------- stop support

    def unfinished_answer(self) -> tuple[str, str] | None:
        """(message id, text) of answer text that streamed but never reached the state."""
        for message_id in reversed(list(self._main_text)):
            text = self._main_text[message_id]
            if message_id not in self._completed and text.strip():
                return message_id, text
        return None


def sse(event: dict[str, Any]) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event, default=str)}\n\n"
