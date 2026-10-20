from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from thebridge_core.contracts import Frame, Match, Rect
from thebridge_core.plugins import PluginContext, PluginSpec

from thebridge.builtin.azurlane_cn.exercise import Opponent, select_opponent
from thebridge.builtin.text_locator.plugin import TextLocator, TextRule


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_power: int | None = Field(default=None, gt=0)
    max_refreshes: int | None = Field(default=None, ge=0, le=5)
    rules: dict[str, TextRule] = Field(default_factory=dict)


def same_row(first: Rect, second: Rect) -> bool:
    return min(first.bottom, second.bottom) > max(first.top, second.top)


class ExerciseLocator(TextLocator):
    def __init__(
        self,
        ocr: Any,
        rules: dict[str, TextRule],
        *,
        max_power: int,
        max_refreshes: int,
    ) -> None:
        super().__init__(ocr, rules)
        self.max_power = max_power
        self.max_refreshes = max_refreshes
        self.refreshes = 0
        self.pending_refresh: tuple[tuple[tuple[int, int], ...], int] | None = None

    async def locate(self, frame: Frame, locator_id: str) -> Match | None:
        if locator_id not in {
            "exercise.opponent",
            "exercise.exhausted",
            "exercise.refresh",
            "exercise.start",
        }:
            return await super().locate(frame, locator_id)

        texts = await self.read_texts(frame)
        if locator_id == "exercise.start":
            if not any(text == "演习对手信息" for _, text in texts):
                return None
            strength_labels = sorted(
                (box for box, text in texts if text == "综合实力"),
                key=lambda box: box.box.left,
            )
            if len(strength_labels) != 2:
                return None
            total_power = 0
            for index, label in enumerate(strength_labels):
                right = strength_labels[1].box.left if index == 0 else frame.width
                powers = [
                    int(text)
                    for box, text in texts
                    if re.fullmatch(r"\d+", text)
                    and label.box.right < box.box.left < right
                    and same_row(box.box, label.box)
                ]
                if len(powers) != 1:
                    return None
                total_power += powers[0]
            buttons = [box for box, text in texts if text == "开始演习"]
            if total_power > self.max_power or len(buttons) != 1:
                return None
            return Match(frame.id, buttons[0].box, buttons[0].confidence)

        labels = [box for box, text in texts if text == "演习次数"]
        if len(labels) != 1:
            return None
        remaining = [
            int(match.group(1))
            for box, text in texts
            if (match := re.fullmatch(r"(\d+)/10", text))
            and box.box.left > labels[0].box.right
            and same_row(box.box, labels[0].box)
        ]
        if len(remaining) != 1 or not 0 <= remaining[0] <= 10:
            return None
        if self.pending_refresh is not None and remaining[0] != self.pending_refresh[1]:
            raise RuntimeError("等待刷新确认时演习次数发生变化，停止以避免误计刷新")
        if locator_id == "exercise.exhausted":
            if remaining[0] != 0:
                return None
            return Match(frame.id, labels[0].box, labels[0].confidence)
        if remaining[0] == 0:
            return None

        main_labels = sorted(
            (box for box, text in texts if re.fullmatch(r"主力[：:]?", text)),
            key=lambda box: box.box.left,
        )
        if len(main_labels) != 4:
            return None
        candidates = []
        targets = []
        for index, main in enumerate(main_labels):
            right = main_labels[index + 1].box.left if index < 3 else frame.width
            column_left = (
                (main_labels[index - 1].box.center.x + main.box.center.x) / 2
                if index > 0
                else 0
            )
            column_right = (
                (main.box.center.x + main_labels[index + 1].box.center.x) / 2
                if index < 3
                else frame.width
            )
            vanguards = [
                box
                for box, text in texts
                if re.fullmatch(r"先锋[：:]?", text)
                and column_left <= box.box.center.x < column_right
            ]
            if len(vanguards) != 1:
                return None
            powers = []
            for label in (main, vanguards[0]):
                values = [
                    (box, int(text))
                    for box, text in texts
                    if re.fullmatch(r"\d+", text)
                    and label.box.right < box.box.left < right
                    and same_row(box.box, label.box)
                ]
                if len(values) != 1:
                    return None
                powers.append(values[0])
            candidates.append(Opponent(index, powers[0][1], powers[1][1]))
            targets.append(powers[0][0])

        signature = tuple(
            (candidate.main_power, candidate.vanguard_power) for candidate in candidates
        )
        if self.pending_refresh is not None:
            previous, _ = self.pending_refresh
            if signature == previous:
                return None
            self.refreshes += 1
            self.pending_refresh = None

        chosen = select_opponent(candidates, self.max_power)
        if locator_id == "exercise.opponent":
            if chosen is None:
                return None
            target = targets[chosen.index]
            return Match(frame.id, target.box, target.confidence)
        if chosen is not None:
            return None
        if self.refreshes >= self.max_refreshes:
            raise RuntimeError("无合格对手且本轮刷新额度已用尽")
        buttons = [box for box, text in texts if re.fullmatch(r"更[换換]对手", text)]
        if len(buttons) != 1:
            return None
        # The runner taps returned matches; confirm the changed list before another action.
        self.pending_refresh = signature, remaining[0]
        return Match(frame.id, buttons[0].box, buttons[0].confidence)


