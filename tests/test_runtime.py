#!/usr/bin/env python3
"""Tests for ModernRomRuntime caching and adaptive depth policy."""
from __future__ import annotations

from pyqiwang import Board, ModernRomRuntime, generate_legal_moves


def main() -> None:
    board = Board()
    runtime = ModernRomRuntime(base_depth=4, max_depth=5, core="rust")
    assert runtime.choose_depth(board) == 4
    first = runtime.search(board)
    before = runtime.engine.harness.instr_count
    second = runtime.search(board)
    assert first == second
    assert second in generate_legal_moves(board, board.side_to_move)
    assert runtime.engine.harness.instr_count == before
    stats = runtime.get_stats()
    assert stats["searches"] == 1
    assert stats["cache_hits"] == 1
    assert stats["hit_rate"] == 0.5

    board.make_move(*first)
    assert runtime.search(board) in generate_legal_moves(board, board.side_to_move)
    assert runtime.get_stats()["searches"] == 2

    ponder_board = Board()
    ponder = ModernRomRuntime(base_depth=1, max_depth=1, core="rust")
    replies = generate_legal_moves(ponder_board, ponder_board.side_to_move)
    info = ponder.ponder_replies(ponder_board, depth=1,
                                  max_replies=2, workers=2)
    assert info["completed"] == 2
    ponder_board.make_move(*replies[0])
    before = ponder.engine.harness.instr_count
    assert ponder.search(ponder_board, depth=1) in generate_legal_moves(
        ponder_board, ponder_board.side_to_move)
    assert ponder.engine.harness.instr_count == before
    assert ponder.get_stats()["cache_hits"] == 1

    book_move = generate_legal_moves(Board(), Board().side_to_move)[0]
    knowledge = ModernRomRuntime(
        base_depth=4, max_depth=4, core="rust",
        opening_lookup=lambda _: book_move,
    )
    before = knowledge.engine.harness.instr_count
    assert knowledge.search(Board()) == book_move
    assert knowledge.engine.harness.instr_count == before
    assert knowledge.get_stats()["knowledge_hits"]["opening"] == 1
    print("ModernRomRuntime tests passed")


if __name__ == "__main__":
    main()
