#!/usr/bin/env python3
"""Correctness and search-stat tests for EnhancedEngine."""
from __future__ import annotations

import random

from pyqiwang import Board, EnhancedEngine, FastEnhancedEngine, generate_legal_moves
from pyqiwang._notation import board_from_fen


def random_board(seed: int, plies: int = 8) -> Board:
    rng = random.Random(seed)
    board = Board()
    for _ in range(plies):
        legal = generate_legal_moves(board, board.side_to_move)
        if not legal:
            break
        board.make_move(*rng.choice(legal))
    return board


def test_start_position() -> None:
    board = Board()
    engine = EnhancedEngine(depth=3)
    move = engine.search(board)
    assert move in generate_legal_moves(board, board.side_to_move)
    stats = engine.stats()
    assert stats["depth"] == 3
    assert stats["nodes"] > 0
    assert stats["tt_entries"] > 0


def test_forced_king_capture() -> None:
    board = board_from_fen("4k4/4R4/9/9/9/9/9/9/9/4K4 w - - 0 1")
    engine = EnhancedEngine(depth=2)
    move = engine.search(board)
    assert move == (4 * 12 + 8, 4 * 12 + 9)
    assert engine.last_score >= 29000


def test_fast_engine() -> None:
    board = Board()
    engine = FastEnhancedEngine(depth=4)
    move = engine.search(board)
    assert move in generate_legal_moves(board, board.side_to_move)
    assert engine.last_depth == 4
    assert engine.stats()["tt_entries"] > 0


def test_python_rust_differential() -> None:
    for seed in range(3):
        board = random_board(seed)
        python = EnhancedEngine(depth=3)
        rust = FastEnhancedEngine(depth=3)
        python_move = python.search(board)
        rust_move = rust.search(board)
        assert rust_move == python_move, (seed, python_move, rust_move)
        assert rust.stats()["score"] == python.stats()["score"], seed


def test_time_limit_returns_completed_iteration() -> None:
    board = Board()
    engine = EnhancedEngine(depth=10, time_limit=0.05)
    move = engine.search(board)
    assert move in generate_legal_moves(board, board.side_to_move)
    assert 0 <= engine.last_depth < 10
    fast = FastEnhancedEngine(depth=10, time_limit=0.001)
    fast_move = fast.search(board)
    assert fast_move in generate_legal_moves(board, board.side_to_move)
    assert fast.last_depth < 10


def main() -> None:
    test_start_position()
    test_forced_king_capture()
    test_fast_engine()
    test_python_rust_differential()
    test_time_limit_returns_completed_iteration()
    print("EnhancedEngine tests passed")


if __name__ == "__main__":
    main()
