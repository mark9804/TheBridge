from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from thebridge_core.contracts import Frame, Match
from thebridge_core.plugins import PluginContext, PluginSpec

from thebridge.builtin.text_locator.plugin import TextLocator, TextRule


class Stages(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    hard: str = Field(pattern=r"^[1-9]\d*-[1-9]\d*$")
    normal: str = Field(pattern=r"^[1-9]\d*-[1-9]\d*$")


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stages: Stages | None = None
    mode: Literal["hard", "normal"] | None = None
    runs: int | None = Field(default=None, ge=1, le=3)
    rules: dict[str, TextRule] = Field(default_factory=dict)


class CampaignLocator(TextLocator):
    def __init__(
        self,
        ocr: Any,
        rules: dict[str, TextRule],
        *,
        stage: str,
        mode: Literal["hard", "normal"],
        runs: int,
    ) -> None:
        super().__init__(ocr, rules)
        self.chapter = int(stage.split("-", 1)[0])
        self.stage_pattern = re.compile(rf"^{re.escape(stage)}(?!\d)")
        self.mode = mode
        self.runs = runs

    async def locate(self, frame: Frame, locator_id: str) -> Match | None:
        if locator_id not in {
            "campaign.next-chapter",
            "campaign.previous-chapter",
            "campaign.mode-switch",
            "campaign.stage",
            "campaign.briefing-go",
            "campaign.runs-increase",
            "campaign.runs-decrease",
            "campaign.runs-start",
            "campaign.result-leave",
        }:
            return await super().locate(frame, locator_id)

        texts = await self.read_texts(frame)
        if locator_id == "campaign.briefing-go":
            if not any(self.stage_pattern.search(text) for _, text in texts):
                return None
            candidates = [box for box, text in texts if text == "立刻前往"]
            if len(candidates) != 1:
                return None
            selected = candidates[0]
            return Match(frame.id, selected.box, selected.confidence)

        if locator_id == "campaign.result-leave":
            if not any("合计获得奖励" in text for _, text in texts) or not any(
                "连续作战已完成" in text for _, text in texts
            ):
                return None
            results = [
                match
                for _, text in texts
                if (
                    match := re.fullmatch(
                        r"计划连续作战(\d+)次，实际完成作战(\d+)次[。.]?", text
                    )
                )
            ]
            if len(results) != 1 or any(
                int(value) != self.runs for value in results[0].groups()
            ):
                return None
            candidates = [box for box, text in texts if text == "离开"]
            if len(candidates) != 1:
                return None
            selected = candidates[0]
            return Match(frame.id, selected.box, selected.confidence)

        if locator_id.startswith("campaign.runs-"):
            labels = [box for box, text in texts if text == "作战次数"]
            if len(labels) != 1 or not any(text == "连续作战" for _, text in texts):
                return None
            anchor = labels[0].box
            counts = [
                (box, int(text))
                for box, text in texts
                if re.fullmatch(r"\d+", text)
                and box.box.left > anchor.right
                and abs(box.box.center.y - anchor.center.y)
                <= 1.5 * max(box.box.bottom - box.box.top, anchor.bottom - anchor.top)
            ]
            if len(counts) != 1:
                return None
            current_runs = counts[0][1]
            if locator_id == "campaign.runs-increase":
                if current_runs >= self.runs:
                    return None
                return await super().locate(frame, "campaign.runs-plus")
            if locator_id == "campaign.runs-decrease":
                if current_runs <= self.runs:
                    return None
                return await super().locate(frame, "campaign.runs-minus")
            if current_runs != self.runs:
                return None
            candidates = [box for box, text in texts if text == "出击"]
            if len(candidates) != 1:
                return None
            selected = candidates[0]
            return Match(frame.id, selected.box, selected.confidence)

        chapters = {
            int(match.group(1))
            for _, text in texts
            if (match := re.fullmatch(r"第(\d+)章", text))
        }
        if len(chapters) != 1:
            return None
        current_chapter = next(iter(chapters))

        if locator_id == "campaign.next-chapter":
            if current_chapter >= self.chapter:
                return None
            candidates = [box for box, text in texts if text == "下一章"]
        elif locator_id == "campaign.previous-chapter":
            if current_chapter <= self.chapter:
                return None
            candidates = [box for box, text in texts if text == "上一章"]
        else:
            # The map button names the mode it switches to, not the active mode.
            switches = {text for _, text in texts if text in {"困难", "普通"}}
            if len(switches) != 1:
                return None
            switch_label = next(iter(switches))
            desired_switch = "困难" if self.mode == "hard" else "普通"
            if locator_id == "campaign.mode-switch":
                if switch_label != desired_switch:
                    return None
                candidates = [box for box, text in texts if text == desired_switch]
            else:
                if current_chapter != self.chapter or switch_label == desired_switch:
                    return None
                candidates = [
                    box for box, text in texts if self.stage_pattern.search(text)
                ]
        if len(candidates) != 1:
            return None
        selected = candidates[0]
        return Match(frame.id, selected.box, selected.confidence)


class CampaignPlugin:
    spec = PluginSpec(
        id="builtin.azurlane-campaign",
        version="0.1.0",
        requires=("vision.text@1",),
        provides=("vision.locator@1",),
    )
    config_model = Config

    async def activate(self, context: PluginContext, config: BaseModel) -> None:
        parsed = Config.model_validate(config)
        if parsed.stages is None or parsed.mode is None or parsed.runs is None:
            raise ValueError("Campaign configuration requires stages, mode, and runs")
        stage = parsed.stages.hard if parsed.mode == "hard" else parsed.stages.normal
        context.provide(
            "vision.locator@1",
            CampaignLocator(
                context.require("vision.text@1"),
                parsed.rules,
                stage=stage,
                mode=parsed.mode,
                runs=parsed.runs,
            ),
        )

    async def deactivate(self) -> None:
        return None


def create_plugin() -> CampaignPlugin:
    return CampaignPlugin()
