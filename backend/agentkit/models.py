from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig

MODEL_KEY = "model"
THINKING_KEY = "thinking"


def model_settings(config: RunnableConfig | None) -> tuple[str | None, bool]:
    """(model id, thinking) the app put in `config["configurable"]`, if any."""
    configurable: dict[str, Any] = (config or {}).get("configurable") or {}
    return configurable.get(MODEL_KEY), bool(configurable.get(THINKING_KEY, False))


def get_model(
    config: RunnableConfig | None,
    *,
    default: str | None = None,
    thinking: bool | None = None,
) -> BaseChatModel:
    """The chat model chosen for this run.

    Order: the model in `config["configurable"]["model"]` (set by the app per chat), then
    `default`, then DEFAULT_MODEL from .env. Outside the app (a notebook, `langgraph dev`)
    pass it yourself: `graph.invoke(inputs, {"configurable": {"model": "ollama:qwen3:0.6b"}})`.
    `thinking` overrides the UI's Think switch, e.g. False for a fast routing call.
    """
    from app.config import get_settings
    from app.llm import ModelError, build_chat_model

    model_id, think = model_settings(config)
    model_id = model_id or default or get_settings().default_model
    if not model_id:
        raise ModelError(
            "No model chosen: pass {'configurable': {'model': '<provider>:<name>'}} "
            "or set DEFAULT_MODEL in .env"
        )
    return build_chat_model(model_id, thinking=think if thinking is None else thinking)
