from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, model_validator
from thebridge_core.contracts import Frame, Match, Rect
from thebridge_core.events import EventBus
from thebridge_core.plugins import PluginContext, PluginSpec

from thebridge.builtin.text_locator.plugin import TextLocator, TextRule

from .story_nodes import STORY_CODE, find_story_nodes, read_story_progress


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: dict[str, TextRule] = Field(default_factory=dict)
    swipe_region: tuple[float, float, float, float] | None = None
    max_swipes_without_progress: int | None = Field(default=None, ge=2)

    @model_validator(mode="after")
    def valid_region(self):
        if self.swipe_region is None:
            return self
        left, top, right, bottom = self.swipe_region
        if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
            raise ValueError("swipe_region must be a normalized rectangle")
        return self


class StoryLocator(TextLocator):
    def __init__(self, ocr, config: Config, events: EventBus):
        if config.swipe_region is None or config.max_swipes_without_progress is None:
            raise ValueError("Story scanning requires swipe_region and max_swipes_without_progress")
        super().__init__(ocr, config.rules)
        self.config, self.events = config, events
        self.direction = "left"
        self.swipes = 0
        self.boundaries = 0
        self.pending_count: int | None = None
        self.entered = False
        self.progress: tuple[int, int] | None = None
        self.previous_layout: tuple[float, ...] = ()
        self.previous_labels: tuple[str, ...] = ()
        self.previous_progress: tuple[int, int] | None = None
        self.swipe_layout: tuple[float, ...] | None = None
        self.swipe_labels: tuple[str, ...] = ()
        self.list_frame: Frame | None = None
        self.list_match: Match | None = None
        self.counter_frame: Frame | None = None
        self.counter_result = (None, None)
        self.candidates = ()

    @staticmethod
    def _same_layout(first, second):
        return (
            bool(first)
            and len(first) == len(second)
            and all(abs(a - b) < 0.01 for a, b in zip(first, second, strict=True))
        )

    def _emit(self, kind, **data):
        self.events.emit(f"bridge.story.{kind}", "builtin.azurlane-story", data)

    async def _counter(self, frame):
        if self.counter_frame is frame:
            return self.counter_result
        self.counter_frame, self.counter_result = frame, (None, None)
        match = await super().locate(frame, "story.returned")
        if match is None:
            return None, None
        progress = await read_story_progress(frame, await self.read_texts(frame), self.ocr)
        self.counter_result = (match, progress)
        return self.counter_result

    async def _list(self, frame):
        if self.list_frame is frame:
            return self.list_match
        self.list_frame, self.list_match = frame, None
        match, progress = await self._counter(frame)
        if match is None or progress is None:
            self.previous_layout = ()
            return None
        texts = await self.read_texts(frame)
        labels = tuple(
            sorted(
                code.upper()
                for box, text in texts
                if 0.35 < box.box.center.y / frame.height < 0.65
                for code in STORY_CODE.findall(text)
            )
        )
        layout = tuple(
            sorted(
                box.box.center.x / frame.width
                for box, text in texts
                if re.fullmatch(r"STORY", text, re.I)
                and 0.3 < box.box.center.y / frame.height < 0.6
            )
        )
        stable = progress == self.previous_progress and self._same_layout(
            layout, self.previous_layout
        )
        self.previous_layout, self.previous_progress = layout, progress
        self.previous_labels = labels
        if not stable:
            return None
        if self.pending_count is not None:
            if progress[0] > self.pending_count:
                self.pending_count = None
                self.entered = False
                self.swipes = self.boundaries = 0
                self.direction = "left"
            elif self.entered:
                raise RuntimeError("Story returned without increasing the completion counter")
            else:
                return None
        if progress != self.progress:
            self._emit("progress", frame_id=frame.id, completed=progress[0], total=progress[1])
            self.progress = progress
        if self.swipe_layout is not None:
            # Equally spaced new nodes can occupy the old nodes' screen positions.
            if (
                labels
                and labels == self.swipe_labels
                and self._same_layout(layout, self.swipe_layout)
            ):
                self.direction = "right" if self.direction == "left" else "left"
                self.boundaries += 1
                self._emit("boundary", frame_id=frame.id, next_direction=self.direction)
            self.swipe_layout = None
        self.candidates = tuple(
            node
            for node in find_story_nodes(frame, texts)
            if not node.completed and not node.locked
        )
        self.list_match = match
        return match

    async def locate(self, frame: Frame, locator_id: str) -> Match | None:
        if not locator_id.startswith("story-nav."):
            match = await super().locate(frame, locator_id)
            if locator_id == "story.playing" and match is not None:
                self.entered = True
                self.previous_layout = ()
            return match
        if locator_id == "story-nav.opened":
            playing = await self.locate(frame, "story.playing")
            if playing is not None:
                return playing
            match, progress = await self._counter(frame)
            if progress and self.pending_count is not None and progress[0] > self.pending_count:
                return match
            return None
        if locator_id == "story-nav.completed":
            match, progress = await self._counter(frame)
            return match if progress and progress[0] == progress[1] else None
        match = await self._list(frame)
        if match is None:
            return None
        if locator_id == "story-nav.list":
            return match
        if locator_id == "story-nav.next":
            if not self.candidates:
                return None
            node = min(self.candidates, key=lambda item: item.box.left)
            self.pending_count, _ = self.progress
            self.entered = False
            self._emit(
                "selected",
                frame_id=frame.id,
                label=node.label,
                completed=self.pending_count,
                gold_fraction=node.gold_fraction,
            )
            return Match(frame.id, node.box)
        if locator_id in ("story-nav.swipe-left", "story-nav.swipe-right"):
            if self.candidates or locator_id != f"story-nav.swipe-{self.direction}":
                return None
            if self.boundaries >= 2 or self.swipes >= self.config.max_swipes_without_progress:
                raise RuntimeError("No unlocked incomplete story found after scanning the list")
            self.swipes += 1
            self.swipe_layout = self.previous_layout
            self.swipe_labels = self.previous_labels
            self.previous_layout = ()
            left, top, right, bottom = self.config.swipe_region
            region = Rect(
                round(left * frame.width),
                round(top * frame.height),
                round(right * frame.width),
                round(bottom * frame.height),
            )
            self._emit("scroll", frame_id=frame.id, direction=self.direction, count=self.swipes)
            return Match(frame.id, region)
        raise KeyError(locator_id)


