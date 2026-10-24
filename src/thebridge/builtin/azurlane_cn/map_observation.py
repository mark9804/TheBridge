from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Literal, Protocol, Self
from uuid import uuid4

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from thebridge_core.contracts import Frame, Rect
from thebridge_core.events import EventBus
from thebridge_core.plugins import PluginContext, PluginSpec

from thebridge.builtin.azurlane_cn.battlefield import Cell, Enemy, Mobility


class CellBox(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    cell: Cell
    box: Rect


class BoardObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    frame_id: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    stable: bool
    active_fleet: Literal[1, 2]
    origin: Cell
    guard_count: int | None = Field(ge=0)
    mobility: Mobility
    walkable_cells: tuple[Cell, ...]
    blocked_cells: tuple[Cell, ...] = ()
    allowed_cells: tuple[Cell, ...] | None = None
    cells: tuple[CellBox, ...]
    enemies: tuple[Enemy, ...]

    @field_validator("active_fleet", mode="before")
    @classmethod
    def validate_fleet_type(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("active_fleet must be an integer")
        return value

    @model_validator(mode="after")
    def validate_unique_cells(self) -> Self:
        for name, cells in (
            ("cells", tuple(item.cell for item in self.cells)),
            ("enemies", tuple(enemy.cell for enemy in self.enemies)),
            ("walkable_cells", self.walkable_cells),
            ("blocked_cells", self.blocked_cells),
            ("allowed_cells", self.allowed_cells or ()),
        ):
            if len(set(cells)) != len(cells):
                raise ValueError(f"{name} must contain distinct cells")
        return self

    def validate_frame(self, frame: Frame) -> Self:
        if (self.frame_id, self.width, self.height) != (frame.id, frame.width, frame.height):
            raise ValueError("map observation must match the current frame id and dimensions")
        if any(not item.box.fits(frame) for item in self.cells):
            raise ValueError("map cell boxes must fit the original frame")
        return self


class MapObserver(Protocol):
    async def observe(self, frame: Frame) -> BoardObservation: ...


class LocalMapObserver:
    def __init__(self, directory: Path, events: EventBus) -> None:
        self.directory = directory
        self.events = events
        self._frame: Frame | None = None
        self._requests: dict[int, Path] = {}
        self._responses: dict[int, BoardObservation] = {}
        self.schema_path = directory / "observation.schema.json"
        self.schema_path.write_text(
            json.dumps(BoardObservation.model_json_schema(), indent=2), encoding="utf-8"
        )

    async def observe(self, frame: Frame) -> BoardObservation:
        if frame is not self._frame:
            if frame.id in self._requests:
                raise ValueError("map input frame id was reused; create a new observer for replay")
            self._frame = frame
        if frame.id in self._responses:
            return self._responses[frame.id].validate_frame(frame)
        if frame.id not in self._requests:
            directory = self.directory / f"{frame.id:06d}"
            directory.mkdir(parents=True, exist_ok=False)
            image_path = directory / "frame.png"
            response_path = directory / "response.json"
            request_path = directory / "request.json"
            Image.fromarray(frame.image[:, :, ::-1]).save(image_path)
            request = {
                "frame_id": frame.id,
                "width": frame.width,
                "height": frame.height,
                "image_path": str(image_path),
                "response_path": str(response_path),
                "schema_path": str(self.schema_path),
                "instructions": (
                    "Write one JSON object matching schema_path to response_path. "
                    "Cells are [column, row]; box is {left, top, right, bottom} in original "
                    "image pixels. Describe only this frame; do not infer unknown terrain."
                ),
            }
            request_path.write_text(json.dumps(request, indent=2), encoding="utf-8")
            self._requests[frame.id] = response_path
            self.events.emit(
                "bridge.event.observation-required",
                "builtin.azurlane-map-input",
                request | {"request_path": str(request_path)},
            )
        response_path = self._requests[frame.id]
        # Poll only for operator input; game state is never inferred from elapsed time.
        while not response_path.exists():
            await asyncio.sleep(0.2)
        try:
            observation = BoardObservation.model_validate_json(
                response_path.read_text(encoding="utf-8")
            ).validate_frame(frame)
        except ValueError as exc:
            raise ValueError(f"invalid map observation in {response_path}: {exc}") from exc
        self._responses[frame.id] = observation
        return observation


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_dir: Path | None = None


class LocalMapObserverPlugin:
    spec = PluginSpec(
        id="builtin.azurlane-map-input",
        version="0.1.0",
        provides=("azurlane-cn.map-observer@1",),
    )
    config_model = Config

    async def activate(self, context: PluginContext, config: BaseModel) -> None:
        parsed = Config.model_validate(config)
        cache_root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        root = parsed.request_dir or cache_root / "thebridge" / "map-input"
        directory = root.expanduser().resolve() / uuid4().hex
        directory.mkdir(parents=True, exist_ok=False)
        context.provide("azurlane-cn.map-observer@1", LocalMapObserver(directory, context.events))

    async def deactivate(self) -> None:
        return None


def create_plugin() -> LocalMapObserverPlugin:
    return LocalMapObserverPlugin()


async def check_map_observation() -> None:
    from tempfile import TemporaryDirectory

    import numpy as np

    frame = Frame(7, np.zeros((20, 30, 3), dtype=np.uint8))
    data = {
        "frame_id": 7,
        "width": 30,
        "height": 20,
        "stable": True,
        "active_fleet": 1,
        "origin": [0, 0],
        "guard_count": 1,
        "mobility": "unrestricted",
        "walkable_cells": [[0, 0], [1, 0]],
        "cells": [{"cell": [1, 0], "box": {"left": 10, "top": 0, "right": 20, "bottom": 10}}],
        "enemies": [{"cell": [1, 0], "strength": 2}],
    }
    parsed = BoardObservation.model_validate_json(json.dumps(data)).validate_frame(frame)
    assert parsed.enemies == (Enemy((1, 0), strength=2),)
    for changed in (
        data | {"frame_id": 6},
        data | {"width": 31},
        data | {"active_fleet": True},
        data | {"cells": data["cells"] * 2},
        data | {"enemies": data["enemies"] * 2},
        data
        | {
            "cells": [
                {
                    "cell": [1, 0],
                    "box": {"left": 10, "top": 0, "right": 31, "bottom": 10},
                }
            ]
        },
    ):
        try:
            BoardObservation.model_validate_json(json.dumps(changed)).validate_frame(frame)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid map observation must be rejected")
    with TemporaryDirectory(prefix="thebridge-map-check-") as temporary:
        events = EventBus()
        observer = LocalMapObserver(Path(temporary), events)
        pending = asyncio.create_task(observer.observe(frame))
        await asyncio.sleep(0)
        assert not pending.done()
        request = events.snapshot()[0].payload
        assert request["frame_id"] == 7
        assert json.loads(Path(request["schema_path"]).read_text())["title"] == "BoardObservation"
        with Image.open(request["image_path"]) as image:
            assert image.size == (30, 20)
        Path(request["response_path"]).write_text(json.dumps(data), encoding="utf-8")
        assert await pending == parsed
        assert await observer.observe(frame) == parsed
        try:
            await observer.observe(Frame(frame.id, np.ones_like(frame.image)))
        except ValueError as exc:
            assert "reused" in str(exc)
        else:
            raise AssertionError("reused frame ids must not reuse old observations")
        assert len(events.snapshot()) == 1


if __name__ == "__main__":
    asyncio.run(check_map_observation())
    print("Map observation check passed")
