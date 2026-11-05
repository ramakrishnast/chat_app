from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langgraph.config import get_config

from agentkit.models import get_model


class UseChatModel(AgentMiddleware):
    """Run every model call of a `create_agent` agent on the model picked in the UI.

    The app puts the chosen model id and the Think switch in the run config; this swaps
    them in before each call, so the `model=` given to create_agent is only a fallback.
    """

    def wrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> Any:
        return handler(request.override(model=get_model(get_config())))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> Any:
        return await handler(request.override(model=get_model(get_config())))


def default_model() -> Any:
    """The `model=` to give create_agent: replaced on every call by UseChatModel."""
    from app.fake_model import ScriptedChatModel

    return ScriptedChatModel()
