#!/usr/bin/env python3
"""Match ModernRomRuntime against faithful ROM depth 4 from book prefixes."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pyqiwang import BLACK, RED, Board, ModernRomRuntime, QiWangEngine
from pyqiwang._board import generate_legal_moves, is_in_check


def book_prefix(plies: int) -> Board:
    board = Board()
    source = QiWangEngine(depth=2, book=True, core="rust")
    for index in range(plies):
        if not source._book_applies(board):
            raise RuntimeError(f"book ended before requested ply {index + 1}")
        move = source.get_best_move(board)
        if move not in generate_legal_moves(board, board.side_to_move):
            raise RuntimeError(f"illegal book move at ply {index + 1}: {move}")
        board.make_move(*move)
    return board


def play(prefix: int, runtime_side: int, max_plies: int) -> dict:
    board = book_prefix(prefix)
    runtime = ModernRomRuntime(base_depth=5, max_depth=6, core="rust")
    faithful = QiWangEngine(depth=4, book=False, core="rust")
    seen = {}
    records = []
    result, reason, winner = "unresolved", "ply limit", None
    for ply in range(max_plies):
        side = board.side_to_move
        legal = generate_legal_moves(board, side)
        if not legal:
            winner_side = 1 - side
            winner = "runtime" if winner_side == runtime_side else "depth4"
            result = f"{winner} wins"
            reason = "checkmate" if is_in_check(board, side) else "stalemate"
            break
        if side == runtime_side:
            selected = runtime.choose_depth(board)
            move = runtime.search(board, depth=selected)
            who = "runtime"
        else:
            selected = 4
            move = faithful.get_best_move(board)
            who = "depth4"
        if move not in legal:
            winner = "depth4" if who == "runtime" else "runtime"
            result, reason = f"{winner} wins", "illegal move"
            break
        records.append({"ply": ply + 1, "engine": who,
                        "side": "red" if side == RED else "black",
                        "depth": selected, "move": list(move)})
        board.make_move(*move)
        key = (tuple(board.pieces[RED]), tuple(board.pieces[BLACK]), board.side_to_move)
        seen[key] = seen.get(key, 0) + 1
        if seen[key] >= 3:
            result, reason = "draw", "threefold repetition"
            break
    return {
        "book_prefix": prefix,
        "runtime_side": "red" if runtime_side == RED else "black",
        "result": result,
        "winner": winner,
        "reason": reason,
        "played_plies": len(records),
        "runtime_stats": runtime.get_stats(),
        "moves": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefixes", type=int, nargs="+", default=[0, 8, 16, 24])
    parser.add_argument("--plies", type=int, default=120)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    games = []
    for prefix in args.prefixes:
        for side in (RED, BLACK):
            row = play(prefix, side, args.plies)
            games.append(row)
            print(json.dumps({key: value for key, value in row.items()
                              if key != "moves"}, ensure_ascii=False), flush=True)
    Path(args.out).write_text(
        json.dumps({"games": games}, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
