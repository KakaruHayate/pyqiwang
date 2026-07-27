#!/usr/bin/env python3
"""Show the capture tree scores behind one Native root candidate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pyqiwang import NativeQiWangEngine, pos_to_notation
from pyqiwang._board import evaluate, evaluate_raw, generate_moves, is_in_check
from pyqiwang._native import INFINITY
from tools.trace_native_root import board_from_record

Move = tuple[int, int]


def parse_move(value: str) -> Move:
    try:
        frm, to = value.split(",", 1)
        return int(frm), int(to)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("move must be FROM,TO") from exc


def diagnose(board, root_move: Move) -> dict:
    root_side = board.side_to_move
    board.make_move(*root_move)
    try:
        side = 1 - root_side
        stand = evaluate(board, side)
        captures = []
        for move in generate_moves(board, side):
            captured = board.cells[move[1]]
            if not captured:
                continue
            board.make_move(*move)
            if is_in_check(board, side):
                board.undo_move()
                continue
            try:
                engine = NativeQiWangEngine(depth=1, book=False)
                child_score = engine._quiesce(
                    board, 1 - side, -INFINITY, INFINITY, 2
                )
                score = -child_score
                captures.append({
                    "move": list(move),
                    "notation": pos_to_notation(move[0]) + pos_to_notation(move[1]),
                    "score": score,
                    "raw_after": evaluate_raw(board),
                    "nodes": engine.nodes,
                })
            finally:
                board.undo_move()
        captures.sort(key=lambda item: item["score"], reverse=True)
        exact_engine = NativeQiWangEngine(depth=1, book=False)
        exact = exact_engine._quiesce(board, side, -INFINITY, INFINITY, 1)
        return {
            "root_move": list(root_move),
            "side_at_horizon": side,
            "stand": stand,
            "static_raw": evaluate_raw(board),
            "exact_quiescence": exact,
            "nodes": exact_engine.nodes,
            "captures": captures,
        }
    finally:
        board.undo_move()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--move", type=parse_move, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    case = next(item for item in fixture["cases"] if item["id"] == args.case)
    result = {
        "case": args.case,
        "diagnostic": diagnose(board_from_record(case["board"]), args.move),
    }
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
        print(f"Wrote quiescence diagnostic to {args.output}")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
