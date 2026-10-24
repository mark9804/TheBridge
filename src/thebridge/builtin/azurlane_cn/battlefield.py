from __future__ import annotations

from collections import deque
from collections.abc import Sequence, Set
from dataclasses import dataclass
from typing import Literal

type Cell = tuple[int, int]
type Mobility = Literal["bounded", "unrestricted", "unknown"]


@dataclass(frozen=True, slots=True)
class Enemy:
    cell: Cell
    boss: bool = False
    strength: int | None = None

    def __post_init__(self) -> None:
        if self.strength is not None and self.strength not in (1, 2, 3):
            raise ValueError("enemy strength must be 1, 2, 3, or unknown")


@dataclass(frozen=True, slots=True)
class Selection:
    target: Enemy | None = None
    path: tuple[Cell, ...] = ()
    stop_reason: str | None = None

    @property
    def reaches_target(self) -> bool:
        return self.target is not None and bool(self.path) and self.path[-1] == self.target.cell


def select_target(
    *,
    walkable_cells: Set[Cell],
    origin: Cell,
    blocked_cells: Set[Cell],
    enemies: Sequence[Enemy],
    guard_count: int | None,
    mobility: Mobility,
    allowed_cells: Set[Cell] | None = None,
    policy: Literal["clear_all", "boss_first"] = "clear_all",
) -> Selection:
    """Choose a target under the explicit clearing or boss-first policy.

    Clear-all requires an observed clear board before choosing a boss. Boss-first
    prefers an actionable boss, including a safe movement prefix, then guards;
    it does not require a known guard count.
    Cells describe traversable terrain, including occupied destinations. Unknown
    terrain is excluded. Bounded movement permits only the supplied allowed cells
    plus the origin. Prefer directly reachable enemies; otherwise return the
    allowed prefix of a full-board path. Paths include the origin, and only
    reach the enemy destination when ``reaches_target`` is true.
    Supply a fresh observation after every move or battle, including enemy spawns.
    """
    if policy not in ("clear_all", "boss_first"):
        raise ValueError("unsupported target policy")
    if guard_count is None and policy == "clear_all":
        return Selection(stop_reason="guard_count_unknown")
    if guard_count is not None and guard_count < 0:
        raise ValueError("guard_count must be non-negative")
    if mobility == "unknown":
        return Selection(stop_reason="mobility_unknown")
    if mobility not in ("bounded", "unrestricted"):
        raise ValueError("unsupported mobility")
    if mobility == "bounded" and allowed_cells is None:
        return Selection(stop_reason="movement_range_unknown")
    if origin not in walkable_cells or origin in blocked_cells:
        return Selection(stop_reason="origin_not_walkable")

    occupied = {enemy.cell for enemy in enemies}
    if len(occupied) != len(enemies) or origin in occupied:
        raise ValueError("enemy cells must be distinct and different from the origin")
    guards = [enemy for enemy in enemies if not enemy.boss]
    bosses = [enemy for enemy in enemies if enemy.boss]
    if policy == "boss_first":
        candidate_groups = [bosses, guards]
    else:
        if not guards:
            assert guard_count is not None
            if guard_count > 0:
                return Selection(stop_reason="guards_not_visible")
            if not bosses:
                return Selection(stop_reason="boss_not_visible")
        candidate_groups = [guards or bosses]

    traversable = set(walkable_cells) - blocked_cells
    regions = [traversable]
    if mobility == "bounded":
        assert allowed_cells is not None
        regions.insert(0, traversable & (allowed_cells | {origin}))
    no_safe_advance = False
    for candidates in candidate_groups:
        if not candidates:
            continue
        for region in regions:
            parents: dict[Cell, Cell | None] = {origin: None}
            distances = {origin: 0}
            queue = deque([origin])
            while queue:
                cell = queue.popleft()
                x, y = cell
                for neighbor in ((x - 1, y), (x, y - 1), (x, y + 1), (x + 1, y)):
                    if neighbor not in region or neighbor in parents:
                        continue
                    parents[neighbor] = cell
                    distances[neighbor] = distances[cell] + 1
                    # An enemy can be a destination, never a passage to another cell.
                    if neighbor not in occupied:
                        queue.append(neighbor)

            target = min(
                (enemy for enemy in candidates if enemy.cell in parents),
                key=lambda enemy: (distances[enemy.cell], enemy.cell),
                default=None,
            )
            if target is None:
                continue
            path: list[Cell] = []
            cursor: Cell | None = target.cell
            while cursor is not None:
                path.append(cursor)
                cursor = parents[cursor]
            path.reverse()
            if mobility == "bounded":
                assert allowed_cells is not None
                for index, cell in enumerate(path[1:], start=1):
                    if cell not in allowed_cells:
                        path = path[:index]
                        break
            if len(path) < 2:
                no_safe_advance = True
                continue
            return Selection(target=target, path=tuple(path))
    return Selection(stop_reason="no_safe_advance" if no_safe_advance else "no_reachable_enemy")


