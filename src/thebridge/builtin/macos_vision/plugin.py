from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from io import BytesIO
from math import ceil, floor

from PIL import Image
from pydantic import BaseModel, ConfigDict
from thebridge_core.contracts import Frame, Rect
from thebridge_core.plugins import PluginContext, PluginSpec


@dataclass(frozen=True, slots=True)
class TextBox:
    text: str
    box: Rect
    confidence: float


class MacosVisionOcr:
    def __init__(self) -> None:
        if sys.platform != "darwin":
            raise RuntimeError("macOS Vision requires macOS")
        try:
            import objc
            import Vision
            from Foundation import NSData
        except ImportError as exc:
            raise RuntimeError("install macOS Vision with: uv sync --extra macos-vision") from exc

        self._vision = Vision
        self._data = NSData
        self._autorelease_pool = objc.autorelease_pool
        self._frame: Frame | None = None
        self._boxes: tuple[TextBox, ...] = ()

    async def read(self, frame: Frame) -> tuple[TextBox, ...]:
        if self._frame is frame:
            return self._boxes
        boxes = await asyncio.to_thread(self._read, frame)
        self._frame, self._boxes = frame, boxes
        return boxes

    def _read(self, frame: Frame) -> tuple[TextBox, ...]:
        with self._autorelease_pool():
            buffer = BytesIO()
            Image.fromarray(frame.image[:, :, ::-1]).save(buffer, format="PNG")
            payload = buffer.getvalue()
            data = self._data.dataWithBytes_length_(payload, len(payload))
            request = self._vision.VNRecognizeTextRequest.alloc().init()
            # Revision 3 misorients upright text beside the game's rotated border lettering.
            request.setRevision_(self._vision.VNRecognizeTextRequestRevision2)
            request.setRecognitionLanguages_(["zh-Hans", "en-US"])
            request.setRecognitionLevel_(self._vision.VNRequestTextRecognitionLevelAccurate)
            request.setUsesLanguageCorrection_(False)
            handler = self._vision.VNImageRequestHandler.alloc().initWithData_options_(data, None)
            succeeded, error = handler.performRequests_error_([request], None)
            if not succeeded:
                raise RuntimeError(f"macOS Vision text recognition failed: {error}")

            boxes: list[TextBox] = []
            for observation in request.results() or ():
                candidates = observation.topCandidates_(1)
                if not candidates:
                    continue
                candidate = candidates[0]
                bounds = observation.boundingBox()
                left = max(0, floor(bounds.origin.x * frame.width))
                right = min(frame.width, ceil((bounds.origin.x + bounds.size.width) * frame.width))
                # Vision's normalized origin is at the bottom left.
                top = max(0, floor((1 - bounds.origin.y - bounds.size.height) * frame.height))
                bottom = min(frame.height, ceil((1 - bounds.origin.y) * frame.height))
                if right > left and bottom > top:
                    boxes.append(
                        TextBox(
                            str(candidate.string()),
                            Rect(left, top, right, bottom),
                            float(candidate.confidence()),
                        )
                    )
            return tuple(boxes)


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MacosVisionPlugin:
    spec = PluginSpec(
        id="builtin.macos-vision",
        version="0.1.0",
        provides=("vision.text@1",),
    )
    config_model = Config

    def __init__(self) -> None:
        self.ocr: MacosVisionOcr | None = None

    async def activate(self, context: PluginContext, config: BaseModel) -> None:
        self.ocr = MacosVisionOcr()
        context.provide("vision.text@1", self.ocr)

    async def deactivate(self) -> None:
        self.ocr = None


def create_plugin() -> MacosVisionPlugin:
    return MacosVisionPlugin()


if __name__ == "__main__":
    import argparse

    import numpy as np

    parser = argparse.ArgumentParser(description="Check macOS Vision OCR against a screenshot")
    parser.add_argument("image")
    args = parser.parse_args()

    async def check() -> None:
        with Image.open(args.image) as image:
            pixels = np.asarray(image.convert("RGB"), dtype=np.uint8)
        frame = Frame(1, np.ascontiguousarray(pixels[:, :, ::-1]))
        ocr = MacosVisionOcr()
        boxes = await ocr.read(frame)
        assert boxes and all(item.box.fits(frame) for item in boxes)
        assert await ocr.read(frame) is boxes
        assert await ocr.read(Frame(1, np.zeros_like(frame.image))) == ()
        for item in boxes:
            print(f"{item.text}\t{item.box}\t{item.confidence:.3f}")

    asyncio.run(check())
