#!/usr/bin/env python3
"""Diagnose mate-style Native scores for one stored fixture candidate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pyqiwang import Board, NativeQiWangEngine, pos_to_notation
from pyqiwang._board import (
    BLACK,
    RED,
    evaluate_raw,
    generate_legal_moves,
    is_in_check,
)
from pyqiwang._native import INFINITY, KING_INDEX
from tools.trace_native_root import board_from_record

Move = tuple[int, int]


def parse_move(value: str) -> Move:
    try:
        frm, to = value.split(",", 1)
        return int(frm), int(to)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("move must be FROM,TO") from exc


def move_record(board: Board, move: Move) -> dict:
    target = board.cells[move[1]]
    return {
        "move": list(move),
        "notation": pos_to_notation(move[0]) + pos_to_notation(move[1]),
        "capture": target != 0,
        "captures_king": any(
            board.pieces[side][KING_INDEX] == move[1] for side in (RED, BLACK)
        ),
    }


class DiagnosticEngine(NativeQiWangEngine):
    def __init__(self, depth: int):
        super().__init__(depth=depth, book=False)
        self.terminals: list[dict] = []

    def _terminal_snapshot(self, board: Board, side: int, ply: int,
                           where: str) -> None:
        red_alive = self._king_alive(board, RED)
        black_alive = self._king_alive(board, BLACK)
        if red_alive and black_alive:
            return
        history = [
            {
                "move": [item[0], item[1]],
                "notation": pos_to_notation(item[0]) + pos_to_notation(item[1]),
                "captured": item[3] != 0,
            }
            for item in board.move_history
        ]
        self.terminals.append({
            "where": where,
            "side": side,
            "ply": ply,
            "red_king": board.pieces[RED][KING_INDEX],
            "black_king": board.pieces[BLACK][KING_INDEX],
            "history": history,
        })

    def _search(self, board: Board, side: int, depth: int,
                alpha: int, beta: int, ply: int) -> int:
        self._terminal_snapshot(board, side, ply, "search_entry")
        return super()._search(board, side, depth, alpha, beta, ply)

    def _quiesce(self, board: Board, side: int,
                 alpha: int, beta: int, ply: int) -> int:
        self._terminal_snapshot(board, side, ply, "quiesce_entry")
        return super()._quiesce(board, side, alpha, beta, ply)


def diagnose(board: Board, root_move: Move, depth: int) -> dict:
    side = board.side_to_move
    if root_move not in generate_legal_moves(board, side):
        raise ValueError(f"root move {root_move} is not legal")

    root = move_record(board, root_move)
    board.make_move(*root_move)
    try:
        reply_side = 1 - side
        replies = generate_legal_moves(board, reply_side)
        reply_results = []
        for reply in replies:
            reply_info = move_record(board, reply)
            engine = DiagnosticEngine(depth)
            board.make_move(*reply)
            try:
                child_score = engine._search(
                    board, side, depth - 2, -INFINITY, INFINITY, 2
                )
                reply_score = -child_score
                reply_info.update({
                    "reply_score": reply_score,
                    "child_score": child_score,
                    "raw_after": evaluate_raw(board),
                    "side_in_check_after": is_in_check(board, side),
                    "legal_after": len(generate_legal_moves(board, side))
                    if engine._king_alive(board, side) else 0,
                    "nodes": engine.nodes,
                    "terminal_count": len(engine.terminals),
                    "first_terminal": engine.terminals[0]
                    if engine.terminals else None,
                })
            finally:
                board.undo_move()
            reply_results.append(reply_info)
    finally:
        board.undo_move()

    reply_results.sort(key=lambda item: item["reply_score"], reverse=True)
    return {
        "root": root,
        "depth": depth,
        "reply_count": len(reply_results),
        "replies_by_score": reply_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--case", default="random-004")
    parser.add_argument("--move", type=parse_move, required=True)
    parser.add_argument("--depth", type=int, default=2)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    case = next((item for item in fixture["cases"] if item["id"] == args.case), None)
    if case is None:
        raise SystemExit(f"Unknown fixture case: {args.case}")

    result = {
        "case": args.case,
        "expected": case["best_move"],
        "diagnostic": diagnose(board_from_record(case["board"]), args.move, args.depth),
    }
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"Wrote native mate diagnostic to {args.output}")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
