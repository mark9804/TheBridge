from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Opponent:
    index: int
    main_power: int
    vanguard_power: int

    def __post_init__(self) -> None:
        if self.index not in range(4):
            raise ValueError("opponent index must be between 0 and 3")
        if any(
            not isinstance(power, int) or power < 0
            for power in (self.main_power, self.vanguard_power)
        ):
            raise ValueError("both fleet powers must be known non-negative integers")

    @property
    def total_power(self) -> int:
        return self.main_power + self.vanguard_power


def select_opponent(candidates: Sequence[Opponent], max_power: int) -> Opponent | None:
    if max_power < 0:
        raise ValueError("max_power must be non-negative")
    if len(candidates) != 4 or {candidate.index for candidate in candidates} != set(range(4)):
        raise ValueError("selection requires all four distinct opponents")
    return min(
        (candidate for candidate in candidates if candidate.total_power <= max_power),
        key=lambda candidate: (candidate.total_power, candidate.index),
        default=None,
    )


if __name__ == "__main__":
    choices = (
        Opponent(0, 15000, 12000),
        Opponent(1, 14000, 12000),
        Opponent(2, 13000, 13000),
        Opponent(3, 16000, 12000),
    )
    assert select_opponent(choices, 26000) == choices[1]
    assert select_opponent(tuple(reversed(choices)), 26000) == choices[1]
    assert select_opponent(choices, 25999) is None
    weakest = Opponent(3, 1, 0)
    assert select_opponent((*choices[:3], weakest), 26000) == weakest
    for incomplete in (choices[:3], (*choices[:3], choices[0])):
        try:
            select_opponent(incomplete, 26000)
        except ValueError:
            pass
        else:
            raise AssertionError("incomplete opponent observations must be rejected")
    print("Exercise policy check passed")
