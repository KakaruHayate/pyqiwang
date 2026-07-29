"""Read a user-supplied ElephantEye ``BOOK.DAT`` opening book.

ElephantEye and its book tools are Copyright (C) 2004-2011 xqbase.com and
licensed under LGPL-2.1-or-later. This module is an independent Python adapter
for the documented 8-byte ``<IHH`` record format; no book data is bundled.
"""
from __future__ import annotations

import bisect
import struct
from pathlib import Path

from pyqiwang._board import (
    ADVISOR,
    BLACK,
    CANNON,
    ELEPHANT,
    KING,
    KNIGHT,
    PAWN,
    PIECE_TYPES,
    RED,
    ROOK,
    Board,
    generate_legal_moves,
)

_RECORD = struct.Struct("<IHH")
_TYPE = {
    KING: 0,
    ADVISOR: 1,
    ELEPHANT: 2,
    KNIGHT: 3,
    ROOK: 4,
    CANNON: 5,
    PAWN: 6,
}


class _RC4:
    def __init__(self) -> None:
        self.s = list(range(256))
        self.x = self.y = 0
        j = 0
        key = (0, 0, 0, 0)
        for i in range(256):
            j = (j + self.s[i] + key[i & 3]) & 255
            self.s[i], self.s[j] = self.s[j], self.s[i]

    def byte(self) -> int:
        self.x = (self.x + 1) & 255
        self.y = (self.y + self.s[self.x]) & 255
        self.s[self.x], self.s[self.y] = self.s[self.y], self.s[self.x]
        return self.s[(self.s[self.x] + self.s[self.y]) & 255]

    def long(self) -> int:
        return sum(self.byte() << shift for shift in (0, 8, 16, 24))


def _zobrist_locks() -> tuple[int, list[list[int]]]:
    rc4 = _RC4()
    player = (rc4.long(), rc4.long(), rc4.long())[2]
    table = []
    for _ in range(14):
        row = []
        for _ in range(256):
            row.append((rc4.long(), rc4.long(), rc4.long())[2])
        table.append(row)
    return player, table


_PLAYER_LOCK, _LOCK_TABLE = _zobrist_locks()


def _elephant_square(pos: int, mirror: bool = False) -> int:
    file, rank = divmod(pos, 12)
    if mirror:
        file = 8 - file
    return (file + 3) + ((12 - rank) << 4)


def _pyqiwang_square(square: int, mirror: bool = False) -> int:
    file = (square & 15) - 3
    rank = 12 - (square >> 4)
    if mirror:
        file = 8 - file
    return file * 12 + rank


def elephant_lock(board: Board, mirror: bool = False) -> int:
    """Return ElephantEye's 32-bit ``dwLock1`` for a pyqiwang board."""
    lock = _PLAYER_LOCK if board.side_to_move == BLACK else 0
    for side in (RED, BLACK):
        type_offset = 0 if side == RED else 7
        for index, pos in enumerate(board.pieces[side]):
            if pos < 0:
                continue
            piece_type = _TYPE[PIECE_TYPES[index]] + type_offset
            lock ^= _LOCK_TABLE[piece_type][_elephant_square(pos, mirror)]
    return lock & 0xFFFFFFFF


def decode_move(encoded: int, mirror: bool = False) -> tuple[int, int]:
    source = encoded & 0xFF
    target = encoded >> 8
    return _pyqiwang_square(source, mirror), _pyqiwang_square(target, mirror)


class ElephantBook:
    """Memory-backed reader for ElephantEye's sorted binary opening book."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        data = self.path.read_bytes()
        if len(data) % _RECORD.size:
            raise ValueError("ElephantEye BOOK.DAT size is not a multiple of 8")
        records = [_RECORD.unpack_from(data, offset)
                   for offset in range(0, len(data), _RECORD.size)]
        self._locks = [record[0] for record in records]
        self._moves = [(record[1], record[2]) for record in records]
        if self._locks != sorted(self._locks):
            raise ValueError("ElephantEye BOOK.DAT records are not sorted")
        self.hits = 0
        self.misses = 0

    def candidates(self, board: Board) -> list[tuple[tuple[int, int], int]]:
        legal = set(generate_legal_moves(board, board.side_to_move))
        for mirrored in (False, True):
            lock = elephant_lock(board, mirrored)
            start = bisect.bisect_left(self._locks, lock)
            end = bisect.bisect_right(self._locks, lock)
            found = []
            for encoded, weight in self._moves[start:end]:
                move = decode_move(encoded, mirrored)
                if move in legal:
                    found.append((move, weight))
            if found:
                found.sort(key=lambda item: item[1], reverse=True)
                return found
        return []

    def lookup(self, board: Board) -> tuple[int, int] | None:
        found = self.candidates(board)
        if found:
            self.hits += 1
            return found[0][0]
        self.misses += 1
        return None

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {
            "records": len(self._locks),
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": self.hits / total if total else 0.0,
            "source": str(self.path),
        }
