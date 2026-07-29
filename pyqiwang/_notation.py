"""Xiangqi FEN and protocol move notation helpers."""
from __future__ import annotations

from itertools import permutations

from pyqiwang._board import (
    ADVISOR,
    BLACK,
    BOARD_STRIDE,
    CANNON,
    ELEPHANT,
    KING,
    KNIGHT,
    PAWN,
    PIECE_TYPES,
    RED,
    ROOK,
    Board,
)

_PIECE_TO_CHAR = {
    KING: "k",
    ADVISOR: "a",
    ELEPHANT: "b",
    ROOK: "r",
    KNIGHT: "n",
    CANNON: "c",
    PAWN: "p",
}
_CHAR_TO_PIECE = {char: piece for piece, char in _PIECE_TO_CHAR.items()}
STARTPOS_FEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"


def move_to_iccs(move: tuple[int, int]) -> str:
    return pos_to_iccs(move[0]) + pos_to_iccs(move[1])


def pos_to_iccs(pos: int) -> str:
    file, rank = divmod(pos, BOARD_STRIDE)
    if not (0 <= file <= 8 and 0 <= rank <= 9):
        raise ValueError(f"invalid board position: {pos}")
    return f"{chr(ord('a') + file)}{rank}"


def iccs_to_move(text: str) -> tuple[int, int]:
    text = text.strip().lower()
    if len(text) != 4:
        raise ValueError(f"invalid ICCS move: {text!r}")
    return iccs_to_pos(text[:2]), iccs_to_pos(text[2:])


def iccs_to_pos(text: str) -> int:
    if len(text) != 2 or text[0] not in "abcdefghi" or text[1] not in "0123456789":
        raise ValueError(f"invalid ICCS square: {text!r}")
    return (ord(text[0]) - ord("a")) * BOARD_STRIDE + int(text[1])


def board_to_fen(board: Board) -> str:
    rows = []
    for rank in range(9, -1, -1):
        row = ""
        empty = 0
        for file in range(9):
            value = board.cells[file * BOARD_STRIDE + rank]
            if value == 0:
                empty += 1
                continue
            if empty:
                row += str(empty)
                empty = 0
            side = (value >> 5) & 1
            piece = PIECE_TYPES[value & 0x0F]
            char = _PIECE_TO_CHAR[piece]
            row += char.upper() if side == RED else char
        if empty:
            row += str(empty)
        rows.append(row)
    active = "w" if board.side_to_move == RED else "b"
    return f"{'/'.join(rows)} {active} - - 0 1"


def board_from_fen(fen: str) -> Board:
    fields = fen.strip().split()
    if len(fields) < 2:
        raise ValueError("Xiangqi FEN must include board and active side")
    rows = fields[0].split("/")
    if len(rows) != 10:
        raise ValueError("Xiangqi FEN must contain 10 ranks")
    active = fields[1].lower()
    if active not in ("w", "r", "b"):
        raise ValueError(f"invalid active side: {fields[1]!r}")

    positions: dict[int, dict[int, list[int]]] = {
        RED: {piece: [] for piece in _PIECE_TO_CHAR},
        BLACK: {piece: [] for piece in _PIECE_TO_CHAR},
    }
    for row_index, row in enumerate(rows):
        rank = 9 - row_index
        file = 0
        for char in row:
            if char.isdigit():
                file += int(char)
                continue
            piece = _CHAR_TO_PIECE.get(char.lower())
            if piece is None or file >= 9:
                raise ValueError(f"invalid Xiangqi FEN rank: {row!r}")
            side = RED if char.isupper() else BLACK
            positions[side][piece].append(file * BOARD_STRIDE + rank)
            file += 1
        if file != 9:
            raise ValueError(f"Xiangqi FEN rank does not contain 9 files: {row!r}")

    board = Board.__new__(Board)
    board.cells = [0] * (BOARD_STRIDE * 11)
    board.pieces = [[-1] * 16, [-1] * 16]
    board.side_to_move = RED if active in ("w", "r") else BLACK
    board.move_history = []

    for side in (RED, BLACK):
        for piece, found in positions[side].items():
            slots = [index for index, slot_piece in enumerate(PIECE_TYPES) if slot_piece == piece]
            if len(found) > len(slots):
                raise ValueError(f"too many pieces of type {piece} for side {side}")
            # ROM PST values are attached to piece indices, so an arbitrary FEN
            # can have several internal encodings when identical pieces remain.
            # Pick the assignment with the smallest distance from the ROM's
            # initial piece slots; this is deterministic and preserves startpos.
            initial = Board().pieces[side]
            best_slots: tuple[int, ...] = ()
            best_positions: tuple[int, ...] = ()
            best_key: tuple[int, tuple[int, ...], tuple[int, ...]] | None = None
            for chosen_slots in permutations(slots, len(found)):
                for chosen_positions in permutations(found):
                    cost = sum(abs(initial[index] - pos)
                               for index, pos in zip(chosen_slots, chosen_positions))
                    key = (cost, chosen_slots, chosen_positions)
                    if best_key is None or key < best_key:
                        best_key = key
                        best_slots = chosen_slots
                        best_positions = chosen_positions
            for index, pos in zip(best_slots, best_positions):
                board.pieces[side][index] = pos
                board.cells[pos] = 0x10 + side * 0x10 + index
    return board