class ExercisePlugin:
    spec = PluginSpec(
        id="builtin.azurlane-exercise",
        version="0.1.0",
        requires=("vision.text@1",),
        provides=("vision.locator@1",),
    )
    config_model = Config

    async def activate(self, context: PluginContext, config: BaseModel) -> None:
        parsed = Config.model_validate(config)
        if parsed.max_power is None or parsed.max_refreshes is None:
            raise ValueError("Exercise configuration requires max_power and max_refreshes")
        context.provide(
            "vision.locator@1",
            ExerciseLocator(
                context.require("vision.text@1"),
                parsed.rules,
                max_power=parsed.max_power,
                max_refreshes=parsed.max_refreshes,
            ),
        )

    async def deactivate(self) -> None:
        return None


def create_plugin() -> ExercisePlugin:
    return ExercisePlugin()


if __name__ == "__main__":
    import asyncio

    import numpy as np

    from thebridge.builtin.macos_vision.plugin import TextBox

    class FakeOcr:
        calls = 0

        def __init__(self, remaining: int = 10, missing: bool = False) -> None:
            self.remaining = remaining
            self.missing = missing
            self.powers = ((14248, 11543), (1372, 2846), (15065, 13389), (16946, 13679))

        async def read(self, frame: Frame) -> tuple[TextBox, ...]:
            self.calls += 1
            boxes = [
                TextBox("通习", Rect(1, 1, 40, 20), 1),
                TextBox("演习次数", Rect(400, 20, 460, 40), 1),
                TextBox(f"{self.remaining}/10", Rect(470, 20, 510, 40), 1),
                TextBox("更换对手", Rect(450, 160, 530, 180), 1),
            ]
            for index, (main, vanguard) in enumerate(self.powers):
                left = index * 100 + 1
                vanguard_left = left - 5 if index else left
                boxes.extend(
                    (
                        TextBox("主力：", Rect(left, 60, left + 40, 80), 1),
                        TextBox(str(main), Rect(left + 45, 60, left + 95, 80), 1),
                        TextBox(
                            "先锋：", Rect(vanguard_left, 90, vanguard_left + 40, 110), 1
                        ),
                    )
                )
                if not (self.missing and index == 3):
                    boxes.append(
                        TextBox(str(vanguard), Rect(left + 45, 90, left + 95, 110), 1)
                    )
            return tuple(boxes)

    async def check() -> None:
        frame = Frame(1, np.zeros((200, 550, 3), dtype=np.uint8))
        ocr = FakeOcr()
        locator = ExerciseLocator(ocr, {}, max_power=26000, max_refreshes=5)
        chosen = await locator.locate(frame, "exercise.opponent")
        assert chosen is not None and chosen.box.left == 146
        assert await locator.locate(frame, "exercise.refresh") is None
        assert await locator.locate(frame, "exercise.exhausted") is None
        assert ocr.calls == 1
        low_limit = ExerciseLocator(FakeOcr(), {}, max_power=1, max_refreshes=5)
        assert await low_limit.locate(frame, "exercise.opponent") is None
        assert await low_limit.locate(frame, "exercise.refresh") is not None
        incomplete = ExerciseLocator(FakeOcr(missing=True), {}, max_power=1, max_refreshes=5)
        assert await incomplete.locate(frame, "exercise.opponent") is None
        assert await incomplete.locate(frame, "exercise.refresh") is None
        exhausted = ExerciseLocator(FakeOcr(remaining=0), {}, max_power=26000, max_refreshes=5)
        assert await exhausted.locate(frame, "exercise.exhausted") is not None
        assert await exhausted.locate(frame, "exercise.opponent") is None
        refresh_ocr = FakeOcr()
        refresh = ExerciseLocator(refresh_ocr, {}, max_power=1, max_refreshes=1)
        assert await refresh.locate(frame, "exercise.refresh") is not None
        assert await refresh.locate(frame, "exercise.refresh") is None
        assert await refresh.locate(frame, "exercise.opponent") is None
        assert refresh.refreshes == 0
        refresh_ocr.powers = ((14249, 11543), *refresh_ocr.powers[1:])
        refreshed = Frame(2, frame.image)
        assert await refresh.locate(refreshed, "exercise.opponent") is None
        assert refresh.refreshes == 1 and refresh.pending_refresh is None
        try:
            await refresh.locate(refreshed, "exercise.refresh")
        except RuntimeError as exc:
            assert "本轮刷新额度已用尽" in str(exc)
        else:
            raise AssertionError("exhausted refresh budget must stop the run")
        for budget in (0, 5):
            changed_ocr = FakeOcr()
            changed = ExerciseLocator(changed_ocr, {}, max_power=1, max_refreshes=budget)
            try:
                await changed.locate(frame, "exercise.refresh")
                changed_ocr.remaining = 0
                await changed.locate(Frame(3, frame.image), "exercise.exhausted")
            except RuntimeError as exc:
                assert "额度已用尽" in str(exc) if budget == 0 else "次数发生变化" in str(exc)
            else:
                raise AssertionError("invalid refresh state must stop the run")
        print("Exercise locator check passed")

    asyncio.run(check())
