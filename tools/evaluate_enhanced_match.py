#!/usr/bin/env python3
"""Run a small colour-swapped EnhancedEngine vs ROM match sample."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pyqiwang import BLACK, RED, Board, FastEnhancedEngine, QiWangEngine
from pyqiwang._board import generate_legal_moves, is_in_check


def game(enhanced_side: int, depth: int, seconds: float, max_plies: int) -> dict:
    board = Board()
    rom = QiWangEngine(depth=4, book=False)
    enhanced = FastEnhancedEngine(depth=depth, time_limit=seconds)
    seen = {}
    result = "limit"
    for ply in range(max_plies):
        legal = generate_legal_moves(board, board.side_to_move)
        if not legal:
            loser = board.side_to_move
            winner = 1 - loser
            result = ("enhanced" if winner == enhanced_side else "rom") + (
                " mate" if is_in_check(board, loser) else " stalemate"
            )
            break
        move = enhanced.search(board) if board.side_to_move == enhanced_side else rom.get_best_move(board)
        if move not in legal:
            result = "illegal move"
            break
        board.make_move(*move)
        key = (tuple(board.pieces[RED]), tuple(board.pieces[BLACK]), board.side_to_move)
        seen[key] = seen.get(key, 0) + 1
        if seen[key] >= 3:
            result = "draw repetition"
            break
    return {"enhanced_side": "red" if enhanced_side == RED else "black", "result": result, "plies": ply + 1}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--depth", type=int, default=8)
    parser.add_argument("--time", type=float, default=3.0)
    parser.add_argument("--plies", type=int, default=100)
    args = parser.parse_args()
    for side in (RED, BLACK):
        print(game(side, args.depth, args.time, args.plies))


if __name__ == "__main__":
    main()
