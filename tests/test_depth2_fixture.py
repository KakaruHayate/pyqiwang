#!/usr/bin/env python3
"""Optional slower ROM-free parity check for the depth-2 corpus."""
from __future__ import annotations

import json
from pathlib import Path

from pyqiwang import BLACK, RED, Board, NativeQiWangEngine


def _board(record: dict) -> Board:
    board = Board()
    board.pieces[RED] = list(record["red"])
    board.pieces[BLACK] = list(record["black"])
    board.side_to_move = record["side"]
    board.move_history = []
    board._init_board()
    return board


def test_depth2_independent_parity() -> None:
    path = Path(__file__).with_name("fixtures") / "rom_depth2_independent.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    engine = NativeQiWangEngine(depth=2)
    agreement = 0
    for case in data["cases"]:
        want = tuple(case["best_move"]) if case["best_move"] else None
        agreement += engine.get_best_move(_board(case["board"])) == want
    assert len(data["cases"]) == 8
    assert agreement == 8


def main() -> int:
    test_depth2_independent_parity()
    print("independent ROM depth-2: 8/8 ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
