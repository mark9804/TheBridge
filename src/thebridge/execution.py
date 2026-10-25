from __future__ import annotations

import asyncio
from collections.abc import Sequence
from contextlib import ExitStack, suppress
from pathlib import Path

from PIL import Image
from pydantic import TypeAdapter
from thebridge_core.artifacts import ArtifactStore
from thebridge_core.contracts import DeviceService, Frame, Point
from thebridge_core.dsl import TaskCatalog, load_task
from thebridge_core.events import Event, EventBus
from thebridge_core.plugins import PluginHost
from thebridge_core.runner import RunResult, StateRunner

from thebridge.builtin.android_adb.plugin import AdbDevice

DEFAULT_PLUGINS = ("builtin.android-adb", "builtin.macos-vision", "builtin.text-locator")


class RecordingDevice:
    def __init__(self, device: DeviceService, directory: Path, events: EventBus) -> None:
        self.device = device
        self.directory = directory
        self.events = events

    async def screenshot(self) -> Frame:
        frame = await self.device.screenshot()
        path = self.directory / f"{frame.id:06d}.png"
        Image.fromarray(frame.image[:, :, ::-1]).save(path)
        self.events.emit(
            "bridge.frame.captured",
            "trace",
            {"frame_id": frame.id, "path": str(path), "width": frame.width, "height": frame.height},
        )
        return frame

    async def tap(self, point: Point) -> None:
        await self.device.tap(point)

    async def swipe(self, start: Point, end: Point, duration_ms: int = 600) -> None:
        await self.device.swipe(start, end, duration_ms)

    async def back(self) -> None:
        await self.device.back()


async def run_task(
    path: Path,
    *,
    serial: str | None = None,
    config_path: Path | None = None,
    timeout_seconds: float = 180,
    trace_dir: Path | None = None,
    plugins: Sequence[str] = DEFAULT_PLUGINS,
    restart_app: str | None = None,
) -> RunResult:
    if timeout_seconds <= 0:
        raise ValueError("timeout must be positive")
    task = load_task(path)
    config_type = TypeAdapter(dict[str, dict[str, object]])
    configs = config_type.validate_python(task.parameters.get("plugins", {}))
    if config_path is not None:
        overrides = config_type.validate_json(config_path.read_text("utf-8"))
        for plugin_id, values in overrides.items():
            configs[plugin_id] = configs.get(plugin_id, {}) | values
    configs.setdefault("builtin.text-locator", {}).setdefault(
        "rules", task.parameters.get("locators", {})
    )
    if serial is not None:
        configs.setdefault("builtin.android-adb", {})["serial"] = serial

    events = EventBus()
    artifacts = ArtifactStore()
    host = PluginHost(TaskCatalog(), artifacts, events)
    host.discover(configs)

    with ExitStack() as stack:
        event_log = None
        if trace_dir is not None:
            trace_dir.mkdir(parents=True, exist_ok=True)
            event_log = stack.enter_context(
                (trace_dir / "events.jsonl").open("x", encoding="utf-8")
            )

        def write_event(event: Event) -> None:
            line = event.model_dump_json()
            print(line, flush=True)
            if event_log is not None:
                event_log.write(line + "\n")
                event_log.flush()

        async with events.subscribe() as queue:

            async def report_events() -> None:
                while True:
                    write_event(await queue.get())

            reporter = asyncio.create_task(report_events())
            try:
                await host.start(set(plugins))
                missing_services = set(task.requires) - host.services.keys()
                if missing_services:
                    raise RuntimeError(
                        f"missing task services: {', '.join(sorted(missing_services))}"
                    )
                missing_artifacts = artifacts.missing(task.artifacts)
                if missing_artifacts:
                    raise RuntimeError(f"missing task artifacts: {', '.join(missing_artifacts)}")
                device = host.services["android.device@1"]
                if restart_app is not None:
                    if not isinstance(device, AdbDevice):
                        raise RuntimeError("--restart-app requires the builtin Android ADB device")
                    await device.restart_app(restart_app)
                if trace_dir is not None:
                    device = RecordingDevice(device, trace_dir, events)
                return await StateRunner(events).run(
                    task, device, host.services["vision.locator@1"], timeout_seconds
                )
            finally:
                try:
                    await host.stop()
                finally:
                    reporter.cancel()
                    with suppress(asyncio.CancelledError):
                        await reporter
                    while not queue.empty():
                        write_event(queue.get_nowait())
