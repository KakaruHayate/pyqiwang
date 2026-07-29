#!/usr/bin/env python3
"""Tests for Xiangqi notation and the UCCI adapter."""
from __future__ import annotations

from io import StringIO
import os

from pyqiwang import Board, QiWangEngine
from pyqiwang._harness import RomHarness
from pyqiwang._notation import (
    STARTPOS_FEN,
    board_from_fen,
    board_to_fen,
    iccs_to_move,
    move_to_iccs,
)
from pyqiwang.ucci import UcciSession


def test_fen_round_trip() -> None:
    board = Board()
    assert board_to_fen(board) == STARTPOS_FEN
    restored = board_from_fen(STARTPOS_FEN)
    assert restored.pieces == board.pieces
    assert restored.cells == board.cells
    assert restored.side_to_move == board.side_to_move


def test_move_round_trip() -> None:
    for text in ("h2e2", "a0a1", "i9h9"):
        assert move_to_iccs(iccs_to_move(text)) == text


def test_verified_runtime_image() -> None:
    harness = RomHarness(core="python")
    harness.boot()
    harness.init_board()
    assert len(harness.bus.prg) == 65536


def test_environment_image_override() -> None:
    previous = os.environ.get("PYQIWANG_ROM_IMAGE")
    try:
        os.environ["PYQIWANG_ROM_IMAGE"] = "qiwang.prg"
        engine = QiWangEngine(depth=1, core="python")
        assert len(engine.harness.bus.prg) == 65536
    finally:
        if previous is None:
            os.environ.pop("PYQIWANG_ROM_IMAGE", None)
        else:
            os.environ["PYQIWANG_ROM_IMAGE"] = previous


class FakeEngine:
    def __init__(self, **kwargs) -> None:
        self.depth = kwargs["depth"]

    def get_best_move(self, board):
        return iccs_to_move("h2e2")

    def evaluate(self, board):
        return 7


def test_ucci_session() -> None:
    output = StringIO()
    session = UcciSession(
        input_stream=StringIO(),
        output_stream=output,
        engine_factory=FakeEngine,
    )
    for command in (
        "ucci",
        "isready",
        "setoption depth 3",
        "position startpos moves h2e2 h7e7",
        "position fen " + STARTPOS_FEN,
        "go depth 3",
        "quit",
    ):
        assert session.handle(command) is (command != "quit")
    text = output.getvalue()
    assert "ucciok\n" in text
    assert "readyok\n" in text
    assert "info time " in text
    assert " depth 3 score 7\n" in text
    assert "bestmove h2e2\n" in text
    assert text.endswith("bye\n")


def main() -> None:
    test_fen_round_trip()
    test_move_round_trip()
    test_verified_runtime_image()
    test_environment_image_override()
    test_ucci_session()
    print("UCCI tests passed")


if __name__ == "__main__":
    main()
