import json
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage

from app.config import Settings
from app.fake_model import ScriptedChatModel
from app.llm import register_model
from app.main import create_app

SCRIPT_MODEL = "fake:script"


def delegate_then_answer() -> list[AIMessage]:
    """Supervisor delegates to the writer subagent, then answers."""
    return [
        AIMessage(
            "Let me ask the writer.",
            tool_calls=[{"name": "writer", "args": {"task": "Write a haiku"}, "id": "call_1"}],
        ),
        AIMessage("Leaves fall softly down"),  # the writer subagent
        AIMessage("Here is your haiku."),  # the supervisor's final answer
    ]


@pytest.fixture
def script() -> list[AIMessage]:
    return delegate_then_answer()


@pytest.fixture
def model(script: list[AIMessage]) -> ScriptedChatModel:
    instance = ScriptedChatModel()
    instance.script = script  # share the list, so tests can rewrite it before running
    register_model(
        SCRIPT_MODEL,
        lambda thinking: (
            instance.model_copy(update={"thinking": "Pondering it." if thinking else ""})
            if thinking
            else instance
        ),
    )
    return instance


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": "",
        "graph": "agents.example.graph:builder",
        "default_model": SCRIPT_MODEL,
        "enable_fake_model": True,
        "openai_api_key": "",
        "anthropic_api_key": "",
        "ollama_base_url": "http://127.0.0.1:9",  # nothing listens: Ollama "unavailable"
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def settings() -> Settings:
    url = os.environ.get("TEST_DATABASE_URL", "")
    return make_settings(database_url=url) if os.environ.get("USE_POSTGRES") else make_settings()


@pytest.fixture
async def client(settings: Settings, model: ScriptedChatModel) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        if settings.database_url:  # the test database is wiped before every test
            async with app.state.store._pool.connection() as conn:
                await conn.execute(
                    "TRUNCATE chat_threads, checkpoints, checkpoint_blobs, checkpoint_writes"
                )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            c.app = app  # type: ignore[attr-defined]
            yield c


def parse_sse(body: str) -> list[dict[str, Any]]:
    events = []
    for block in body.strip().split("\n\n"):
        data = [line[6:] for line in block.splitlines() if line.startswith("data: ")]
        if data:
            events.append(json.loads("\n".join(data)))
    return events


async def run(client: httpx.AsyncClient, thread_id: str, content: str, **extra: Any) -> list[dict]:
    response = await client.post(
        f"/api/threads/{thread_id}/runs", json={"content": content, **extra}
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return parse_sse(response.text)


async def new_thread(client: httpx.AsyncClient, **body: Any) -> str:
    response = await client.post("/api/threads", json=body)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])
