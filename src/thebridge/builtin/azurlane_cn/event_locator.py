from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from thebridge_core.contracts import Frame, Match
from thebridge_core.events import EventBus
from thebridge_core.plugins import PluginContext, PluginSpec

from thebridge.builtin.text_locator.plugin import TextLocator, TextRule

from .battlefield import Cell, select_target
from .map_observation import BoardObservation, MapObserver


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str | None = Field(default=None, pattern=r"^(T[1-6]|SP)$")
    policy: Literal["clear_all", "boss_first"] = "clear_all"
    mob_fleet: Literal[1, 2] = 1
    boss_fleet: Literal[1, 2] = 2
    rules: dict[str, TextRule] = Field(default_factory=dict)


@dataclass(frozen=True)
class PendingAction:
    frame_id: int
    kind: Literal["switch", "move", "attack"]
    fleet: int
    origin: Cell
    destination: Cell | None = None
    boss: bool = False


class EventLocator(TextLocator):
    """Keep activity-specific state while the DSL owns all device input."""

    def __init__(self, ocr: Any, observer: MapObserver, config: Config, events: EventBus) -> None:
        super().__init__(ocr, config.rules)
        if config.stage is None:
            raise ValueError("Event configuration requires stage")
        if config.mob_fleet == config.boss_fleet:
            raise ValueError("Mob and boss fleets must be distinct")
        self.config = config
        self.observer = observer
        self.events = events
        self.stage_pattern = re.compile(rf"^{re.escape(config.stage)}(?!\d).+")
        self.pending: PendingAction | None = None
        self.combat_is_boss = False
        self.boss_won = False
        self.clear_blocker = False
        self._board_frame: Frame | None = None
        self._board: BoardObservation | None = None
        self._blocked_reported = False

    async def _text_match(self, frame: Frame, pattern: str) -> Match | None:
        candidates = [box for box, text in await self.read_texts(frame) if re.search(pattern, text)]
        if len(candidates) != 1:
            return None
        box = candidates[0]
        return Match(frame.id, box.box, box.confidence)

    async def _selection_page(self, frame: Frame) -> Match | None:
        texts = await self.read_texts(frame)
        if not any(text == "出击" for _, text in texts):
            return None
        if any(
            re.search(r"舰队选择|关卡产出|结算奖励|SETTLEREWARDS|再次前往|战斗评价", text, re.I)
            for _, text in texts
        ):
            return None
        return await self._text_match(frame, self.stage_pattern.pattern)

    async def _board_for(self, frame: Frame) -> BoardObservation:
        if self._board_frame is not frame:
            board = (await self.observer.observe(frame)).validate_frame(frame)
            fleets = {
                int(match.group(1))
                for _, text in await self.read_texts(frame)
                if (match := re.match(r"FLEET[.:：]?([12])", text, re.I))
            }
            if fleets and fleets != {board.active_fleet}:
                raise ValueError("Map observation fleet disagrees with the current FLEET label")
            self._board_frame, self._board = frame, board
        assert self._board is not None
        return self._board

    async def _map_action(self, frame: Frame) -> Match | None:
        if self.pending is not None or await self.locate(frame, "event.map") is None:
            return None
        board = await self._board_for(frame)
        if not board.stable:
            return None
        bosses = tuple(enemy for enemy in board.enemies if enemy.boss)
        guards = tuple(enemy for enemy in board.enemies if not enemy.boss)
        pursue_boss = (
            bool(bosses)
            and not self.clear_blocker
            and (self.config.policy == "boss_first" or (board.guard_count == 0 and not guards))
        )
        fleet = self.config.boss_fleet if pursue_boss else self.config.mob_fleet
        if board.active_fleet != fleet:
            switch = await self._text_match(frame, r"^切换$")
            if switch is None:
                return None
            self.pending = PendingAction(frame.id, "switch", fleet, board.origin)
            self._emit_decision(frame, "switch", fleet=fleet)
            return switch

        selection = select_target(
            walkable_cells=set(board.walkable_cells),
            origin=board.origin,
            blocked_cells=set(board.blocked_cells)
            | ({enemy.cell for enemy in bosses} if self.clear_blocker else set()),
            enemies=guards if self.clear_blocker else board.enemies,
            guard_count=board.guard_count,
            mobility=board.mobility,
            allowed_cells=None if board.allowed_cells is None else set(board.allowed_cells),
            policy=self.config.policy,
        )
        if selection.stop_reason is not None:
            raise RuntimeError(
                f"Map needs another observation or manual action: {selection.stop_reason}"
            )
        assert selection.target is not None
        if pursue_boss and not selection.target.boss:
            # A blocking guard is a mob-fleet job; retry the boss route after that battle.
            self.clear_blocker = True
            return await self._map_action(frame)
        destination = selection.path[-1]
        boxes = [item.box for item in board.cells if item.cell == destination]
        if len(boxes) != 1:
            raise RuntimeError(f"Map endpoint {destination} has no unique visible cell box")
        kind = "attack" if selection.reaches_target else "move"
        self.pending = PendingAction(
            frame.id, kind, fleet, board.origin, destination, selection.target.boss
        )
        self._emit_decision(
            frame,
            kind,
            fleet=fleet,
            destination=destination,
            target=selection.target.cell,
            boss=selection.target.boss,
        )
        return Match(frame.id, boxes[0])

    def _emit_decision(self, frame: Frame, kind: str, **payload: object) -> None:
        self.events.emit(
            "bridge.event.map-decision",
            "builtin.azurlane-event",
            {"frame_id": frame.id, "kind": kind, "policy": self.config.policy, **payload},
        )

    async def _map_outcome(self, frame: Frame) -> Match | None:
        pending = self.pending
        if pending is None:
            # Confirmation may precede a stable next decision by several frames.
            return await self.locate(frame, "event.map")
        if frame.id <= pending.frame_id:
            return None
        ready = await super().locate(frame, "battle.ready")
        if ready is not None:
            if pending.kind != "attack":
                raise RuntimeError("Unexpected battle after a movement or fleet switch")
            self.combat_is_boss = pending.boss
            self.pending = None
            return ready
        if pending.kind == "attack":
            # An attack may leave a transitional map frame before battle preparation appears.
            return None
        map_match = await self.locate(frame, "event.map")
        if map_match is None:
            return None
        if pending.kind == "switch":
            fleet = await self._text_match(frame, rf"(?i)^FLEET[.:：]?{pending.fleet}(?!\d)")
            if fleet is None:
                return None
            self.pending = None
            return map_match
        board = await self._board_for(frame)
        if not board.stable or board.origin == pending.origin:
            return None
        if board.active_fleet != pending.fleet:
            raise RuntimeError("Active fleet changed during movement")
        if board.origin != pending.destination:
            raise RuntimeError("Fleet stopped before the selected endpoint; inspect reachability")
        self.pending = None
        return map_match

    async def locate(self, frame: Frame, locator_id: str) -> Match | None:
        if not locator_id.startswith("event."):
            return await super().locate(frame, locator_id)
        if locator_id == "event.map":
            return await super().locate(frame, "entry.map")
        if locator_id == "event.map-action":
            return await self._map_action(frame)
        if locator_id == "event.map-outcome":
            return await self._map_outcome(frame)
        if locator_id == "event.stage-select":
            match = await self._selection_page(frame)
            if match is None or self.boss_won:
                return None
            if self.config.stage == "SP":
                counts = [
                    int(found.group(1))
                    for _, text in await self.read_texts(frame)
                    if (found := re.search(r"今日次数[:：](\d+)/\d+", text))
                ]
                if counts != [1]:
                    raise RuntimeError("SP attempt count is exhausted or not uniquely recognized")
            return match
        if locator_id == "event.briefing-go":
            if await self._text_match(frame, self.stage_pattern.pattern) is None:
                return None
            return await super().locate(frame, "entry.briefing")
        if locator_id == "event.fleets-go":
            if self.config.stage == "SP":
                return None
            return await super().locate(frame, "entry.fleets")
        if locator_id == "event.needs-fleets":
            title = await self._text_match(frame, r"^舰队选择$")
            if title is None:
                return None
            texts = await self.read_texts(frame)
            blocked = self.config.stage == "SP" or any(
                re.search(r"可出击舰队数[:：][01]/2", text) for _, text in texts
            )
            if not blocked:
                return None
            if not self._blocked_reported:
                self.events.emit(
                    "bridge.event.input-required",
                    "builtin.azurlane-event",
                    {
                        "reason": "SP fleet entry needs a populated visual sample"
                        if self.config.stage == "SP"
                        else "Both surface fleets must be populated",
                        "frame_id": frame.id,
                    },
                )
                self._blocked_reported = True
            return title
        if locator_id == "event.victory":
            match = await super().locate(frame, "battle.victory")
            if match is not None:
                if self.combat_is_boss:
                    self.boss_won = True
                else:
                    self.clear_blocker = False
            return match
        if locator_id == "event.completed":
            return await self._selection_page(frame) if self.boss_won else None
        if locator_id == "event.returning":
            for name in ("battle.settlement-leave", "event.completed", "event.map"):
                match = await self.locate(frame, name)
                if match is not None:
                    if name == "event.map":
                        self.combat_is_boss = False
                        self.boss_won = False
                    return match
            return None
        if locator_id == "event.screen":
            for name in (
                "event.needs-fleets",
                "battle.settlement-leave",
                "event.completed",
                "event.briefing-go",
                "event.fleets-go",
                "battle.ready",
                "battle.victory",
                "battle.reward",
                "battle.after-reward",
                "event.map",
                "event.stage-select",
            ):
                match = await self.locate(frame, name)
                if match is not None:
                    return match
            return None
        raise KeyError(locator_id)


