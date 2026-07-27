"""pyqiwang — FC QiWang Chinese Chess AI research engine.

Two implementation paths are available:

* ``QiWangEngine`` preserves the original ROM-backed, move-faithful path.
* ``NativeQiWangEngine`` is the ROM-free pure-Python reimplementation path.
"""

from pyqiwang._engine import QiWangEngine  # noqa: F401
from pyqiwang._native import (             # noqa: F401
    NativeQiWangEngine,
    NativeQiWangEngineError,
)
from pyqiwang._board import (              # noqa: F401
    Board,
    RED, BLACK,
    EMPTY, KING, ADVISOR, ELEPHANT, ROOK, KNIGHT, CANNON, PAWN,
    PIECE_TYPES, PIECE_NAMES, PIECE_NAMES_BLACK,
    generate_legal_moves, generate_moves, is_in_check, evaluate,
    pos_to_notation, notation_to_pos,
    BOARD_STRIDE,
)

__version__ = "1.1.0"
__all__ = [
    "QiWangEngine", "NativeQiWangEngine", "NativeQiWangEngineError",
    "Board",
    "RED", "BLACK",
    "EMPTY", "KING", "ADVISOR", "ELEPHANT",
    "ROOK", "KNIGHT", "CANNON", "PAWN",
    "PIECE_TYPES", "PIECE_NAMES", "PIECE_NAMES_BLACK",
    "generate_legal_moves", "generate_moves", "is_in_check", "evaluate",
    "pos_to_notation", "notation_to_pos",
    "BOARD_STRIDE",
]
