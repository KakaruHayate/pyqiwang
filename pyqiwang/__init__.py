"""
pyqiwang — Chinese Chess AI Engine (100% ROM-faithful)

This package provides a clean Python API for the 棋王 FC chess AI.
The engine runs the ROM's native $8597 search subroutine through a
6502 CPU emulator, giving 100% move fidelity.
"""

from pyqiwang._engine import QiWangEngine  # noqa: F401
from pyqiwang._board import (              # noqa: F401
    Board,
    RED, BLACK,
    EMPTY, KING, ADVISOR, ELEPHANT, ROOK, KNIGHT, CANNON, PAWN,
    PIECE_TYPES, PIECE_NAMES, PIECE_NAMES_BLACK,
    generate_legal_moves, generate_moves, is_in_check, evaluate,
    pos_to_notation, notation_to_pos,
    BOARD_STRIDE,
)

__version__ = "1.0.0"
__all__ = [
    "QiWangEngine",
    "Board",
    "RED", "BLACK",
    "EMPTY", "KING", "ADVISOR", "ELEPHANT",
    "ROOK", "KNIGHT", "CANNON", "PAWN",
    "PIECE_TYPES", "PIECE_NAMES", "PIECE_NAMES_BLACK",
    "generate_legal_moves", "generate_moves", "is_in_check", "evaluate",
    "pos_to_notation", "notation_to_pos",
    "BOARD_STRIDE",
]