class EventPlugin:
    spec = PluginSpec(
        id="builtin.azurlane-event",
        version="0.1.0",
        requires=("vision.text@1", "azurlane-cn.map-observer@1"),
        provides=("vision.locator@1",),
    )
    config_model = Config

    async def activate(self, context: PluginContext, config: BaseModel) -> None:
        context.provide(
            "vision.locator@1",
            EventLocator(
                context.require("vision.text@1"),
                context.require("azurlane-cn.map-observer@1"),
                Config.model_validate(config),
                context.events,
            ),
        )

    async def deactivate(self) -> None:
        return None


def create_plugin() -> EventPlugin:
    return EventPlugin()


async def check_event() -> None:
    from pathlib import Path

    import numpy as np
    from thebridge_core.contracts import Rect
    from thebridge_core.dsl import load_task
    from thebridge_core.runner import StateRunner

    from thebridge.builtin.macos_vision.plugin import TextBox

    from .battlefield import Enemy
    from .map_observation import CellBox

    task = load_task(Path(__file__).with_name("tasks") / "event-stage.yaml")
    rules = Config.model_validate(task.parameters["plugins"]["builtin.azurlane-event"]).rules
    pixels = np.zeros((60, 80, 3), dtype=np.uint8)
    map1, map2 = ("迎击", "切换", "FLEET.1"), ("迎击", "切换", "FLEET.2")
    ready = ("出击", "编队", "击破敌方舰队")
    victory, reward = ("点击继续", "战斗评价", "大获全胜S"), ("获得道具", "点击继续")
    report, selection = ("EXP+100", "确定"), ("出击", "T1星空倒转之日", "作战模式")

    class Replay:
        def __init__(self, screens, boards):
            self.screens, self.boards = screens, boards
            self.index, self.backs = 0, 0
            self.taps = []

        async def screenshot(self):
            assert self.index < len(self.screens), "event flow requested an unexpected frame"
            self.index += 1
            return Frame(self.index, pixels)

        async def tap(self, point):
            self.taps.append((self.index, point))

        async def back(self):
            self.backs += 1

        async def read(self, frame):
            return tuple(
                TextBox(text, Rect(1, 1, 8, 8), 1.0) for text in self.screens[frame.id - 1]
            )

        async def observe(self, frame):
            return self.boards[frame.id]

    def board(frame_id, **changes):
        cells = tuple((x, y) for x in range(3) for y in range(2))
        return BoardObservation(
            **dict(
                frame_id=frame_id,
                width=80,
                height=60,
                stable=True,
                active_fleet=1,
                origin=(0, 0),
                guard_count=1,
                mobility="unrestricted",
                walkable_cells=cells,
                cells=tuple(
                    CellBox(cell=(x, y), box=Rect(x * 10, y * 10 + 20, x * 10 + 8, y * 10 + 28))
                    for x, y in cells
                ),
                enemies=(Enemy((2, 0)),),
            )
            | changes
        )

    def case(screens, boards, *, stage="T1", policy="clear_all"):
        replay = Replay(screens, boards)
        locator = EventLocator(
            replay, replay, Config(stage=stage, policy=policy, rules=rules), EventBus()
        )
        return locator, replay

    # Movement and delayed fleet switching must finish before another action is chosen.
    screens = [map1] * 4 + [ready] * 2 + [victory, reward, report]
    screens += [map1] * 3 + [map2] * 4 + [ready] * 2
    screens += [victory, reward, report, selection, selection]
    boss = dict(guard_count=0, enemies=(Enemy((2, 1), boss=True),))
    # Attack transition frames 4 and 16 deliberately have no structured map response.
    boards = {
        2: board(2, mobility="bounded", allowed_cells=((1, 0),)),
        3: board(3, origin=(1, 0)),
        11: board(11, origin=(2, 0), **boss),
        13: board(13, origin=(0, 1), active_fleet=2, stable=False, **boss),
        14: board(14, origin=(0, 1), active_fleet=2, stable=False, **boss),
        15: board(15, origin=(0, 1), active_fleet=2, **boss),
    }
    locator, replay = case(screens, boards)
    result = await StateRunner(locator.events).run(task, replay, locator, timeout_seconds=1)
    assert result.final_state == "completed" and len(replay.taps) == 12 and replay.backs == 0
    assert not any(frame_id in (4, 12, 13, 14, 16) for frame_id, _ in replay.taps)
    events = locator.events.snapshot()
    decisions = [e.payload for e in events if e.kind == "bridge.event.map-decision"]
    assert [item["kind"] for item in decisions] == ["move", "attack", "switch", "attack"]
    assert [item["fleet"] for item in decisions] == [1, 1, 2, 2]

    mixed = (Enemy((1, 0)), Enemy((2, 0), boss=True))
    for policy, active, corridor, expected_kind, expected_fleet in (
        ("clear_all", 1, False, "attack", 1),
        ("boss_first", 1, False, "switch", 2),
        ("boss_first", 2, True, "switch", 1),
    ):
        changes = {"walkable_cells": ((0, 0), (1, 0), (2, 0))} if corridor else {}
        locator, replay = case(
            [map1 if active == 1 else map2],
            {1: board(1, active_fleet=active, enemies=mixed, **changes)},
            policy=policy,
        )
        frame = Frame(1, pixels)
        assert await locator.locate(frame, "event.map-action") is not None
        assert locator.pending is not None
        assert (locator.pending.kind, locator.pending.fleet) == (expected_kind, expected_fleet)
        assert await locator.locate(frame, "event.map-outcome") is None
        assert await locator.locate(frame, "event.map-action") is None
        if corridor:
            replay.screens += [map1, ready, victory, map1]
            replay.boards[2] = board(2, guard_count=None, enemies=mixed, **changes)
            replay.boards[5] = board(5, guard_count=None, enemies=(mixed[1],), **changes)
            assert await locator.locate(Frame(2, pixels), "event.map-outcome") is not None
            assert await locator.locate(Frame(2, pixels), "event.map-action") is not None
            assert locator.pending.kind == "attack" and not locator.pending.boss
            assert await locator.locate(Frame(3, pixels), "event.map-outcome") is not None
            assert await locator.locate(Frame(4, pixels), "event.victory") is not None
            assert not locator.clear_blocker
            assert await locator.locate(Frame(5, pixels), "event.map-action") is not None
            assert locator.pending.kind == "switch" and locator.pending.fleet == 2

    locator, _ = case([victory, selection], {})
    assert await locator.locate(Frame(1, pixels), "event.victory") is not None
    assert not locator.boss_won
    assert await locator.locate(Frame(2, pixels), "event.completed") is None

    fleets = ("舰队选择", "可出击舰队数：0/2", "立刻前往")
    locator, replay = case([fleets, fleets], {}, stage="SP")
    result = await StateRunner(locator.events).run(task, replay, locator, timeout_seconds=1)
    assert result.final_state == "needs-fleets" and replay.taps == [] and replay.backs == 0
    assert sum(e.kind == "bridge.event.input-required" for e in locator.events.snapshot()) == 1

    locator, replay = case([map1, map1], {2: board(1)})
    try:
        await StateRunner(locator.events).run(task, replay, locator, timeout_seconds=1)
    except ValueError as exc:
        assert "current frame" in str(exc)
    else:
        raise AssertionError("stale map observations must not produce input")
    assert replay.taps == [] and replay.backs == 0
    print("Event locator check passed")
