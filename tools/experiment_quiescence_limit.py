#!/usr/bin/env python3
"""Measure depth-1 ROM parity across native quiescence ply limits."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyqiwang import BLACK, RED, Board, NativeQiWangEngine
import pyqiwang._native as native


def load_board(record: dict) -> Board:
    board = Board()
    board.pieces[RED] = list(record["red"])
    board.pieces[BLACK] = list(record["black"])
    board.side_to_move = int(record["side"])
    board.move_history = []
    board._init_board()
    return board


def main() -> int:
    fixtures = [
        ROOT / "tests/fixtures/rom_depth1_golden.json",
        ROOT / "tests/fixtures/rom_depth1_independent.json",
    ]
    corpora = [json.loads(path.read_text(encoding="utf-8")) for path in fixtures]
    for limit in range(2, 13):
        native.QUIESCENCE_MAX_PLY = limit
        counts = []
        misses = []
        for data in corpora:
            engine = NativeQiWangEngine(depth=1)
            agreement = 0
            for case in data["cases"]:
                got = engine.get_best_move(load_board(case["board"]))
                want = tuple(case["best_move"]) if case["best_move"] else None
                agreement += got == want
                if got != want:
                    misses.append((case["id"], want, got))
            counts.append(agreement)
        print(limit, counts, sum(counts), misses)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
