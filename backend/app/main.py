import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Body, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.graph_loader import load_graph
from app.history import first_seen, to_chat_messages
from app.llm import ModelCatalog, ModelError, split_model_id
from app.runs import run_config, stream_run
from app.store import DEFAULT_TITLE, MemoryThreadStore, PostgresThreadStore, ThreadStore
from app.streaming import PROTOCOL_VERSION
from app.titles import fallback_title

log = logging.getLogger("app")

MAX_MESSAGE_CHARS = 100_000


class ThreadCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=200)
    thinking: bool = False


class ThreadUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    model: str | None = Field(default=None, min_length=1, max_length=200)
    thinking: bool | None = None


class RunCreate(BaseModel):
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    model: str | None = Field(default=None, max_length=200)
    thinking: bool | None = None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(), format="%(levelname)s %(name)s %(message)s"
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        pool = None
        if settings.database_url:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            from psycopg.rows import dict_row
            from psycopg_pool import AsyncConnectionPool

            pool = AsyncConnectionPool(
                settings.database_url,
                max_size=10,
                open=False,
                kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            )
            await pool.open(wait=True, timeout=10)
            checkpointer: Any = AsyncPostgresSaver(pool)  # type: ignore[arg-type]
            await checkpointer.setup()
            store: ThreadStore = PostgresThreadStore(pool)
        else:
            from langgraph.checkpoint.memory import InMemorySaver

            log.warning("DATABASE_URL is empty: chats are kept in memory and lost on restart")
            checkpointer = InMemorySaver()
            store = MemoryThreadStore()
        await store.setup()
        app.state.checkpointer = checkpointer
        app.state.store = store
        app.state.graph = await load_graph(settings.graph, checkpointer, settings.graph_pythonpath)
        app.state.active_runs = set()
        log.info("ready: graph %s, storage %s", settings.graph, "postgres" if pool else "memory")
        try:
            yield
        finally:
            if pool is not None:
                await pool.close()

    app = FastAPI(title="LangGraph Chat API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.catalog = ModelCatalog(settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ModelError)
    async def model_error(_: Request, exc: ModelError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    def store_of(request: Request) -> ThreadStore:
        return request.app.state.store  # type: ignore[no-any-return]

    async def thread_or_404(request: Request, thread_id: str) -> Any:
        thread = await store_of(request).get(thread_id)
        if thread is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Thread not found")
        return thread

    # ------------------------------------------------------------------ meta

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/info")
    async def info(request: Request) -> dict[str, Any]:
        return {
            "protocol": PROTOCOL_VERSION,
            "graph": settings.graph,
            "storage": "postgres" if settings.database_url else "memory",
        }

    @app.get("/api/models")
    async def models(request: Request, refresh: bool = False) -> dict[str, Any]:
        catalog: ModelCatalog = request.app.state.catalog
        listed = await catalog.available(refresh=refresh)
        return {"models": [m.as_dict() for m in listed], "default": await catalog.default(listed)}

    # ------------------------------------------------------------------ threads

    @app.get("/api/threads")
    async def list_threads(request: Request) -> list[dict[str, Any]]:
        return [t.as_dict() for t in await store_of(request).list()]

    @app.post("/api/threads", status_code=status.HTTP_201_CREATED)
    async def create_thread(request: Request, body: ThreadCreate) -> dict[str, Any]:
        if body.model:
            split_model_id(body.model)
        thread = await store_of(request).create(
            title=body.title, model=body.model, thinking=body.thinking
        )
        return thread.as_dict()

    @app.get("/api/threads/{thread_id}")
    async def get_thread(request: Request, thread_id: str) -> dict[str, Any]:
        thread = await thread_or_404(request, thread_id)
        graph = request.app.state.graph
        config = {"configurable": {"thread_id": thread_id}}
        state = await graph.aget_state(config)
        messages = (state.values or {}).get("messages") or []
        timestamps = await first_seen(graph, config)
        return {**thread.as_dict(), "messages": to_chat_messages(messages, timestamps)}

    @app.patch("/api/threads/{thread_id}")
    async def update_thread(request: Request, thread_id: str, body: ThreadUpdate) -> dict[str, Any]:
        await thread_or_404(request, thread_id)
        if body.model:
            split_model_id(body.model)
        thread = await store_of(request).update(
            thread_id,
            title=body.title.strip() if body.title else None,
            model=body.model,
            thinking=body.thinking,
        )
        assert thread is not None
        return thread.as_dict()

    @app.delete("/api/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_thread(request: Request, thread_id: str) -> Response:
        await thread_or_404(request, thread_id)
        if thread_id in request.app.state.active_runs:
            raise HTTPException(status.HTTP_409_CONFLICT, "Stop the running reply first")
        await request.app.state.checkpointer.adelete_thread(thread_id)
        await store_of(request).delete(thread_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # ------------------------------------------------------------------ runs

    @app.post("/api/threads/{thread_id}/runs")
    async def create_run(
        request: Request, thread_id: str, body: Annotated[RunCreate, Body()]
    ) -> StreamingResponse:
        """Send a user message and stream the graph's reply as Server-Sent Events."""
        thread = await thread_or_404(request, thread_id)
        if thread_id in request.app.state.active_runs:
            raise HTTPException(status.HTTP_409_CONFLICT, "A reply is already streaming here")
        catalog: ModelCatalog = request.app.state.catalog
        model_id = body.model or thread.model or await catalog.default()
        if not model_id:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "No models available: start Ollama and pull a model, or set an API key",
            )
        split_model_id(model_id)
        thinking = thread.thinking if body.thinking is None else body.thinking

        graph = request.app.state.graph
        state = await graph.aget_state(run_config(thread_id, model_id, thinking))
        first_turn = not (state.values or {}).get("messages") and thread.title == DEFAULT_TITLE
        placeholder = fallback_title(body.content)
        await store_of(request).update(
            thread_id, model=model_id, thinking=thinking, title=placeholder if first_turn else None
        )
        return StreamingResponse(
            stream_run(
                graph=graph,
                store=store_of(request),
                thread_id=thread_id,
                content=body.content,
                model_id=model_id,
                thinking=thinking,
                first_turn=first_turn,
                placeholder_title=placeholder,
                active=request.app.state.active_runs,
            ),
            media_type="text/event-stream",
            # No proxy buffering, so tokens reach the browser as they are generated.
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


app = create_app()
