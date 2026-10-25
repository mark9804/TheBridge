from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image
from thebridge_core.contracts import Frame, Rect

STORY_CODE = re.compile(r"(?:EP(?:S|\d+)|EX)-\d+", re.I)


@dataclass(frozen=True, slots=True)
class StoryNode:
    label: str
    box: Rect
    icon_box: Rect
    completed: bool
    locked: bool
    gold_fraction: float


def parse_story_progress(texts: Sequence[tuple[Any, str]]) -> tuple[int, int] | None:
    counts = []
    for _, text in texts:
        match = re.fullmatch(r"已完成阶段[:：](\d+)/(\d+)(?:已领取)?", text)
        if match:
            counts.append(tuple(map(int, match.groups())))
    if len(counts) != 1:
        return None
    completed, total = counts[0]
    return (completed, total) if 0 <= completed <= total and total > 0 else None


async def read_story_progress(
    frame: Frame, texts: Sequence[tuple[Any, str]], ocr: Any
) -> tuple[int, int] | None:
    anchors = [item.box for item, text in texts if "已完成阶段" in text]
    if len(anchors) != 1:
        return None
    box = anchors[0]
    margin = round((box.bottom - box.top) * 0.4)
    left, right = max(0, box.left - margin), min(frame.width, box.right + margin)
    top, bottom = max(0, box.top - margin), min(frame.height, box.bottom + margin)
    crop = Image.fromarray(frame.image[top:bottom, left:right, ::-1])
    enlarged = crop.resize((crop.width * 2, crop.height * 2), Image.Resampling.LANCZOS)
    local = Frame(frame.id, np.ascontiguousarray(np.asarray(enlarged)[:, :, ::-1]))
    # Full-frame OCR confuses the narrow yellow 7 with 1 on this counter.
    text = "".join(re.sub(r"\s+", "", item.text) for item in await ocr.read(local))
    counts = re.findall(r"(\d+)/(\d+)", text)
    if len(counts) != 1:
        return None
    completed, total = map(int, counts[0])
    return (completed, total) if 0 <= completed <= total and total > 0 else None


def find_story_nodes(frame: Frame, texts: Sequence[tuple[Any, str]]) -> tuple[StoryNode, ...]:
    if parse_story_progress(texts) is None:
        return ()
    anchors = [box.box for box, text in texts if re.search(r"STOR|TORY", text, re.I)]
    nodes = []
    for item, label in texts:
        box = item.box
        height = box.bottom - box.top
        if not 0.35 * frame.height <= box.center.y <= 0.65 * frame.height:
            continue
        if len(re.findall(r"[\u4e00-\u9fff]", label)) < 2 or box.right - box.left < 2 * height:
            continue
        nearby = [
            anchor
            for anchor in anchors
            if abs(anchor.left - box.left) <= height
            and 0 < box.center.y - anchor.center.y <= 2.5 * height
        ]
        if len(nearby) == 1:
            header_left = nearby[0].left
        elif not nearby and STORY_CODE.match(label):
            # Some backgrounds make STORY unreadable while the full episode ID survives.
            header_left = box.left
        else:
            continue
        # The fixed STORY header stays in place while long node titles scroll.
        left = round(header_left - 4 * height)
        right = round(header_left - 0.3 * height)
        top = round(box.center.y - 1.5 * height)
        bottom = round(box.center.y + 1.5 * height)
        if left < 0 or top < 0 or right > frame.width or bottom > frame.height:
            continue
        icon = Rect(left, top, right, bottom)
        pixels = frame.image[top:bottom, left:right].astype(np.int16)
        blue, green, red = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
        gold = (red > 150) & (green > 110) & (blue < 150)
        gold &= (red - blue > 50) & (green - blue > 35)
        fraction = float(gold.mean())
        completed = fraction >= 0.08
        white = (pixels.min(axis=2) > 210) & (np.ptp(pixels, axis=2) < 45)
        if not completed and float(white.mean()) < 0.025:
            continue
        locked = re.search(r"完成[A-Z]", label, re.I) is not None
        nodes.append(StoryNode(label, box, icon, completed, locked, fraction))
    return tuple(sorted(nodes, key=lambda node: node.box.left))


