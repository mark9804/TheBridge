from __future__ import annotations

from dataclasses import dataclass
from graphlib import TopologicalSorter
from importlib.metadata import entry_points
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from thebridge_core.artifacts import ArtifactRequirement, ArtifactStore
from thebridge_core.dsl import TaskCatalog, TaskSpec
from thebridge_core.events import EventBus


class PluginSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]+$")
    version: str
    api: Literal[1] = 1
    provides: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    artifacts: tuple[ArtifactRequirement, ...] = ()


class Plugin(Protocol):
    spec: PluginSpec
    config_model: type[BaseModel]

    async def activate(self, context: PluginContext, config: BaseModel) -> None: ...

    async def deactivate(self) -> None: ...


class PluginContext:
    def __init__(
        self,
        spec: PluginSpec,
        services: dict[str, Any],
        tasks: TaskCatalog,
        artifacts: ArtifactStore,
        events: EventBus,
    ) -> None:
        self.spec = spec
        self._services = services
        self.tasks = tasks
        self.artifacts = artifacts
        self.events = events
        self._provided: list[str] = []
        self._task_ids: list[str] = []

    def provide(self, name: str, service: Any) -> None:
        if name not in self.spec.provides:
            raise ValueError(f"plugin {self.spec.id} did not declare service {name}")
        if name in self._services:
            raise ValueError(f"service already exists: {name}")
        self._services[name] = service
        self._provided.append(name)

    def require(self, name: str) -> Any:
        if name not in self.spec.requires:
            raise ValueError(f"plugin {self.spec.id} did not declare dependency {name}")
        return self._services[name]

    def register_task(self, task: TaskSpec) -> None:
        self.tasks.add(task)
        self._task_ids.append(task.id)

    def close(self) -> None:
        for task_id in reversed(self._task_ids):
            self.tasks.remove(task_id)
        for name in reversed(self._provided):
            self._services.pop(name, None)


@dataclass(slots=True)
class RegisteredPlugin:
    plugin: Plugin
    config: BaseModel
    active: bool = False


class PluginHost:
    def __init__(
        self,
        tasks: TaskCatalog,
        artifacts: ArtifactStore,
        events: EventBus,
        services: dict[str, Any] | None = None,
    ) -> None:
        self.tasks = tasks
        self.artifacts = artifacts
        self.events = events
        self.services = services or {}
        self.plugins: dict[str, RegisteredPlugin] = {}
        self._contexts: dict[str, PluginContext] = {}
        self._activation_order: list[str] = []

    def register(self, plugin: Plugin, config: object | None = None) -> None:
        if plugin.spec.id in self.plugins:
            raise ValueError(f"duplicate plugin: {plugin.spec.id}")
        parsed_config = plugin.config_model.model_validate(config or {})
        self.plugins[plugin.spec.id] = RegisteredPlugin(plugin=plugin, config=parsed_config)

    def discover(self, configs: dict[str, object] | None = None) -> None:
        plugin_configs = configs or {}
        for entry_point in entry_points(group="thebridge.plugins"):
            factory = entry_point.load()
            plugin = factory()
            self.register(plugin, plugin_configs.get(plugin.spec.id))

    async def start(self, enabled: set[str]) -> None:
        unknown = enabled - self.plugins.keys()
        if unknown:
            raise ValueError(f"unknown plugins: {', '.join(sorted(unknown))}")

        providers: dict[str, set[str]] = {}
        for plugin_id, registered in self.plugins.items():
            for service in registered.plugin.spec.provides:
                providers.setdefault(service, set()).add(plugin_id)

        selected = set(enabled)
        chosen_providers: dict[tuple[str, str], str] = {}
        pending = list(enabled)
        while pending:
            plugin_id = pending.pop()
            for service in self.plugins[plugin_id].plugin.spec.requires:
                if service in self.services:
                    continue
                candidates = providers.get(service, set())
                explicit_candidates = candidates & enabled
                if len(explicit_candidates) == 1:
                    provider = next(iter(explicit_candidates))
                elif len(explicit_candidates) > 1:
                    raise ValueError(f"ambiguous service provider: {service}")
                elif len(candidates) == 1:
                    provider = next(iter(candidates))
                elif not candidates:
                    raise ValueError(f"missing service {service} for plugin {plugin_id}")
                else:
                    raise ValueError(
                        f"ambiguous service provider for {plugin_id}: {service}; "
                        "enable exactly one provider"
                    )
                chosen_providers[plugin_id, service] = provider
                if provider not in selected:
                    selected.add(provider)
                    pending.append(provider)

        for service, candidates in providers.items():
            active_candidates = candidates & selected
            if len(active_candidates) > 1 or (service in self.services and active_candidates):
                raise ValueError(f"duplicate active service provider: {service}")

        graph = {
            plugin_id: {
                chosen_providers[plugin_id, service]
                for service in self.plugins[plugin_id].plugin.spec.requires
                if service not in self.services
            }
            for plugin_id in selected
        }

        try:
            for plugin_id in TopologicalSorter(graph).static_order():
                registered = self.plugins[plugin_id]
                missing = self.artifacts.missing(registered.plugin.spec.artifacts)
                if missing:
                    raise RuntimeError(
                        f"plugin {plugin_id} is missing artifacts: {', '.join(missing)}"
                    )
                context = PluginContext(
                    registered.plugin.spec,
                    self.services,
                    self.tasks,
                    self.artifacts,
                    self.events,
                )
                try:
                    await registered.plugin.activate(context, registered.config)
                    missing_provides = set(registered.plugin.spec.provides) - self.services.keys()
                    if missing_provides:
                        raise RuntimeError(
                            f"plugin {plugin_id} did not provide: "
                            f"{', '.join(sorted(missing_provides))}"
                        )
                except BaseException:
                    try:
                        await registered.plugin.deactivate()
                    except BaseException as cleanup_error:
                        self.events.emit(
                            "bridge.plugin.cleanup-failed",
                            plugin_id,
                            {"error": str(cleanup_error)},
                        )
                    finally:
                        context.close()
                    raise
                registered.active = True
                self._contexts[plugin_id] = context
                self._activation_order.append(plugin_id)
                self.events.emit("bridge.plugin.activated", plugin_id)
        except BaseException:
            try:
                await self.stop()
            except BaseException as cleanup_error:
                self.events.emit(
                    "bridge.plugin.cleanup-failed",
                    "plugin-host",
                    {"error": str(cleanup_error)},
                )
            raise

    async def stop(self) -> None:
        first_error: BaseException | None = None
        for plugin_id in reversed(self._activation_order):
            registered = self.plugins[plugin_id]
            try:
                await registered.plugin.deactivate()
            except BaseException as exc:
                first_error = first_error or exc
            finally:
                self._contexts[plugin_id].close()
                registered.active = False
                self.events.emit("bridge.plugin.deactivated", plugin_id)
        self._activation_order.clear()
        self._contexts.clear()
        if first_error is not None:
            raise first_error
