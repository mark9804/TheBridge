from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import uvicorn
from PIL import Image
from pydantic import BaseModel
from thebridge_core.artifacts import ArtifactStore
from thebridge_core.contracts import Frame, Match, Point, Rect
from thebridge_core.dsl import TaskCatalog, load_task, parse_task
from thebridge_core.events import EventBus
from thebridge_core.plugins import PluginContext, PluginHost, PluginSpec
from thebridge_core.runner import StateRunner

from thebridge.execution import DEFAULT_PLUGINS, RecordingDevice, run_task


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="thebridge")
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="启动 API 和已构建的 Web UI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    validate = commands.add_parser("validate", help="校验任务 DSL")
    validate.add_argument("path", type=Path)

    run = commands.add_parser("run", help="通过 ADB 和视觉插件执行任务 DSL")
    run.add_argument("path", type=Path)
    run.add_argument("--serial")
    run.add_argument("--config", type=Path, help="插件 ID 到配置的 JSON 文件")
    run.add_argument("--timeout", type=float, default=180)
    run.add_argument("--trace-dir", type=Path, help="保存原始截图与事件日志")
    run.add_argument("--plugins", nargs="+", default=DEFAULT_PLUGINS, help="启用的插件 ID 列表")

    commands.add_parser("check", help="运行最小框架自检")
    return parser


async def run_check() -> None:
    events = EventBus()
    tasks = TaskCatalog()
    host = PluginHost(tasks, ArtifactStore(), events)
    host.discover()
    await host.start({"builtin.azurlane-cn"})
    assert tasks.get("azurlane-cn.commission.collect-and-dispatch").stage == "draft"

    task = parse_task(
        {
            "version": 1,
            "id": "self-check",
            "title": "self-check",
            "entry": "start",
            "states": {
                "start": {
                    "expect": "self.start",
                    "transitions": [
                        {"locate": "self.button", "action": "tap_match", "next": "done"}
                    ],
                },
                "done": {"expect": "self.done", "terminal": True},
            },
        }
    )

    class Device:
        def __init__(self) -> None:
            self.frame_id = 0
            self.taps: list[Point] = []
            self.backs = 0

        async def screenshot(self) -> Frame:
            self.frame_id += 1
            pixels = np.zeros((8, 12, 3), dtype=np.uint8)
            pixels[0, 0] = (11, 22, 33)
            return Frame(self.frame_id, pixels)

        async def tap(self, point: Point) -> None:
            self.taps.append(point)

        async def back(self) -> None:
            self.backs += 1

    class Locator:
        async def locate(self, frame: Frame, locator_id: str) -> Match | None:
            visible = {
                1: {"self.start", "self.button"},
                2: {"self.done"},
            }
            if locator_id not in visible.get(frame.id, set()):
                return None
            return Match(frame.id, Rect(0, 0, 4, 4), 1.0)

    device = Device()
    with TemporaryDirectory(prefix="thebridge-check-") as directory:
        recording = RecordingDevice(device, Path(directory), events)
        result = await StateRunner(events).run(task, recording, Locator(), timeout_seconds=1)
        with Image.open(Path(directory) / "000001.png") as image:
            assert image.size == (12, 8) and image.getpixel((0, 0)) == (33, 22, 11)
        assert (Path(directory) / "000002.png").is_file()
        await recording.back()
        assert device.backs == 1
    assert result.final_state == "done" and device.taps == [Point(2, 2)]
    entered = [event for event in events.snapshot() if event.kind == "bridge.state.entered"]
    assert [event.payload["state"] for event in entered] == ["start", "done"]

    back_task = task.model_dump(by_alias=True)
    back_task["states"]["start"]["transitions"][0]["action"] = "back"
    back_device = Device()
    await StateRunner(EventBus()).run(
        parse_task(back_task), back_device, Locator(), timeout_seconds=1
    )
    assert back_device.backs == 1 and back_device.taps == []

    class HangingDevice(Device):
        async def screenshot(self) -> Frame:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    try:
        await StateRunner(events).run(task, HangingDevice(), Locator(), timeout_seconds=0.01)
    except TimeoutError as exc:
        assert str(exc) == "task timed out in state start"
    else:
        raise AssertionError("runner timeout did not interrupt screenshot")
    await host.stop()

    class CheckConfig(BaseModel):
        pass

    class FailingPlugin:
        spec = PluginSpec(id="self-check.failure", version="1", provides=("self.service@1",))
        config_model = CheckConfig

        def __init__(self) -> None:
            self.deactivated = False

        async def activate(self, context: PluginContext, config: BaseModel) -> None:
            context.provide("self.service@1", object())
            raise RuntimeError("activation failed")

        async def deactivate(self) -> None:
            self.deactivated = True

    class DisabledPlugin(FailingPlugin):
        spec = PluginSpec(id="self-check.disabled", version="1", provides=("self.service@1",))

    class ConsumerPlugin(FailingPlugin):
        spec = PluginSpec(id="self-check.consumer", version="1", requires=("self.service@1",))

        async def activate(self, context: PluginContext, config: BaseModel) -> None:
            context.require("self.service@1")

    failing = FailingPlugin()
    failing_host = PluginHost(TaskCatalog(), ArtifactStore(), EventBus())
    failing_host.register(failing)
    failing_host.register(DisabledPlugin())
    try:
        await failing_host.start({failing.spec.id})
    except RuntimeError as exc:
        assert str(exc) == "activation failed"
    else:
        raise AssertionError("failing plugin unexpectedly activated")
    assert failing.deactivated and "self.service@1" not in failing_host.services

    ambiguous_host = PluginHost(TaskCatalog(), ArtifactStore(), EventBus())
    ambiguous_host.register(FailingPlugin())
    ambiguous_host.register(DisabledPlugin())
    ambiguous_host.register(ConsumerPlugin())
    try:
        await ambiguous_host.start({"self-check.consumer"})
    except ValueError as exc:
        assert "ambiguous service provider" in str(exc)
    else:
        raise AssertionError("ambiguous provider unexpectedly selected")
    print("TheBridge check passed")


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "serve":
        uvicorn.run("thebridge.app:app", host=args.host, port=args.port, reload=False)
    elif args.command == "validate":
        task = load_task(args.path)
        print(f"valid task: {task.id} ({len(task.states)} states)")
    elif args.command == "run":
        try:
            result = asyncio.run(
                run_task(
                    args.path,
                    serial=args.serial,
                    config_path=args.config,
                    timeout_seconds=args.timeout,
                    trace_dir=args.trace_dir,
                    plugins=args.plugins,
                )
            )
        except Exception as exc:
            print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
            raise SystemExit(1) from None
        print(json.dumps({"status": "finished", **asdict(result)}, ensure_ascii=False))
    else:
        asyncio.run(run_check())


if __name__ == "__main__":
    main()
