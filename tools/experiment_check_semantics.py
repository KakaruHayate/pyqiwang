#!/usr/bin/env python3
"""Compare Native horizon check semantics against ROM parity corpora."""
from __future__ import annotations

import json
from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pyqiwang._board import evaluate, generate_moves, is_in_check
from pyqiwang._native import MATE_SCORE, QUIESCENCE_MAX_PLY, NativeQiWangEngine
from tools.trace_native_root import board_from_record

CORPORA = [
    ("depth1-golden", "rom_depth1_golden.json", 1),
    ("depth1-independent", "rom_depth1_independent.json", 1),
    ("depth2-independent", "rom_depth2_independent.json", 2),
]


class StaticCheckHorizonEngine(NativeQiWangEngine):
    """At the horizon, score check positions statically instead of evading."""

    def _quiesce(self, board, side, alpha, beta, ply):
        self._visit()
        if not self._king_alive(board, side):
            return -MATE_SCORE + ply
        if not self._king_alive(board, 1 - side):
            return MATE_SCORE - ply

        stand = evaluate(board, side)
        if stand >= beta:
            return stand
        if stand > alpha:
            alpha = stand
        if ply >= QUIESCENCE_MAX_PLY:
            return alpha

        for frm, to in generate_moves(board, side):
            captured = board.cells[to]
            if not captured:
                continue
            board.make_move(frm, to)
            if is_in_check(board, side):
                board.undo_move()
                continue
            try:
                score = -self._quiesce(
                    board, 1 - side, -beta, -alpha, ply + 1
                )
            finally:
                board.undo_move()
            if score >= beta:
                return score
            if score > alpha:
                alpha = score
        return alpha


class PreRecursionBoundEngine(StaticCheckHorizonEngine):
    """Apply the incremental PST bound before selectively descending."""

    def _quiesce(self, board, side, alpha, beta, ply):
        self._visit()
        if not self._king_alive(board, side):
            return -MATE_SCORE + ply
        if not self._king_alive(board, 1 - side):
            return MATE_SCORE - ply

        stand = evaluate(board, side)
        if stand >= beta:
            return stand
        if stand > alpha:
            alpha = stand
        if ply >= QUIESCENCE_MAX_PLY:
            return alpha

        for frm, to in generate_moves(board, side):
            if not board.cells[to]:
                continue
            board.make_move(frm, to)
            if is_in_check(board, side):
                board.undo_move()
                continue
            try:
                immediate = evaluate(board, side)
                if immediate >= beta:
                    return immediate
                score = -self._quiesce(
                    board, 1 - side, -beta, -alpha, ply + 1
                )
            finally:
                board.undo_move()
            if score >= beta:
                return score
            if score > alpha:
                alpha = score
        return alpha


class DeepPreRecursionBoundEngine(StaticCheckHorizonEngine):
    """Apply the immediate PST cutoff only at ROM-like selective levels."""

    bound_min_ply = 2

    def _quiesce(self, board, side, alpha, beta, ply):
        self._visit()
        if not self._king_alive(board, side):
            return -MATE_SCORE + ply
        if not self._king_alive(board, 1 - side):
            return MATE_SCORE - ply

        stand = evaluate(board, side)
        if stand >= beta:
            return stand
        if stand > alpha:
            alpha = stand
        if ply >= QUIESCENCE_MAX_PLY:
            return alpha

        for frm, to in generate_moves(board, side):
            if not board.cells[to]:
                continue
            board.make_move(frm, to)
            if is_in_check(board, side):
                board.undo_move()
                continue
            try:
                immediate = evaluate(board, side)
                if ply >= self.bound_min_ply and immediate >= beta:
                    return immediate
                score = -self._quiesce(
                    board, 1 - side, -beta, -alpha, ply + 1
                )
            finally:
                board.undo_move()
            if score >= beta:
                return score
            if score > alpha:
                alpha = score
        return alpha


class Ply3PreRecursionBoundEngine(DeepPreRecursionBoundEngine):
    bound_min_ply = 3


class PseudoCaptureHorizonEngine(StaticCheckHorizonEngine):
    """At the horizon, search every capture without self-check filtering."""

    def _quiesce(self, board, side, alpha, beta, ply):
        self._visit()
        if not self._king_alive(board, side):
            return -MATE_SCORE + ply
        if not self._king_alive(board, 1 - side):
            return MATE_SCORE - ply

        stand = evaluate(board, side)
        if stand >= beta:
            return stand
        if stand > alpha:
            alpha = stand
        if ply >= QUIESCENCE_MAX_PLY:
            return alpha

        for frm, to in generate_moves(board, side):
            if not board.cells[to]:
                continue
            board.make_move(frm, to)
            try:
                score = -self._quiesce(
                    board, 1 - side, -beta, -alpha, ply + 1
                )
            finally:
                board.undo_move()
            if score >= beta:
                return score
            if score > alpha:
                alpha = score
        return alpha


VARIANTS = [
    ("baseline", NativeQiWangEngine),
    ("static-check-horizon", StaticCheckHorizonEngine),
    ("pre-recursion-bound", PreRecursionBoundEngine),
    ("deep-pre-recursion-bound-ply2", DeepPreRecursionBoundEngine),
    ("deep-pre-recursion-bound-ply3", Ply3PreRecursionBoundEngine),
    ("pseudo-capture-horizon", PseudoCaptureHorizonEngine),
]


def run_variant(name, engine_type, fixture_dir):
    print(name)
    for corpus_name, filename, depth in CORPORA:
        data = json.loads((fixture_dir / filename).read_text(encoding="utf-8"))
        rows = []
        for case in data["cases"]:
            want = tuple(case["best_move"]) if case["best_move"] else None
            engine = engine_type(depth=depth, book=False)
            got = engine.get_best_move(board_from_record(case["board"]))
            rows.append((case["id"], want, got))
        mismatches = [row for row in rows if row[1] != row[2]]
        print(f"  {corpus_name}: {len(rows) - len(mismatches)}/{len(rows)}")
        for row in mismatches:
            print(f"    {row[0]}: ROM={row[1]} Native={row[2]}")


def main() -> int:
    fixture_dir = _REPO_ROOT / "tests" / "fixtures"
    for name, engine_type in VARIANTS:
        run_variant(name, engine_type, fixture_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
