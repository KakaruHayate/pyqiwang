"""ctypes adapter for the optional Rust EnhancedEngine search core."""
from __future__ import annotations

import ctypes
from pathlib import Path
from typing import Any

from pyqiwang._board import Board, RED, BLACK, generate_legal_moves


class EnhancedFastError(RuntimeError):
    pass


class _Result(ctypes.Structure):
    _fields_ = [
        ("move_code", ctypes.c_uint16),
        ("score", ctypes.c_int32),
        ("depth", ctypes.c_uint32),
        ("nodes", ctypes.c_uint64),
        ("qnodes", ctypes.c_uint64),
        ("tt_hits", ctypes.c_uint64),
        ("tt_cutoffs", ctypes.c_uint64),
        ("beta_cutoffs", ctypes.c_uint64),
        ("tt_entries", ctypes.c_uint64),
        ("elapsed_ms", ctypes.c_uint64),
    ]


def find_library() -> Path | None:
    root = Path(__file__).resolve().parent.parent
    name = "pyqiwang_enhanced_search.dll"
    candidates = [
        root / "pyqiwang" / name,
        root / "rust" / "enhanced_search" / "target" / "release" / name,
    ]
    return next((p for p in candidates if p.is_file()), None)


class FastEnhancedEngine:
    """Run the same Board state through the compiled PVS implementation."""

    name = "pyqiwang EnhancedEngine (Rust PVS+TT)"

    def __init__(self, depth: int = 8, time_limit: float | None = None,
                 tt_size: int = 500_000) -> None:
        path = find_library()
        if path is None:
            raise EnhancedFastError(
                "enhanced Rust library not found; build rust/enhanced_search"
            )
        self.depth = max(1, int(depth))
        self.time_limit = time_limit
        self.tt_size = max(1_000, int(tt_size))
        self._lib = ctypes.CDLL(str(path))
        fn = self._lib.qiwang_enhanced_search
        fn.argtypes = [
            ctypes.POINTER(ctypes.c_uint8), ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_uint8, ctypes.c_uint32, ctypes.c_uint64, ctypes.c_uint64,
            ctypes.POINTER(_Result),
        ]
        fn.restype = ctypes.c_int32
        self._search = fn
        self.last_score = 0
        self.last_depth = 0
        self.last_elapsed = 0.0
        self.nodes = 0
        self.qnodes = 0
        self.tt_hits = 0
        self.tt_cutoffs = 0
        self.beta_cutoffs = 0
        self.tt_entries = 0

    def search(self, board: Board, side: int | None = None) -> tuple[int, int] | None:
        if side is None:
            side = board.side_to_move
        cells = (ctypes.c_uint8 * len(board.cells))(*board.cells)
        pieces_data = board.pieces[RED] + board.pieces[BLACK]
        pieces = (ctypes.c_uint8 * len(pieces_data))(*[(p if p >= 0 else 0xFF) for p in pieces_data])
        result = _Result()
        time_ms = 0 if self.time_limit is None else max(1, int(self.time_limit * 1000))
        code = self._search(cells, pieces, side, self.depth, time_ms, self.tt_size, ctypes.byref(result))
        if code != 0:
            raise EnhancedFastError(f"Rust enhanced search failed: {code}")
        self.last_score = result.score
        self.last_depth = result.depth
        self.last_elapsed = result.elapsed_ms / 1000.0
        self.nodes = result.nodes
        self.qnodes = result.qnodes
        self.tt_hits = result.tt_hits
        self.tt_cutoffs = result.tt_cutoffs
        self.beta_cutoffs = result.beta_cutoffs
        self.tt_entries = result.tt_entries
        if result.move_code == 0xFFFF:
            legal = generate_legal_moves(board, side)
            return legal[0] if legal and result.depth == 0 else None
        return result.move_code >> 8, result.move_code & 0xFF

    def stats(self) -> dict[str, Any]:
        total = self.nodes + self.qnodes
        return {
            "depth": self.last_depth,
            "score": self.last_score,
            "nodes": self.nodes,
            "qnodes": self.qnodes,
            "total_nodes": total,
            "elapsed": self.last_elapsed,
            "nps": int(total / self.last_elapsed) if self.last_elapsed else 0,
            "tt_entries": self.tt_entries,
            "tt_hits": self.tt_hits,
            "tt_cutoffs": self.tt_cutoffs,
            "beta_cutoffs": self.beta_cutoffs,
        }
