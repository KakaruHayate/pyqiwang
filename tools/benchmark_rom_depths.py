#!/usr/bin/env python3
"""Measure the original ROM search at successive experimental depths."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pyqiwang import Board, QiWangEngine, generate_legal_moves
from pyqiwang._board import pos_to_notation


def move_text(move: tuple[int, int] | None) -> str | None:
    if move is None:
        return None
    return pos_to_notation(move[0]) + pos_to_notation(move[1])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-depth", type=int, default=4)
    parser.add_argument("--max-depth", type=int, default=10)
    parser.add_argument("--core", choices=("auto", "python", "rust"), default="rust")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    if args.max_depth > 5 and args.core == "python":
        parser.error("depth > 5 requires the compiled Rust core in practice")

    board = Board()
    rows = []
    for depth in range(args.min_depth, args.max_depth + 1):
        engine = QiWangEngine(depth=depth, core=args.core)
        before = engine.harness.instr_count
        started = time.perf_counter()
        row = {"depth": depth}
        try:
            move = engine.get_best_move(board)
            elapsed = time.perf_counter() - started
            instructions = engine.harness.instr_count - before
            row.update({
                "status": "ok",
                "move": move_text(move),
                "legal": move in generate_legal_moves(board, board.side_to_move),
                "seconds": elapsed,
                "instructions": instructions,
                "instructions_per_second": instructions / elapsed if elapsed else 0,
            })
        except Exception as exc:
            row.update({
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
                "seconds": time.perf_counter() - started,
                "instructions": engine.harness.instr_count - before,
            })
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        if row["status"] != "ok":
            break

    report = {"rom_depth_benchmark": rows}
    if args.out:
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
