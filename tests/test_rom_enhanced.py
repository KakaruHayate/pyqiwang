#!/usr/bin/env python3
"""Checks for the minimal ROM-native deeper-search mode."""
from __future__ import annotations

import random

from pyqiwang import Board, QiWangEngine, generate_legal_moves


def random_board(seed: int, plies: int) -> Board:
    rng = random.Random(seed)
    board = Board()
    for _ in range(plies):
        legal = generate_legal_moves(board, board.side_to_move)
        if not legal:
            break
        board.make_move(*rng.choice(legal))
    return board


def main() -> None:
    engine = QiWangEngine(depth=4, core="rust")
    opening = Board()
    assert engine.get_best_move(opening) == (86, 50)
    assert engine.get_enhanced_move(opening) == (86, 50)

    differences = 0
    for index in range(8):
        board = random_board(20260729 + index, 7 + index)
        normal = engine.get_best_move(board)
        enhanced = engine.get_enhanced_move(board)
        legal = generate_legal_moves(board, board.side_to_move)
        assert normal in legal
        assert enhanced in legal
        differences += normal != enhanced
    print(f"ROM-native depth 5 differs from depth 4 on {differences}/8 sample positions")
    print("ROM enhanced tests passed")


if __name__ == "__main__":
    main()
