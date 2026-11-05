"""Model registry: which chat models exist, and building one from a "<provider>:<name>" id.

Graphs never construct their own LLM. The backend passes the chosen model id (and the Think
switch) in `config["configurable"]`, and nodes call `agentkit.get_model(config)`, which lands
here. That keeps Ollama, OpenAI and Anthropic interchangeable per chat.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import httpx
from langchain_core.language_models import BaseChatModel

from app.config import Settings, get_settings

log = logging.getLogger(__name__)

PROVIDERS = ("ollama", "openai", "anthropic", "fake")
FAKE_MODEL_ID = "fake:echo"


class ModelError(Exception):
    """The model id is malformed, its provider is not configured, or listing failed."""


@dataclass(frozen=True)
class ModelInfo:
    id: str  # "<provider>:<name>"
    provider: str
    name: str
    thinking: bool  # whether the Think toggle does anything for this model
    detail: str | None = None  # e.g. "8B" for Ollama models

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider,
            "name": self.name,
            "thinking": self.thinking,
            "detail": self.detail,
        }


def split_model_id(model_id: str) -> tuple[str, str]:
    provider, sep, name = model_id.partition(":")
    if not sep or not name or provider not in PROVIDERS:
        raise ModelError(
            f"Model id {model_id!r} must look like '<provider>:<name>' with provider one of "
            f"{', '.join(PROVIDERS)}"
        )
    return provider, name


# ------------------------------------------------------------------ listing


class ModelCatalog:
    OLLAMA_CACHE_SECONDS = 30.0

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._ollama: list[ModelInfo] = []
        self._ollama_at = 0.0

    async def _ollama_models(self, refresh: bool) -> list[ModelInfo]:
        fresh = time.monotonic() - self._ollama_at < self.OLLAMA_CACHE_SECONDS
        if self._ollama and fresh and not refresh:
            return self._ollama
        try:
            async with httpx.AsyncClient(base_url=self._settings.ollama_base_url) as client:
                response = await client.get("/api/tags", timeout=5.0)
                response.raise_for_status()
                raw_models = response.json().get("models", [])
                models = []
                for raw in raw_models:
                    capabilities = raw.get("capabilities")
                    if capabilities is None:  # older Ollama: ask per model
                        show = await client.post("/api/show", json={"model": raw["name"]})
                        capabilities = (
                            show.json().get("capabilities", []) if show.is_success else []
                        )
                    if capabilities and "completion" not in capabilities:
                        continue  # embedding-only models
                    models.append(
                        ModelInfo(
                            id=f"ollama:{raw['name']}",
                            provider="ollama",
                            name=raw["name"],
                            thinking="thinking" in capabilities,
                            detail=(raw.get("details") or {}).get("parameter_size"),
                        )
                    )
        except (httpx.HTTPError, ValueError) as exc:
            log.info("ollama unavailable", extra={"error": str(exc)})
            return []
        models.sort(key=lambda m: m.name)
        self._ollama, self._ollama_at = models, time.monotonic()
        return models

    async def available(self, *, refresh: bool = False) -> list[ModelInfo]:
        s = self._settings
        models = await self._ollama_models(refresh)
        if s.openai_api_key:
            models += [
                ModelInfo(id=f"openai:{n}", provider="openai", name=n, thinking=True)
                for n in s.openai_models
            ]
        if s.anthropic_api_key:
            models += [
                ModelInfo(id=f"anthropic:{n}", provider="anthropic", name=n, thinking=True)
                for n in s.anthropic_models
            ]
        if s.enable_fake_model:
            models.append(ModelInfo(id=FAKE_MODEL_ID, provider="fake", name="echo", thinking=True))
        return models

    async def default(self, models: list[ModelInfo] | None = None) -> str | None:
        if self._settings.default_model:
            return self._settings.default_model
        models = models if models is not None else await self.available()
        return models[0].id if models else None


# ------------------------------------------------------------------ building

# Model ids handled by custom code instead of a provider (tests, or your own wrappers).
_registered: dict[str, Callable[[bool], BaseChatModel]] = {}


def register_model(model_id: str, factory: Callable[[bool], BaseChatModel]) -> None:
    """Serve `model_id` from `factory(thinking)`, ahead of the built-in providers."""
    _registered[model_id] = factory


def build_chat_model(model_id: str, *, thinking: bool = False) -> BaseChatModel:
    """Return a (cached) chat model for `model_id`; `thinking` turns on provider reasoning."""
    if model_id in _registered:
        return _registered[model_id](thinking)
    return _build(model_id, thinking)


@lru_cache(maxsize=64)
def _build(model_id: str, thinking: bool) -> BaseChatModel:
    s = get_settings()
    provider, name = split_model_id(model_id)

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        # reasoning=False explicitly disables thinking on models that think by default
        # (qwen3 & co. are slow with it on); True returns it separately from the answer.
        return ChatOllama(
            model=name,
            base_url=s.ollama_base_url,
            reasoning=thinking,
            client_kwargs={"timeout": s.model_timeout},
        )

    if provider == "openai":
        if not s.openai_api_key:
            raise ModelError("OPENAI_API_KEY is not set")
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {
            "model": name,
            "api_key": s.openai_api_key,
            "timeout": s.model_timeout,
        }
        if s.openai_base_url:
            kwargs["base_url"] = s.openai_base_url
        if thinking:
            kwargs["reasoning"] = {"effort": "medium", "summary": "auto"}
        return ChatOpenAI(**kwargs)

    if provider == "anthropic":
        if not s.anthropic_api_key:
            raise ModelError("ANTHROPIC_API_KEY is not set")
        from langchain_anthropic import ChatAnthropic

        budget = s.anthropic_thinking_budget
        kwargs = {
            "model": name,
            "api_key": s.anthropic_api_key,
            "timeout": s.model_timeout,
            "max_tokens": budget + 8192 if thinking else 8192,
        }
        if thinking:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
        return ChatAnthropic(**kwargs)

    # fake
    from app.fake_model import ScriptedChatModel

    return ScriptedChatModel(thinking="Let me think about that." if thinking else "", delay=0.03)
