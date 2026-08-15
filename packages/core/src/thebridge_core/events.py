from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from itertools import count
from typing import Any

from pydantic import BaseModel, ConfigDict


class Event(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    ts: datetime
    kind: str
    source: str
    run_id: str | None = None
    payload: dict[str, Any]


class EventBus:
    def __init__(self, history_size: int = 1000) -> None:
        self._ids = count(1)
        self._history: deque[Event] = deque(maxlen=history_size)
        self._subscribers: set[asyncio.Queue[Event]] = set()

    def emit(
        self,
        kind: str,
        source: str,
        payload: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> Event:
        event = Event(
            id=next(self._ids),
            ts=datetime.now(UTC),
            kind=kind,
            source=source,
            run_id=run_id,
            payload=payload or {},
        )
        self._history.append(event)
        for queue in tuple(self._subscribers):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)
        return event

    def snapshot(self, after: int = 0) -> list[Event]:
        return [event for event in self._history if event.id > after]

    @asynccontextmanager
    async def subscribe(self, after: int = 0) -> AsyncIterator[asyncio.Queue[Event]]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._history.maxlen or 0)
        for event in self.snapshot(after):
            queue.put_nowait(event)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)
