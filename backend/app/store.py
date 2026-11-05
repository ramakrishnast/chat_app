"""Thread metadata for the sidebar (title, model, timestamps).

The conversation itself lives in LangGraph's checkpointer, keyed by the same thread id.
"""

import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Protocol

DEFAULT_TITLE = "New chat"


@dataclass
class Thread:
    id: str
    title: str = DEFAULT_TITLE
    model: str | None = None
    thinking: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "model": self.model,
            "thinking": self.thinking,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class ThreadStore(Protocol):
    async def setup(self) -> None: ...
    async def list(self, limit: int = 500) -> list[Thread]: ...
    async def get(self, thread_id: str) -> Thread | None: ...
    async def create(self, *, title: str | None, model: str | None, thinking: bool) -> Thread: ...
    async def update(self, thread_id: str, **changes: Any) -> Thread | None: ...
    async def set_title_if(self, thread_id: str, *, title: str, current: str) -> bool: ...
    async def delete(self, thread_id: str) -> bool: ...


_UPDATABLE = {"title", "model", "thinking"}


class MemoryThreadStore:
    def __init__(self) -> None:
        self._threads: dict[str, Thread] = {}

    async def setup(self) -> None:
        return None

    async def list(self, limit: int = 500) -> list[Thread]:
        return sorted(self._threads.values(), key=lambda t: t.updated_at, reverse=True)[:limit]

    async def get(self, thread_id: str) -> Thread | None:
        return self._threads.get(thread_id)

    async def create(self, *, title: str | None, model: str | None, thinking: bool) -> Thread:
        thread = Thread(
            id=str(uuid.uuid4()), title=title or DEFAULT_TITLE, model=model, thinking=thinking
        )
        self._threads[thread.id] = thread
        return thread

    async def update(self, thread_id: str, **changes: Any) -> Thread | None:
        thread = self._threads.get(thread_id)
        if thread is None:
            return None
        values = {k: v for k, v in changes.items() if k in _UPDATABLE and v is not None}
        thread = replace(thread, **values, updated_at=datetime.now(UTC))
        self._threads[thread_id] = thread
        return thread

    async def set_title_if(self, thread_id: str, *, title: str, current: str) -> bool:
        thread = self._threads.get(thread_id)
        if thread is None or thread.title != current:
            return False
        self._threads[thread_id] = replace(thread, title=title)
        return True

    async def delete(self, thread_id: str) -> bool:
        return self._threads.pop(thread_id, None) is not None


class PostgresThreadStore:
    """Uses the same psycopg pool as the checkpointer (autocommit, dict rows)."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def setup(self) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_threads (
                    id uuid PRIMARY KEY,
                    title text NOT NULL,
                    model text,
                    thinking boolean NOT NULL DEFAULT false,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS chat_threads_updated_at "
                "ON chat_threads (updated_at DESC)"
            )

    @staticmethod
    def _row(row: dict[str, Any] | None) -> Thread | None:
        if row is None:
            return None
        return Thread(**{**row, "id": str(row["id"])})

    async def list(self, limit: int = 500) -> list[Thread]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT * FROM chat_threads ORDER BY updated_at DESC LIMIT %s", (limit,)
            )
            return [t for t in map(self._row, await cur.fetchall()) if t]

    async def get(self, thread_id: str) -> Thread | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute("SELECT * FROM chat_threads WHERE id = %s", (thread_id,))
            return self._row(await cur.fetchone())

    async def create(self, *, title: str | None, model: str | None, thinking: bool) -> Thread:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO chat_threads (id, title, model, thinking) VALUES (%s, %s, %s, %s) "
                "RETURNING *",
                (uuid.uuid4(), title or DEFAULT_TITLE, model, thinking),
            )
            thread = self._row(await cur.fetchone())
            assert thread is not None
            return thread

    async def update(self, thread_id: str, **changes: Any) -> Thread | None:
        values = {k: v for k, v in changes.items() if k in _UPDATABLE and v is not None}
        sets = "".join(f"{key} = %({key})s, " for key in values)  # keys come from _UPDATABLE
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE chat_threads SET {sets}updated_at = now() WHERE id = %(id)s RETURNING *",
                {**values, "id": thread_id},
            )
            return self._row(await cur.fetchone())

    async def set_title_if(self, thread_id: str, *, title: str, current: str) -> bool:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE chat_threads SET title = %s WHERE id = %s AND title = %s",
                (title, thread_id, current),
            )
            return cur.rowcount > 0

    async def delete(self, thread_id: str) -> bool:
        async with self._pool.connection() as conn:
            cur = await conn.execute("DELETE FROM chat_threads WHERE id = %s", (thread_id,))
            return cur.rowcount > 0
