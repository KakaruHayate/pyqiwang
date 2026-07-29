#!/usr/bin/env python3
"""Run colour-swapped matches between two depths of the original ROM search."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pyqiwang import BLACK, RED, Board, QiWangEngine
from pyqiwang._board import generate_legal_moves, is_in_check, pos_to_notation


def move_text(move: tuple[int, int]) -> str:
    return pos_to_notation(move[0]) + pos_to_notation(move[1])


def play_game(depth5_side: int, max_plies: int, core: str,
              verbose: bool = False) -> dict:
    board = Board()
    engines = {
        depth5_side: QiWangEngine(depth=5, book=False, core=core),
        1 - depth5_side: QiWangEngine(depth=4, book=False, core=core),
    }
    seen = {}
    moves = []
    totals = {4: {"seconds": 0.0, "instructions": 0, "moves": 0},
              5: {"seconds": 0.0, "instructions": 0, "moves": 0}}
    result = "unresolved"
    winner_depth = None
    reason = "ply limit"

    for ply in range(max_plies):
        side = board.side_to_move
        legal = generate_legal_moves(board, side)
        if not legal:
            winner_side = 1 - side
            winner_depth = 5 if winner_side == depth5_side else 4
            reason = "checkmate" if is_in_check(board, side) else "stalemate"
            result = f"depth{winner_depth} wins"
            break

        engine = engines[side]
        depth = 5 if side == depth5_side else 4
        before = engine.harness.instr_count
        started = time.perf_counter()
        try:
            move = engine.get_best_move(board)
        except TimeoutError as exc:
            result = f"depth{depth} timeout"
            reason = str(exc)
            break
        elapsed = time.perf_counter() - started
        instructions = engine.harness.instr_count - before
        if move not in legal:
            result = f"depth{depth} illegal move"
            reason = repr(move)
            break

        totals[depth]["seconds"] += elapsed
        totals[depth]["instructions"] += instructions
        totals[depth]["moves"] += 1
        record = {
            "ply": ply + 1,
            "side": "red" if side == RED else "black",
            "depth": depth,
            "move": move_text(move),
            "seconds": round(elapsed, 6),
            "instructions": instructions,
        }
        moves.append(record)
        if verbose:
            print(json.dumps(record, ensure_ascii=False), flush=True)
        board.make_move(*move)

        key = (tuple(board.pieces[RED]), tuple(board.pieces[BLACK]),
               board.side_to_move)
        seen[key] = seen.get(key, 0) + 1
        if seen[key] >= 3:
            result = "draw"
            reason = "threefold repetition"
            break

    summary = {
        "depth5_side": "red" if depth5_side == RED else "black",
        "result": result,
        "winner_depth": winner_depth,
        "reason": reason,
        "plies": len(moves),
        "totals": totals,
        "moves": moves,
    }
    for depth in (4, 5):
        count = totals[depth]["moves"]
        totals[depth]["mean_seconds"] = (
            totals[depth]["seconds"] / count if count else 0.0)
        totals[depth]["mean_instructions"] = (
            totals[depth]["instructions"] / count if count else 0)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plies", type=int, default=120)
    parser.add_argument("--core", choices=("auto", "python", "rust"), default="rust")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--out", default=None, help="optional JSON result path")
    args = parser.parse_args()
    games = [
        play_game(RED, args.plies, args.core, args.verbose),
        play_game(BLACK, args.plies, args.core, args.verbose),
    ]
    report = {"depth5_vs_depth4": games}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.out:
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
