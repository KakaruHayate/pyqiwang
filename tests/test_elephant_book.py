#!/usr/bin/env python3
"""Tests for user-supplied ElephantEye BOOK.DAT integration."""
from __future__ import annotations

import argparse

from pyqiwang import Board, ElephantBook, ModernRomRuntime, generate_legal_moves


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("book")
    args = parser.parse_args()
    book = ElephantBook(args.book)
    board = Board()
    candidates = book.candidates(board)
    assert book.stats()["records"] == 12081
    assert len(candidates) >= 10
    assert candidates[0][0] in ((14, 50), (86, 50))
    assert all(move in generate_legal_moves(board, board.side_to_move)
               for move, _ in candidates)

    runtime = ModernRomRuntime(
        base_depth=6, max_depth=7, core="rust",
        opening_lookup=book.lookup,
    )
    before = runtime.engine.harness.instr_count
    move = runtime.search(board)
    assert move in generate_legal_moves(board, board.side_to_move)
    assert runtime.engine.harness.instr_count == before
    assert runtime.get_stats()["knowledge_hits"]["opening"] == 1

    misses = 0
    for _ in range(40):
        move = book.lookup(board)
        if move is None:
            misses += 1
            break
        board.make_move(*move)
    assert misses == 1 or len(board.move_history) == 40
    print(f"ElephantBook tests passed; covered {len(board.move_history)} plies")


if __name__ == "__main__":
    main()
