from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from thebridge_core.contracts import Frame, Match, Rect
from thebridge_core.plugins import PluginContext, PluginSpec


class TextRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pattern: re.Pattern[str]
    anchor: re.Pattern[str] | None = None
    require: tuple[re.Pattern[str], ...] = ()
    absent: tuple[re.Pattern[str], ...] = ()
    index: int = Field(default=0, ge=0)
    offset: tuple[float, float] = (0.0, 0.0)


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: dict[str, TextRule] = Field(default_factory=dict)


class TextLocator:
    def __init__(self, ocr: Any, rules: dict[str, TextRule]) -> None:
        self.ocr = ocr
        self.rules = rules
        self._frame: Frame | None = None
        self._texts: tuple[tuple[Any, str], ...] = ()

    async def read_texts(self, frame: Frame) -> tuple[tuple[Any, str], ...]:
        if self._frame is not frame:
            boxes = await self.ocr.read(frame)
            self._texts = tuple((box, re.sub(r"\s+", "", box.text)) for box in boxes)
            self._frame = frame
        return self._texts

    async def locate(self, frame: Frame, locator_id: str) -> Match | None:
        rule = self.rules[locator_id]
        texts = await self.read_texts(frame)
        if any(not any(pattern.search(text) for _, text in texts) for pattern in rule.require):
            return None
        if any(pattern.search(text) for pattern in rule.absent for _, text in texts):
            return None

        candidates = [box for box, text in texts if rule.pattern.search(text)]
        if rule.anchor is not None:
            anchors = [box.box for box, text in texts if rule.anchor.search(text)]
            candidates = [
                candidate
                for candidate in candidates
                if any(
                    abs(candidate.box.center.y - anchor.center.y)
                    <= 1.5
                    * max(candidate.box.bottom - candidate.box.top, anchor.bottom - anchor.top)
                    for anchor in anchors
                )
            ]
        candidates.sort(key=lambda item: (item.box.top, item.box.left))
        if rule.index >= len(candidates):
            return None
        selected = candidates[rule.index]
        box = selected.box
        height = box.bottom - box.top
        dx, dy = (round(value * height) for value in rule.offset)
        left, top = box.left + dx, box.top + dy
        right, bottom = box.right + dx, box.bottom + dy
        if left < 0 or top < 0 or right > frame.width or bottom > frame.height:
            return None
        return Match(frame.id, Rect(left, top, right, bottom), selected.confidence)


class TextLocatorPlugin:
    spec = PluginSpec(
        id="builtin.text-locator",
        version="0.1.0",
        requires=("vision.text@1",),
        provides=("vision.locator@1",),
    )
    config_model = Config

    async def activate(self, context: PluginContext, config: BaseModel) -> None:
        parsed = Config.model_validate(config)
        context.provide(
            "vision.locator@1",
            TextLocator(context.require("vision.text@1"), parsed.rules),
        )

    async def deactivate(self) -> None:
        return None


def create_plugin() -> TextLocatorPlugin:
    return TextLocatorPlugin()


if __name__ == "__main__":
    import asyncio

    import numpy as np

    from thebridge.builtin.macos_vision.plugin import TextBox

    class FakeOcr:
        calls = 0

        async def read(self, frame: Frame) -> tuple[TextBox, ...]:
            self.calls += 1
            return (
                TextBox("任务", Rect(1, 1, 10, 10), 1.0),
                TextBox("前 往", Rect(70, 20, 90, 30), 0.9),
                TextBox("后宅补充食物", Rect(5, 60, 60, 70), 0.8),
                TextBox("前往", Rect(70, 61, 90, 71), 0.9),
            )

    async def check() -> None:
        rules = Config.model_validate(
            {
                "rules": {
                    "food": {"pattern": "^前往$", "anchor": "后宅", "require": ["任务"]},
                    "second": {"pattern": "前往", "index": 1},
                    "blocked": {"pattern": "前往", "absent": ["任务"]},
                    "missing": {"pattern": "前往", "require": ["不存在"]},
                    "shifted": {"pattern": "前往", "index": 1, "offset": [1, -3]},
                    "outside": {"pattern": "前往", "index": 1, "offset": [0, -8]},
                }
            }
        ).rules
        ocr = FakeOcr()
        locator = TextLocator(ocr, rules)
        frame = Frame(1, np.zeros((100, 100, 3), dtype=np.uint8))
        food = await locator.locate(frame, "food")
        assert food is not None and food.box == Rect(70, 61, 90, 71)
        assert await locator.locate(frame, "second") == food
        assert await locator.locate(frame, "blocked") is None
        assert await locator.locate(frame, "missing") is None
        shifted = await locator.locate(frame, "shifted")
        assert shifted is not None and shifted.box == Rect(80, 31, 100, 41)
        assert await locator.locate(frame, "outside") is None
        assert ocr.calls == 1
        await locator.locate(Frame(1, frame.image), "food")
        assert ocr.calls == 2
        print("Text locator check passed")

    asyncio.run(check())
