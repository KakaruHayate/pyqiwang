"""ROM-free access to the FC QiWang sequential opening line."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from pyqiwang._board import RED, BLACK, Board, generate_legal_moves

Move = tuple[int, int]


class OpeningBookDataError(RuntimeError):
    """Raised when the extracted opening-book data is invalid."""


def board_key(board: Board) -> tuple[tuple[int, ...], tuple[int, ...], int]:
    """Return the stable position identity used by the sequential book."""
    return (
        tuple(board.pieces[RED]),
        tuple(board.pieces[BLACK]),
        board.side_to_move,
    )


def _load_moves() -> tuple[Move, ...]:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "opening_book.json")
    try:
        with open(path, encoding="utf-8") as stream:
            data = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise OpeningBookDataError(f"Cannot load opening book: {path}") from exc

    raw = data.get("moves") if isinstance(data, dict) else None
    expected = data.get("source", {}).get("plies") if isinstance(data, dict) else None
    if not isinstance(raw, list) or expected != len(raw) or len(raw) != 33:
        raise OpeningBookDataError("Opening book must contain exactly 33 plies")

    moves: list[Move] = []
    for ply, move in enumerate(raw):
        if (not isinstance(move, list) or len(move) != 2
                or not all(isinstance(value, int) for value in move)):
            raise OpeningBookDataError(f"Invalid move at opening-book ply {ply}")
        moves.append((move[0], move[1]))
    return tuple(moves)


OPENING_LINE = _load_moves()


def _build_positions() -> tuple[tuple[tuple[int, ...], tuple[int, ...], int], ...]:
    board = Board()
    positions = [board_key(board)]
    for ply, move in enumerate(OPENING_LINE):
        if move not in generate_legal_moves(board, board.side_to_move):
            raise OpeningBookDataError(
                f"Opening-book move is illegal at ply {ply}: {move}"
            )
        board.make_move(*move)
        positions.append(board_key(board))
    return tuple(positions)


OPENING_POSITIONS = _build_positions()


@dataclass
class SequentialOpeningBook:
    """Probe the ROM's fixed line by exact board-position matching.

    The book carries no mutable pointer. A position must equal one of the line
    prefixes exactly; a game that diverges naturally receives no book move.
    """

    def probe(self, board: Board) -> Move | None:
        key = board_key(board)
        for ply, position in enumerate(OPENING_POSITIONS[:-1]):
            if key == position:
                return OPENING_LINE[ply]
        return None
