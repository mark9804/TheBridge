from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from thebridge_core.contracts import Rect

CommissionCategory = Literal["urgent", "daily"]
RewardKind = Literal["gem", "cognitive_chip", "oil", "cube"]
PriorityRule = Literal["night_long", "gem", "cognitive_chip", "oil", "cube", "shortest"]
CN_TIMEZONE = timezone(timedelta(hours=8))


@dataclass(frozen=True, slots=True)
class CommissionCandidate:
    box: Rect
    category: CommissionCategory
    duration_minutes: int | None = None
    rewards: frozenset[RewardKind] = frozenset()


def select_commission(
    candidates: Sequence[CommissionCandidate],
    priority: Sequence[PriorityRule],
    *,
    now: datetime | None = None,
) -> CommissionCandidate | None:
    if not candidates:
        return None

    current = now or datetime.now(CN_TIMEZONE)
    if current.tzinfo is None:
        raise ValueError("now must include timezone information")
    cn_hour = current.astimezone(CN_TIMEZONE).hour
    night = cn_hour >= 21 or cn_hour < 2

    def key(item: tuple[int, CommissionCandidate]) -> tuple[int, ...]:
        screen_order, candidate = item
        duration = candidate.duration_minutes if candidate.duration_minutes is not None else 10**9
        criteria: list[int] = []
        for rule in priority:
            if rule == "night_long":
                is_night_long = (
                    night
                    and candidate.category == "urgent"
                    and candidate.duration_minutes is not None
                    and candidate.duration_minutes >= 360
                )
                criteria.append(0 if is_night_long else 1)
            elif rule == "shortest":
                criteria.append(duration)
            else:
                criteria.append(0 if rule in candidate.rewards else 1)
        category_rank = 0 if candidate.category == "urgent" else 1
        return category_rank, *criteria, screen_order

    return min(enumerate(candidates), key=key)[1]


if __name__ == "__main__":
    box = Rect(0, 0, 10, 10)
    choices = (
        CommissionCandidate(box, "daily", 30, frozenset({"gem"})),
        CommissionCandidate(box, "urgent", 480, frozenset({"oil"})),
        CommissionCandidate(box, "urgent", 360, frozenset({"cognitive_chip"})),
        CommissionCandidate(box, "urgent", 120, frozenset({"cube"})),
    )
    priority: tuple[PriorityRule, ...] = (
        "night_long",
        "cognitive_chip",
        "oil",
    )
    selected = select_commission(
        choices,
        priority,
        now=datetime(2026, 8, 16, 22, tzinfo=CN_TIMEZONE),
    )
    assert selected == choices[2]
    selected = select_commission(
        choices,
        ("cube", "shortest"),
        now=datetime(2026, 8, 16, 12, tzinfo=CN_TIMEZONE),
    )
    assert selected == choices[3]
    assert (
        select_commission((), priority, now=datetime(2026, 8, 16, 22, tzinfo=CN_TIMEZONE))
        is None
    )
