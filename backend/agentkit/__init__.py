"""Helpers for graph authors. Import these from your LangGraph nodes and tools.

    from agentkit import get_model, subagent_tool

- `get_model(config)` returns the chat model the user picked in the UI (Ollama, OpenAI or
  Anthropic, with the Think switch applied). Never hard-code an LLM in a node.
- `subagent_tool(graph, name=..., description=...)` turns a compiled subagent graph into a
  tool for a supervisor, and tags its run so the UI nests its output under that tool call.
"""

from agentkit.models import get_model, model_settings
from agentkit.subagents import subagent_tool

__all__ = ["get_model", "model_settings", "subagent_tool"]
