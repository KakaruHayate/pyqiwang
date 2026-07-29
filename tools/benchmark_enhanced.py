#!/usr/bin/env python3
"""Benchmark EnhancedEngine and optionally compare moves with Pikafish."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pyqiwang import Board, FastEnhancedEngine
from pyqiwang._notation import board_to_fen, move_to_iccs
from modern_ai import PikafishEngine, find_pikafish


def sample_positions(count: int) -> list[Board]:
    board = Board()
    out = [board.clone()]
    line = [
        (86, 50), (91, 55), (84, 62), (93, 70), (96, 97), (105, 104),
        (62, 64), (55, 53), (14, 38), (19, 43), (12, 37), (21, 46),
    ]
    for move in line:
        if board.cells[move[0]]:
            board.make_move(*move)
            out.append(board.clone())
        if len(out) >= count:
            break
    return out[:count]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--depth", type=int, default=8)
    parser.add_argument("--time", type=float, default=30.0)
    parser.add_argument("--positions", type=int, default=6)
    parser.add_argument("--pikafish-depth", type=int, default=12)
    parser.add_argument("--no-pikafish", action="store_true")
    args = parser.parse_args()

    oracle = None
    if not args.no_pikafish and find_pikafish():
        oracle = PikafishEngine(depth=args.pikafish_depth, movetime=None, threads=1, hash_mb=64)
    rows = []
    try:
        for index, board in enumerate(sample_positions(args.positions)):
            engine = FastEnhancedEngine(depth=args.depth, time_limit=args.time)
            move = engine.search(board)
            row = {
                "index": index,
                "fen": board_to_fen(board),
                "enhanced": move_to_iccs(move) if move else None,
                **engine.stats(),
            }
            if oracle is not None:
                oracle_move = oracle.search(board, board.side_to_move)
                row["pikafish"] = move_to_iccs(oracle_move) if oracle_move else None
                row["matches_pikafish"] = move == oracle_move
                row["pikafish_score"] = oracle.last_score
                row["pikafish_depth"] = oracle.last_depth
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False))
    finally:
        if oracle is not None:
            oracle.close()
    if oracle is not None:
        matches = sum(bool(row.get("matches_pikafish")) for row in rows)
        print(f"agreement: {matches}/{len(rows)}")


if __name__ == "__main__":
    main()
