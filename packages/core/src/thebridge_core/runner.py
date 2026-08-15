from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import uuid4

from thebridge_core.contracts import DeviceService, LocatorService
from thebridge_core.dsl import TaskSpec
from thebridge_core.events import EventBus


@dataclass(frozen=True, slots=True)
class RunResult:
    run_id: str
    task_id: str
    final_state: str
    steps: int


class StateRunner:
    def __init__(self, events: EventBus) -> None:
        self.events = events

    async def run(
        self,
        task: TaskSpec,
        device: DeviceService,
        locator: LocatorService,
        timeout_seconds: float = 60.0,
    ) -> RunResult:
        run_id = uuid4().hex
        state_id = task.entry
        entered_state: str | None = None
        steps = 0
        self.events.emit("bridge.run.started", "runner", {"task_id": task.id}, run_id)

        try:
            async with asyncio.timeout(timeout_seconds):
                while True:
                    frame = await device.screenshot()
                    state = task.states[state_id]
                    appeared = await locator.locate(frame, state.expect)
                    if appeared is None:
                        continue
                    if appeared.frame_id != frame.id:
                        raise RuntimeError("locator returned a stale frame")

                    if entered_state != state_id:
                        self.events.emit(
                            "bridge.state.entered",
                            "runner",
                            {"state": state_id, "frame_id": frame.id},
                            run_id,
                        )
                        entered_state = state_id
                    if state.terminal:
                        result = RunResult(run_id, task.id, state_id, steps)
                        self.events.emit(
                            "bridge.run.finished",
                            "runner",
                            {"task_id": task.id, "state": state_id, "steps": steps},
                            run_id,
                        )
                        return result

                    for transition in state.transitions:
                        match = await locator.locate(frame, transition.locate)
                        if match is None:
                            continue
                        if match.frame_id != frame.id:
                            raise RuntimeError("locator returned a stale frame")
                        if not match.box.fits(frame):
                            raise RuntimeError("locator returned a box outside the frame")
                        await device.tap(match.box.center)
                        steps += 1
                        self.events.emit(
                            "bridge.action.finished",
                            "runner",
                            {
                                "action": transition.action,
                                "locator": transition.locate,
                                "frame_id": frame.id,
                            },
                            run_id,
                        )
                        state_id = transition.next_state
                        entered_state = None
                        break
        except BaseException as exc:
            message = (
                f"task timed out in state {state_id}"
                if isinstance(exc, TimeoutError)
                else str(exc)
            )
            self.events.emit(
                "bridge.run.failed",
                "runner",
                {"task_id": task.id, "state": state_id, "error": message},
                run_id,
            )
            if isinstance(exc, TimeoutError):
                raise TimeoutError(message) from exc
            raise
