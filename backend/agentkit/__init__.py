"""Helpers for graph authors. Import these from your LangGraph nodes and tools.

    from agentkit import UseChatModel, default_model, get_model, subagent_tool

- `UseChatModel()` is middleware for `create_agent`: every model call uses the model picked
  in the UI. Pass `model=default_model()` to create_agent as the (never used) fallback.

- `get_model(config)` returns the chat model the user picked in the UI (Ollama, OpenAI or
  Anthropic, with the Think switch applied). Never hard-code an LLM in a node.
- `subagent_tool(graph, name=..., description=...)` turns a compiled subagent graph into a
  tool for a supervisor, and tags its run so the UI nests its output under that tool call.
"""

from agentkit.middleware import UseChatModel, default_model
from agentkit.models import get_model, model_settings
from agentkit.subagents import subagent_tool

__all__ = ["UseChatModel", "default_model", "get_model", "model_settings", "subagent_tool"]
