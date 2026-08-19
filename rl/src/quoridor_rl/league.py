from __future__ import annotations

import math
from pathlib import Path


def allocate_match_types(
    games: int,
    *,
    champion_available: bool,
    history_available: bool,
    current_weight: float = 0.50,
    champion_weight: float = 0.30,
    history_weight: float = 0.20,
) -> list[str]:
    """Allocate a deterministic, exact-size current/champion/history schedule."""
    if games < 1:
        return []
    weights = {
        "current": max(0.0, current_weight),
        "champion": max(0.0, champion_weight) if champion_available else 0.0,
        "history": max(0.0, history_weight) if history_available else 0.0,
    }
    if weights["history"] == 0.0 and champion_available:
        weights["champion"] += max(0.0, history_weight)
    elif weights["champion"] == 0.0 and history_available:
        weights["history"] += max(0.0, champion_weight)
    total = sum(weights.values())
    if total <= 0:
        return ["current"] * games

    exact = {kind: games * weight / total for kind, weight in weights.items()}
    counts = {kind: math.floor(value) for kind, value in exact.items()}
    remaining = games - sum(counts.values())
    priority = {"current": 2, "champion": 1, "history": 0}
    fractions = sorted(
        weights,
        key=lambda kind: (exact[kind] - counts[kind], priority[kind]),
        reverse=True,
    )
    for kind in fractions[:remaining]:
        counts[kind] += 1

    # Interleave sources so worker completion order cannot create long source runs.
    schedule: list[str] = []
    while len(schedule) < games:
        for kind in ("current", "champion", "history"):
            if counts[kind] > 0:
                schedule.append(kind)
                counts[kind] -= 1
    return schedule


def qualifies_for_promotion(
    *,
    score: float,
    p1_win_rate: float,
    p2_win_rate: float,
    minimum_score: float = 0.55,
    minimum_seat_win_rate: float = 0.40,
) -> bool:
    return (
        score >= minimum_score
        and p1_win_rate >= minimum_seat_win_rate
        and p2_win_rate >= minimum_seat_win_rate
    )


def _snapshot_iteration(path: Path) -> int | None:
    try:
        return int(path.stem.rsplit("_", 1)[1])
    except (IndexError, ValueError):
        return None


def select_history_paths(
    paths: list[Path],
    *,
    recent_iterations: int = 6,
    champion_count: int = 3,
) -> list[Path]:
    """Keep recent iteration snapshots and champions, deduplicated by iteration."""
    champions = sorted(
        (
            (_snapshot_iteration(path), path)
            for path in paths
            if path.name.startswith("champion_")
        ),
        key=lambda item: item[0] if item[0] is not None else -1,
        reverse=True,
    )
    iterations = sorted(
        (
            (_snapshot_iteration(path), path)
            for path in paths
            if path.name.startswith("iteration_")
        ),
        key=lambda item: item[0] if item[0] is not None else -1,
        reverse=True,
    )
    selected: list[Path] = []
    seen: set[int] = set()
    for iteration, path in champions[: max(0, champion_count)]:
        if iteration is not None and iteration not in seen:
            selected.append(path)
            seen.add(iteration)
    added_iterations = 0
    for iteration, path in iterations:
        if added_iterations >= max(0, recent_iterations):
            break
        if iteration is not None and iteration not in seen:
            selected.append(path)
            seen.add(iteration)
            added_iterations += 1
    return selected
