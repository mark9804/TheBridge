from __future__ import annotations

import asyncio
import shutil
from io import BytesIO

import numpy as np
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field
from thebridge_core.contracts import Frame, Point
from thebridge_core.plugins import PluginContext, PluginSpec


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adb_path: str = "adb"
    serial: str | None = None
    timeout_seconds: float = Field(default=10.0, gt=0)


class AdbError(RuntimeError):
    pass


class AdbDevice:
    def __init__(self, adb_path: str, serial: str | None, timeout_seconds: float) -> None:
        self.adb_path = adb_path
        self.serial = serial
        self.timeout_seconds = timeout_seconds
        self.frame_id = 0

    def _command(self, *args: str) -> tuple[str, ...]:
        serial = ("-s", self.serial) if self.serial else ()
        return (self.adb_path, *serial, *args)

    async def _run(self, *args: str) -> bytes:
        command = self._command(*args)
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise AdbError(f"failed to start adb: {exc}") from exc

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self.timeout_seconds
            )
        except TimeoutError as exc:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise AdbError(f"adb command timed out: {' '.join(command)}") from exc
        except asyncio.CancelledError:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise

        if process.returncode:
            detail = stderr.decode(errors="replace").strip() or "unknown adb error"
            raise AdbError(f"adb command failed ({process.returncode}): {detail}")
        return stdout

    async def screenshot(self) -> Frame:
        data = await self._run("exec-out", "screencap", "-p")
        try:
            with Image.open(BytesIO(data)) as image:
                rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
        except (OSError, UnidentifiedImageError) as exc:
            raise AdbError("adb returned an invalid screenshot") from exc

        self.frame_id += 1
        return Frame(self.frame_id, np.ascontiguousarray(rgb[:, :, ::-1]))

    async def tap(self, point: Point) -> None:
        await self._run("shell", "input", "tap", str(point.x), str(point.y))


class AndroidAdbPlugin:
    spec = PluginSpec(
        id="builtin.android-adb",
        version="0.1.0",
        api=1,
        provides=("android.device@1",),
    )
    config_model = Config

    def __init__(self) -> None:
        self.device: AdbDevice | None = None

    async def activate(self, context: PluginContext, config: BaseModel) -> None:
        parsed = Config.model_validate(config)
        adb_path = shutil.which(parsed.adb_path)
        if adb_path is None:
            raise AdbError(f"adb executable not found: {parsed.adb_path}")

        device = AdbDevice(adb_path, parsed.serial, parsed.timeout_seconds)
        state = (await device._run("get-state")).decode(errors="replace").strip()
        if state != "device":
            raise AdbError(f"adb device is not ready: {state or 'empty response'}")
        self.device = device
        context.provide("android.device@1", device)

    async def deactivate(self) -> None:
        self.device = None


def create_plugin() -> AndroidAdbPlugin:
    return AndroidAdbPlugin()
