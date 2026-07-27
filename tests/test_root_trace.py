#!/usr/bin/env python3
"""ROM-free structural checks for checked-in root-search traces."""
from __future__ import annotations

import json
from pathlib import Path

FIXTURES = Path(__file__).with_name("fixtures")
TRACE_FILES = (
    "root_trace_initial_depth1.json",
    "root_trace_001_depth1.json",
    "root_trace_002_depth1.json",
    "root_trace_004_depth1.json",
    "root_trace_depth1_independent_015.json",
)
DEPTH2_TRACE_FILES = (
    "root_trace_depth2_independent_004.json",
)


def validate_trace(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    trace = data["trace"]
    assert trace["result"] == data["expected"]
    assert trace["candidate_count"] == len(trace["attempts"])
    assert trace["max_internal_level"] >= 4

    side = trace["attempts"][0]["side"]
    best = 0x1000 if side == 0 else 0xF000
    best_move = None
    for attempt in trace["attempts"]:
        assert attempt["best_before_raw"] == best
        score = attempt["score_raw"]
        better = score > best if side == 0 else score < best
        if better:
            best = score
            best_move = attempt["move"]
        assert attempt["best_after_raw"] == best
        assert attempt["best_move_after"] == best_move
    assert best_move == trace["result"]


def validate_iterative_trace(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    trace = data["trace"]
    assert trace["result"] == data["expected"]
    assert trace["max_internal_level"] >= 4

    attempts_by_iteration: dict[int, list[dict]] = {}
    for attempt in trace["attempts"]:
        attempts_by_iteration.setdefault(attempt["iteration"], []).append(attempt)
    assert sorted(attempts_by_iteration) == [0, 1]
    assert len(attempts_by_iteration[0]) == trace["candidate_count"]
    assert len(attempts_by_iteration[1]) >= trace["candidate_count"]

    final_attempts = attempts_by_iteration[1]
    assert any(attempt["best_move_after"] == trace["result"]
               for attempt in final_attempts)
    assert final_attempts[-1]["best_move_after"] == trace["result"]


def test_root_trace_fixtures() -> None:
    for name in TRACE_FILES:
        validate_trace(FIXTURES / name)
    for name in DEPTH2_TRACE_FILES:
        validate_iterative_trace(FIXTURES / name)


def main() -> int:
    test_root_trace_fixtures()
    total = len(TRACE_FILES) + len(DEPTH2_TRACE_FILES)
    print(f"root trace fixtures: {total}/{total} ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