def check_story_nodes() -> None:
    from thebridge.builtin.macos_vision.plugin import TextBox

    def text(value: str, box: Rect) -> tuple[TextBox, str]:
        return TextBox(value, box, 1.0), value

    for scale in (1, 2):

        def rect(left: int, top: int, right: int, bottom: int, factor: int = scale) -> Rect:
            return Rect(left * factor, top * factor, right * factor, bottom * factor)

        pixels = np.zeros((600 * scale, 1000 * scale, 3), dtype=np.uint8)
        texts = [text("已完成阶段：1/26", rect(800, 560, 950, 580))]
        for offset, label, color in (
            (0, "EP1-1已读剧情", (50, 210, 245)),
            (300, "-2滚动标题", (245, 245, 245)),
            (600, "完成EP1-2", (245, 245, 245)),
        ):
            texts.extend(
                [
                    text("STORY", rect(120 + offset, 260, 180 + offset, 275)),
                    text(label, rect(125 + offset, 290, 270 + offset, 310)),
                ]
            )
            pixels[280 * scale : 320 * scale, (65 + offset) * scale : (100 + offset) * scale] = (
                color
            )
        frame = Frame(1, pixels)
        nodes = find_story_nodes(frame, texts)
        assert parse_story_progress(texts) == (1, 26)
        assert [(node.completed, node.locked) for node in nodes] == [
            (True, False),
            (False, False),
            (False, True),
        ]
        assert [node.label for node in nodes if not node.completed and not node.locked] == [
            "-2滚动标题"
        ]
        for locked_label in ("＞完成EP1-2", "完成EX-1"):
            marked_lock = texts[:-1] + [text(locked_label, texts[-1][0].box)]
            assert find_story_nodes(frame, marked_lock)[-1].locked
        missing_header = [
            texts[0],
            text("人とOLS", texts[3][0].box),
            text("EP4-2吃什么？", texts[4][0].box),
        ]
        available = find_story_nodes(frame, missing_header)
        assert len(available) == 1 and not available[0].completed and not available[0].locked
        missing_header[-1] = text("无编号背景文字", texts[4][0].box)
        assert find_story_nodes(frame, missing_header) == ()
        clipped = [
            texts[0],
            text("STORY", rect(20, 260, 80, 275)),
            text("边缘标题", rect(25, 290, 170, 310)),
        ]
        assert find_story_nodes(frame, clipped) == ()
        assert find_story_nodes(Frame(2, np.zeros_like(pixels)), texts) == ()
        assert parse_story_progress(texts + [texts[0]]) is None
        assert parse_story_progress([text("已完成阶段：26/26已领取", rect(0, 0, 200, 20))]) == (
            26,
            26,
        )
        assert parse_story_progress([text("已完成阶段：27/26", rect(0, 0, 20, 20))]) is None
    print("Story node checks passed")


async def check_story_progress_reader() -> None:
    from thebridge.builtin.macos_vision.plugin import TextBox

    pixels = np.full((100, 300, 3), (20, 90, 180), dtype=np.uint8)
    frame = Frame(7, pixels)
    anchor = TextBox("已完成阶段：1/26", Rect(100, 60, 270, 80), 1.0)
    texts = ((anchor, anchor.text),)

    class Ocr:
        calls = 0

        async def read(self, local: Frame) -> tuple[TextBox, ...]:
            self.calls += 1
            assert local is not frame and local.id == frame.id
            assert (local.width, local.height) == (372, 72)
            assert np.array_equal(local.image[30, 30], frame.image[60, 100])
            return (TextBox("7/26", Rect(1, 1, 30, 20), 1.0),)

    ocr = Ocr()
    assert await read_story_progress(frame, texts, ocr) == (7, 26)
    assert await read_story_progress(frame, (), ocr) is None
    assert await read_story_progress(frame, texts * 2, ocr) is None
    assert ocr.calls == 1
    print("Story progress crop checks passed")
