from __future__ import annotations

from importlib.resources import files

import yaml
from pydantic import BaseModel, ConfigDict
from thebridge_core.dsl import parse_task
from thebridge_core.plugins import PluginContext, PluginSpec


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AzurLaneCnPlugin:
    spec = PluginSpec(id="builtin.azurlane-cn", version="0.1.0", api=1)
    config_model = Config

    async def activate(self, context: PluginContext, config: BaseModel) -> None:
        task_file = files(__package__).joinpath("tasks/commission.yaml")
        context.register_task(parse_task(yaml.safe_load(task_file.read_text(encoding="utf-8"))))

    async def deactivate(self) -> None:
        return None


def create_plugin() -> AzurLaneCnPlugin:
    return AzurLaneCnPlugin()
