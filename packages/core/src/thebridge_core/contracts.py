from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class Point:
    x: int
    y: int


@dataclass(frozen=True, slots=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    def __post_init__(self) -> None:
        if self.left < 0 or self.top < 0:
            raise ValueError("Rect coordinates must be non-negative")
        if self.right <= self.left or self.bottom <= self.top:
            raise ValueError("Rect must have positive width and height")

    @property
    def center(self) -> Point:
        return Point((self.left + self.right) // 2, (self.top + self.bottom) // 2)

    def fits(self, frame: Frame) -> bool:
        return self.right <= frame.width and self.bottom <= frame.height


@dataclass(frozen=True, slots=True)
class Frame:
    id: int
    image: NDArray[np.uint8]

    def __post_init__(self) -> None:
        if self.image.dtype != np.uint8 or self.image.ndim != 3 or self.image.shape[2] != 3:
            raise ValueError("Frame image must be an HxWx3 uint8 BGR array")

    @property
    def width(self) -> int:
        return int(self.image.shape[1])

    @property
    def height(self) -> int:
        return int(self.image.shape[0])


@dataclass(frozen=True, slots=True)
class Match:
    frame_id: int
    box: Rect
    score: float | None = None


class DeviceService(Protocol):
    async def screenshot(self) -> Frame: ...

    async def tap(self, point: Point) -> None: ...

    async def back(self) -> None: ...


class LocatorService(Protocol):
    async def locate(self, frame: Frame, locator_id: str) -> Match | None: ...
