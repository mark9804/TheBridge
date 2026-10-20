from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, Header
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from thebridge_core.artifacts import ArtifactStore
from thebridge_core.dsl import TaskCatalog
from thebridge_core.events import Event, EventBus
from thebridge_core.plugins import PluginHost

events = EventBus()
tasks = TaskCatalog()
artifacts = ArtifactStore()
host = PluginHost(tasks, artifacts, events)


class HealthResponse(BaseModel):
    status: str
    version: str


class PluginSummary(BaseModel):
    id: str
    version: str
    active: bool
    provides: tuple[str, ...]
    requires: tuple[str, ...]


class TaskSummary(BaseModel):
    id: str
    title: str
    stage: Literal["draft", "stable"]
    available: bool
    missing_services: list[str]
    missing_artifacts: list[str]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configs: dict[str, object] = {
        "builtin.android-adb": {
            "adb_path": os.environ.get("THEBRIDGE_ADB", "adb"),
            "serial": os.environ.get("THEBRIDGE_SERIAL") or None,
            "timeout_seconds": os.environ.get("THEBRIDGE_ADB_TIMEOUT", "10"),
        }
    }
    if priority := os.environ.get("THEBRIDGE_COMMISSION_PRIORITY"):
        configs["builtin.azurlane-cn"] = {
            "commission_priority": [item.strip() for item in priority.split(",")]
        }
    host.discover(configs)
    configured = os.environ.get("THEBRIDGE_PLUGINS", "builtin.azurlane-cn")
    enabled = {item.strip() for item in configured.split(",") if item.strip()}
    await host.start(enabled)
    app.state.host = host
    try:
        yield
    finally:
        await host.stop()


app = FastAPI(title="TheBridge", version="0.1.0", lifespan=lifespan)


@app.get("/api/v1/health")
def health() -> HealthResponse:
    return HealthResponse(status="ok", version=app.version)


@app.get("/api/v1/plugins")
def list_plugins() -> list[PluginSummary]:
    return [
        PluginSummary(
            id=plugin_id,
            version=registered.plugin.spec.version,
            active=registered.active,
            provides=registered.plugin.spec.provides,
            requires=registered.plugin.spec.requires,
        )
        for plugin_id, registered in sorted(host.plugins.items())
    ]


@app.get("/api/v1/tasks")
def list_tasks() -> list[TaskSummary]:
    result: list[TaskSummary] = []
    for task in tasks.all():
        missing_services = [service for service in task.requires if service not in host.services]
        missing_artifacts = artifacts.missing(task.artifacts)
        result.append(
            TaskSummary(
                id=task.id,
                title=task.title,
                stage=task.stage,
                available=not missing_services and not missing_artifacts,
                missing_services=missing_services,
                missing_artifacts=missing_artifacts,
            )
        )
    return result


@app.get("/api/v1/events")
def list_events(after: int = 0) -> list[Event]:
    return events.snapshot(after)


@app.get("/api/v1/events/stream")
async def stream_events(
    after: int = 0,
    last_event_id: Annotated[int | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    cursor = max(after, last_event_id or 0)

    async def generate() -> AsyncIterator[str]:
        async with events.subscribe(cursor) as queue:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"id: {event.id}\ndata: {event.model_dump_json()}\n\n"
                except TimeoutError:
                    yield ": keepalive\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


web_dist = Path(__file__).resolve().parents[2] / "web" / "dist"
if web_dist.is_dir():
    app.mount("/", StaticFiles(directory=web_dist, html=True), name="web")