class StoryPlugin:
    spec = PluginSpec(
        id="builtin.azurlane-story",
        version="0.1.0",
        requires=("vision.text@1",),
        provides=("vision.locator@1",),
    )
    config_model = Config

    async def activate(self, context: PluginContext, config: BaseModel):
        context.provide(
            "vision.locator@1",
            StoryLocator(
                context.require("vision.text@1"), Config.model_validate(config), context.events
            ),
        )

    async def deactivate(self):
        return None


def create_plugin() -> StoryPlugin:
    return StoryPlugin()


async def check_story_navigation() -> None:
    from pathlib import Path
    from unittest.mock import patch

    import numpy as np
    from thebridge_core.dsl import load_task
    from thebridge_core.runner import StateRunner

    from thebridge.builtin.macos_vision.plugin import TextBox

    from .story_nodes import StoryNode, check_story_nodes, check_story_progress_reader

    check_story_nodes()
    await check_story_progress_reader()
    task = load_task(Path(__file__).with_name("tasks") / "event-story-all.yaml")
    config = Config.model_validate(task.parameters["plugins"]["builtin.azurlane-story"])

    class Ocr:
        texts = ()

        async def read(self, frame):
            return self.texts

    ocr = Ocr()
    locator = StoryLocator(ocr, config, EventBus())
    frame_id = 0

    def frame(completed=6, playing=False, node_id="EP2-3"):
        nonlocal frame_id
        frame_id += 1
        values = (
            ("跳过", "自动")
            if playing
            else ("活动・剧情", f"已完成阶段：{completed}/26", "STORY", f"完成{node_id}")
        )
        ocr.texts = tuple(TextBox(value, Rect(50, 40, 100, 50), 1.0) for value in values)
        return Frame(frame_id, np.zeros((100, 200, 3), dtype=np.uint8))

    node = StoryNode("未完成剧情", Rect(50, 50, 100, 60), Rect(20, 40, 40, 60), False, False, 0.0)
    with patch(__name__ + ".find_story_nodes", return_value=(node,)):
        assert await locator.locate(frame(), "story-nav.list") is None
        current = frame()
        assert await locator.locate(current, "story-nav.list") is not None
        assert await locator.locate(current, "story-nav.next") is not None
        assert locator.pending_count == 6
        assert await locator.locate(frame(playing=True), "story.playing") is not None
        assert await locator.locate(frame(7), "story-nav.list") is None
        current = frame(7)
        assert await locator.locate(current, "story-nav.list") is not None
        assert locator.pending_count is None and locator.progress == (7, 26)
        assert await locator.locate(current, "story-nav.next") is not None
        await locator.locate(frame(playing=True), "story.playing")
        await locator.locate(frame(7), "story-nav.list")
        try:
            await locator.locate(frame(7), "story-nav.list")
        except RuntimeError as exc:
            assert "without increasing" in str(exc)
        else:
            raise AssertionError("Unchanged story progress must stop repeated entry")

    locator = StoryLocator(ocr, config, EventBus())
    with patch(__name__ + ".find_story_nodes", return_value=()):
        await locator.locate(frame(node_id="EX-1"), "story-nav.list")
        current = frame(node_id="EX-1")
        await locator.locate(current, "story-nav.list")
        assert await locator.locate(current, "story-nav.swipe-left") is not None
        await locator.locate(frame(node_id="EX-1"), "story-nav.list")
        current = frame(node_id="EX-1")
        await locator.locate(current, "story-nav.list")
        assert locator.direction == "right"
        assert await locator.locate(current, "story-nav.swipe-right") is not None
        await locator.locate(frame(node_id="EP3-1"), "story-nav.list")
        await locator.locate(frame(node_id="EP3-1"), "story-nav.list")
        assert locator.direction == "right" and locator.boundaries == 1
        assert await locator.locate(frame(26), "story-nav.completed") is not None
        assert await locator.locate(frame(25), "story-nav.completed") is None

    class RewardReplay:
        index = 0

        def __init__(self):
            self.taps = []

        async def screenshot(self):
            self.index += 1
            assert self.index <= 6, "Reward exit did not settle"
            return Frame(self.index, np.zeros((100, 200, 3), dtype=np.uint8))

        async def read(self, frame):
            values = (
                ("获得道具", "心智魔方", "点击继续")
                if frame.id <= 2
                else ("活动・剧情", "已完成阶段：26/26已领取", "STORY")
            )
            return tuple(TextBox(value, Rect(50, 40, 100, 50), 1.0) for value in values)

        async def tap(self, point):
            self.taps.append(self.index)

    for filename, terminal in (
        ("event-story-all.yaml", "completed"),
        ("event-story.yaml", "returned"),
    ):
        replay = RewardReplay()
        reward_task = load_task(Path(__file__).with_name("tasks") / filename)
        reward_locator = (
            StoryLocator(replay, config, EventBus())
            if terminal == "completed"
            else TextLocator(
                replay,
                {
                    key: TextRule.model_validate(value)
                    for key, value in reward_task.parameters["locators"].items()
                },
            )
        )
        result = await StateRunner(EventBus()).run(reward_task, replay, reward_locator)
        assert result.final_state == terminal and replay.taps == [1]
    ocr.texts = tuple(
        TextBox(value, Rect(10, 10, 30, 20), 1.0)
        for value in ("获得道具", "特装原型", "蓝图", "点击继续")
    )
    assert (
        await StoryLocator(ocr, config, EventBus()).locate(
            Frame(1, np.zeros((100, 200, 3), dtype=np.uint8)), "story.reward-continue"
        )
        is None
    )
    print("Story navigation checks passed")