if __name__ == "__main__":
    grid = {(x, y) for x in range(3) for y in range(3)}
    guard = Enemy((2, 0), strength=2)
    common = dict(
        walkable_cells=grid,
        origin=(0, 0),
        blocked_cells={(1, 0)},
        enemies=(guard,),
        guard_count=1,
        mobility="unrestricted",
    )
    selection = select_target(**common)
    assert selection.target == guard
    assert selection.path == ((0, 0), (0, 1), (1, 1), (2, 1), (2, 0))
    assert selection.reaches_target

    boss = Enemy((1, 0), boss=True)
    corridor = {(0, 0), (1, 0), (2, 0)}
    assert (
        select_target(
            **(common | dict(walkable_cells=corridor, blocked_cells=set(), enemies=(boss, guard)))
        ).stop_reason
        == "no_reachable_enemy"
    )
    boss_only = common | dict(blocked_cells=set(), enemies=(boss,))
    assert select_target(**boss_only).stop_reason == "guards_not_visible"
    assert (
        select_target(**(boss_only | dict(guard_count=None))).stop_reason == "guard_count_unknown"
    )
    assert select_target(**(boss_only | dict(guard_count=0))).target == boss
    assert (
        select_target(
            **(common | dict(guard_count=0, enemies=(boss, guard), blocked_cells=set()))
        ).target
        == guard
    )
    bounded = common | dict(mobility="bounded", allowed_cells={(0, 1), (1, 1)})
    selection = select_target(**bounded)
    assert selection.target == guard
    assert selection.path == ((0, 0), (0, 1), (1, 1))
    assert not selection.reaches_target
    assert select_target(**(bounded | dict(allowed_cells=set()))).stop_reason == "no_safe_advance"
    assert (
        select_target(**(bounded | dict(blocked_cells={(1, 0), (0, 1)}))).stop_reason
        == "no_reachable_enemy"
    )
    assert (
        select_target(**(bounded | dict(walkable_cells={(0, 0), (2, 0)}))).stop_reason
        == "no_reachable_enemy"
    )
    assert (
        select_target(**(boss_only | dict(mobility="bounded", allowed_cells={(0, 1)}))).stop_reason
        == "guards_not_visible"
    )
    direct = Enemy((0, 2))
    selection = select_target(
        **(
            bounded
            | dict(
                enemies=(Enemy((1, 0)), direct),
                blocked_cells=set(),
                allowed_cells={(0, 1), (0, 2)},
            )
        )
    )
    assert selection.target == direct and selection.reaches_target
    assert selection.path == ((0, 0), (0, 1), (0, 2))
    assert select_target(**(common | dict(mobility="unknown"))).stop_reason == "mobility_unknown"
    assert (
        select_target(**(common | dict(mobility="bounded"))).stop_reason == "movement_range_unknown"
    )
    near = (Enemy((0, 1)), Enemy((1, 0)))
    assert (
        select_target(**(common | dict(enemies=tuple(reversed(near)), blocked_cells=set()))).target
        == near[0]
    )
    obstacles = {(0, 0), (4, 0), (4, 1), (1, 3), (2, 3), (2, 4), (4, 5), (0, 7), (1, 7), (2, 7)}
    selection = select_target(
        walkable_cells={(x, y) for x in range(5) for y in range(9)} - obstacles,
        origin=(4, 2),
        blocked_cells={(1, 0), (2, 1)},
        enemies=tuple(Enemy(cell) for cell in ((0, 3), (2, 5), (4, 6), (4, 8))),
        guard_count=4,
        mobility="bounded",
        allowed_cells={
            (1, 2),
            (2, 2),
            (3, 2),
            (4, 2),
            (2, 1),
            (3, 1),
            (3, 0),
            (3, 3),
            (4, 3),
            (3, 4),
            (4, 4),
        },
    )
    assert selection.target == Enemy((0, 3))
    assert selection.path == ((4, 2), (3, 2), (2, 2), (1, 2))
    assert not selection.reaches_target

    mixed = common | dict(blocked_cells=set(), enemies=(boss, guard))
    assert select_target(**mixed) == select_target(**mixed, policy="clear_all")
    assert select_target(**mixed).target == guard
    assert select_target(**mixed, policy="boss_first").target == boss
    assert select_target(**(mixed | dict(guard_count=None)), policy="boss_first").target == boss
    assert select_target(**common, policy="boss_first").target == guard
    assert (
        select_target(**(mixed | dict(mobility="unknown")), policy="boss_first").stop_reason
        == "mobility_unknown"
    )
    blocking_guard = Enemy((1, 0))
    distant_boss = Enemy((2, 0), boss=True)
    assert (
        select_target(
            **(
                common
                | dict(
                    walkable_cells=corridor,
                    blocked_cells=set(),
                    enemies=(blocking_guard, distant_boss),
                )
            ),
            policy="boss_first",
        ).target
        == blocking_guard
    )
    near_guard = Enemy((0, 1))
    far_boss = Enemy((2, 2), boss=True)
    boss_advance = common | dict(
        blocked_cells=set(),
        enemies=(near_guard, far_boss),
        mobility="bounded",
        allowed_cells={(0, 1), (1, 0), (1, 1)},
    )
    assert select_target(**boss_advance).target == near_guard
    selection = select_target(**boss_advance, policy="boss_first")
    assert selection.target == far_boss and not selection.reaches_target
    assert selection.path == ((0, 0), (1, 0), (1, 1))
    assert (
        select_target(
            **(boss_advance | dict(enemies=(near_guard, distant_boss), allowed_cells={(0, 1)})),
            policy="boss_first",
        ).target
        == near_guard
    )
    print("Battlefield policy check passed")
