"""Minimal synchronous UCCI adapter for QiWangEngine.

Run with ``python -m pyqiwang.ucci`` and communicate over stdin/stdout.
"""
from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from typing import TextIO

from pyqiwang import Board, QiWangEngine, generate_legal_moves
from pyqiwang._notation import STARTPOS_FEN, board_from_fen, iccs_to_move, move_to_iccs


class UcciSession:
    def __init__(
        self,
        input_stream: TextIO = sys.stdin,
        output_stream: TextIO = sys.stdout,
        engine_factory: Callable[..., QiWangEngine] = QiWangEngine,
        rom_path: str | None = None,
        core: str = "auto",
    ) -> None:
        self.input = input_stream
        self.output = output_stream
        self.engine_factory = engine_factory
        self.rom_path = rom_path
        self.core = core
        self.depth = 2
        self.use_book = False
        self.board = Board()
        self.engine: QiWangEngine | None = None
        self.banned: set[tuple[int, int]] = set()

    def send(self, text: str) -> None:
        self.output.write(text + "\n")
        self.output.flush()

    def _ensure_engine(self) -> QiWangEngine:
        if self.engine is None:
            self.engine = self.engine_factory(
                rom_path=self.rom_path,
                depth=self.depth,
                book=self.use_book,
                core=self.core,
            )
        return self.engine

    def _reset_engine(self) -> None:
        self.engine = None

    def _set_option(self, args: list[str]) -> None:
        words = list(args)
        if words and words[0].lower() == "name":
            words.pop(0)
        if "value" in [word.lower() for word in words]:
            index = [word.lower() for word in words].index("value")
            name = " ".join(words[:index]).lower()
            value = " ".join(words[index + 1:])
        elif len(words) >= 2:
            name, value = words[0].lower(), words[1]
        else:
            return
        if name in ("depth", "search depth"):
            self.depth = max(1, min(12, int(value)))
            if self.engine is not None:
                self.engine.depth = self.depth
        elif name in ("usebook", "use book"):
            enabled = value.lower() in ("1", "true", "yes", "on")
            if enabled != self.use_book:
                self.use_book = enabled
                self._reset_engine()
        elif name in ("core", "execution core") and value.lower() in ("auto", "python", "rust"):
            if value.lower() != self.core:
                self.core = value.lower()
                self._reset_engine()

    def _set_position(self, args: list[str]) -> None:
        if not args:
            raise ValueError("position requires startpos or fen")
        lower = [item.lower() for item in args]
        if lower[0] == "startpos":
            board = board_from_fen(STARTPOS_FEN)
            move_index = 1
        elif lower[0] == "fen":
            try:
                move_index = lower.index("moves")
            except ValueError:
                move_index = len(args)
            board = board_from_fen(" ".join(args[1:move_index]))
        else:
            raise ValueError("position requires startpos or fen")

        if move_index < len(args) and lower[move_index] == "moves":
            for text in args[move_index + 1:]:
                move = iccs_to_move(text)
                if move not in generate_legal_moves(board, board.side_to_move):
                    raise ValueError(f"illegal move in position command: {text}")
                board.make_move(*move)
        self.board = board
        self.banned.clear()

    def _go(self, args: list[str]) -> None:
        words = [word.lower() for word in args]
        if "depth" in words:
            index = words.index("depth")
            if index + 1 < len(words):
                self.depth = max(1, min(12, int(words[index + 1])))
        engine = self._ensure_engine()
        engine.depth = self.depth
        started = time.perf_counter()
        move = engine.get_best_move(self.board)
        elapsed_ms = max(1, int((time.perf_counter() - started) * 1000))
        if move in self.banned:
            self.send("info message ROM best move is banned; constrained search is unsupported")
            move = None
        if move is None:
            self.send("nobestmove")
            return
        self.send(f"info time {elapsed_ms} depth {self.depth} score {engine.evaluate(self.board)}")
        self.send(f"bestmove {move_to_iccs(move)}")

    def handle(self, line: str) -> bool:
        parts = line.strip().split()
        if not parts:
            return True
        command, args = parts[0].lower(), parts[1:]
        try:
            if command == "ucci":
                self.send("id name pyqiwang")
                self.send("id version 1.1.0")
                self.send("id author Kakaru")
                self.send("option usebook type check default false")
                self.send("option depth type spin default 2 min 1 max 12")
                self.send("option core type combo default auto var auto var python var rust")
                self.send("ucciok")
            elif command == "isready":
                self._ensure_engine()
                self.send("readyok")
            elif command == "setoption":
                self._set_option(args)
            elif command in ("newgame", "ucinewgame"):
                self.board = Board()
                self.banned.clear()
                self._reset_engine()
            elif command == "position":
                self._set_position(args)
            elif command == "banmoves":
                self.banned = {iccs_to_move(text) for text in args}
            elif command == "go":
                self._go(args)
            elif command == "stop":
                self.send("info message search is synchronous; stop is acknowledged between searches")
            elif command == "quit":
                self.send("bye")
                return False
            else:
                self.send(f"info message unknown command: {command}")
        except Exception as exc:
            self.send(f"info message error: {exc}")
        return True

    def run(self) -> None:
        for line in self.input:
            if not self.handle(line):
                break


def main() -> None:
    parser = argparse.ArgumentParser(description="pyqiwang UCCI engine adapter")
    parser.add_argument("--rom", default=None, help="verified .nes or qiwang.prg path")
    parser.add_argument("--core", choices=("auto", "python", "rust"), default="auto")
    args = parser.parse_args()
    UcciSession(rom_path=args.rom, core=args.core).run()


if __name__ == "__main__":
    main()
