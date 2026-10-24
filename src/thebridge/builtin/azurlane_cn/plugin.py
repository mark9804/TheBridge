from __future__ import annotations

from functools import partial
from importlib.resources import files

import yaml
from pydantic import BaseModel, ConfigDict
from thebridge_core.dsl import parse_task
from thebridge_core.plugins import PluginContext, PluginSpec

from .commission import PriorityRule, select_commission


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commission_priority: tuple[PriorityRule, ...] | None = None


class TaskParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commission_priority: tuple[PriorityRule, ...]


class AzurLaneCnPlugin:
    spec = PluginSpec(
        id="builtin.azurlane-cn",
        version="0.1.0",
        api=1,
        provides=("azurlane-cn.commission-selector@1",),
    )
    config_model = Config

    async def activate(self, context: PluginContext, config: Config) -> None:
        task_file = files(__package__).joinpath("tasks/commission.yaml")
        task = parse_task(yaml.safe_load(task_file.read_text(encoding="utf-8")))
        parameters = TaskParameters.model_validate(task.parameters)
        priority = (
            config.commission_priority
            if config.commission_priority is not None
            else parameters.commission_priority
        )
        context.provide(
            "azurlane-cn.commission-selector@1",
            partial(select_commission, priority=priority),
        )
        context.register_task(task)
        task_directory = files(__package__).joinpath("tasks")
        for task_file in sorted(task_directory.iterdir(), key=lambda item: item.name):
            if task_file.name.endswith(".yaml") and task_file.name != "commission.yaml":
                context.register_task(
                    parse_task(yaml.safe_load(task_file.read_text(encoding="utf-8")))
                )

    async def deactivate(self) -> None:
        return None


def create_plugin() -> AzurLaneCnPlugin:
    return AzurLaneCnPlugin()
