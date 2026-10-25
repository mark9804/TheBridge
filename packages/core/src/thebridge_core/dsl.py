from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from thebridge_core.artifacts import ArtifactRequirement


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class TransitionSpec(StrictModel):
    locate: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]+$")
    action: Literal["tap_match", "back", "observe", "swipe_left", "swipe_right"]
    next_state: str = Field(alias="next", pattern=r"^[a-z0-9][a-z0-9._-]+$")


class StateSpec(StrictModel):
    expect: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]+$")
    terminal: bool = False
    transitions: tuple[TransitionSpec, ...] = ()


class TaskSpec(StrictModel):
    version: Literal[1]
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]+$")
    title: str
    stage: Literal["draft", "stable"] = "draft"
    parameters: dict[str, object] = Field(default_factory=dict)
    requires: tuple[str, ...] = ()
    artifacts: tuple[ArtifactRequirement, ...] = ()
    entry: str
    states: dict[str, StateSpec]

    @model_validator(mode="after")
    def validate_graph(self) -> TaskSpec:
        if self.entry not in self.states:
            raise ValueError(f"entry state does not exist: {self.entry}")

        for state_id, state in self.states.items():
            if state.terminal and state.transitions:
                raise ValueError(f"terminal state has transitions: {state_id}")
            if not state.terminal and not state.transitions:
                raise ValueError(f"non-terminal state has no transitions: {state_id}")
            for transition in state.transitions:
                if transition.next_state not in self.states:
                    raise ValueError(
                        f"state {state_id} targets missing state {transition.next_state}"
                    )

        reachable = {self.entry}
        pending = [self.entry]
        while pending:
            state_id = pending.pop()
            for transition in self.states[state_id].transitions:
                if transition.next_state not in reachable:
                    reachable.add(transition.next_state)
                    pending.append(transition.next_state)
        unreachable = set(self.states) - reachable
        if unreachable:
            raise ValueError(f"unreachable states: {', '.join(sorted(unreachable))}")
        if not any(state.terminal for state in self.states.values()):
            raise ValueError("task has no terminal state")
        return self


def parse_task(data: object) -> TaskSpec:
    return TaskSpec.model_validate(data)


def load_task(path: Path) -> TaskSpec:
    with path.open(encoding="utf-8") as stream:
        return parse_task(yaml.safe_load(stream))


class TaskCatalog:
    def __init__(self) -> None:
        self._tasks: dict[str, TaskSpec] = {}

    def add(self, task: TaskSpec) -> None:
        if task.id in self._tasks:
            raise ValueError(f"duplicate task: {task.id}")
        self._tasks[task.id] = task

    def remove(self, task_id: str) -> None:
        self._tasks.pop(task_id, None)

    def get(self, task_id: str) -> TaskSpec:
        return self._tasks[task_id]

    def all(self) -> tuple[TaskSpec, ...]:
        return tuple(self._tasks.values())
