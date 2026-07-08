"""
pyqiwang._engine — QiWangEngine: high-level API for the ROM chess AI.

Usage:
    from pyqiwang import QiWangEngine, Board

    engine = QiWangEngine(depth=2)
    board = Board()

    best = engine.get_best_move(board)
    # (from_pos, to_pos) or None

    info = engine.analyze(board)
    # { 'move': (frm, to), 'score': int, 'depth': int, 'elapsed': float }
"""

from __future__ import annotations

import os
import time
from typing import Optional

from pyqiwang._board import (
    Board, RED, BLACK, EMPTY, PIECE_TYPES,
    generate_legal_moves, evaluate, pos_to_notation, notation_to_pos,
    BOARD_STRIDE,
)

# Deferred imports to avoid circular refs
from pyqiwang._mos6502 import MOS6502, CPUError  # noqa: E402
from pyqiwang._harness import RomHarness         # noqa: E402


class QiWangEngineError(Exception):
    """Raised when the engine encounters an error."""
    pass


class QiWangEngine:
    """Chinese Chess AI engine based on the 棋王 FC ROM.

    Runs the ROM's native $8597 search subroutine through a 6502 CPU
    emulator, providing **100% move fidelity** with the original game.

    The engine holds a ROM-internal state. Call ``make_move()`` to advance
    the ROM state after each move (alternatively, call ``reset()`` to
    restore the initial position and sync from scratch).

    Args:
        rom_path: Path to the 棋王 ROM .nes file. If None, uses the
            default location next to this module.
        depth: Search depth. Default 2 (beginner). Valid range 1-12.
            In the original ROM: 2=beginner, 3=intermediate, 4=advanced.

    Example:
        >>> engine = QiWangEngine(depth=3)
        >>> board = Board()
        >>> move = engine.get_best_move(board)
        >>> engine.make_move(board, *move)
    """

    def __init__(self, rom_path: Optional[str] = None, depth: int = 2):
        if rom_path is None:
            rom_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                '..',
                '棋王(繁)[小天才](CN)[TAB](0.75Mb).nes',
            )
        if not os.path.exists(rom_path):
            raise QiWangEngineError(
                f"ROM file not found: {rom_path}\n"
                "Download 棋王(繁)[小天才](CN)[TAB](0.75Mb).nes and "
                "place it next to the package."
            )

        self._depth = max(1, min(depth, 12))
        self._rom_path = rom_path
        self._board = Board()  # Python-side canonical board
        self._init_rom()
        self._move_count = 0

    # ── Internal: ROM state management ─────────────────────

    def _init_rom(self) -> None:
        """Bootstrap the 6502 emulator + ROM."""
        self.harness = RomHarness(self._rom_path)
        self.harness.boot()
        self.harness.init_board()
        self.harness.new_game(side_to_move=0x10, book=False)

    def _reset_board(self) -> None:
        """Reset both Python and ROM boards to initial position."""
        self._board = Board()
        self._move_count = 0
        self.harness.new_game(side_to_move=0x10, book=False)

    def _sync_board_to_rom(self, board: Board) -> None:
        """Write Python board state to ROM RAM ($00-$83, $94-$B3, $C7)."""
        h = self.harness
        # Clear board cells $00-$83 first (avoid stale pieces)
        for a in range(0x84):
            h.wr(a, 0x00)
        for idx in range(16):
            rp = board.pieces[RED][idx]
            bp = board.pieces[BLACK][idx]
            if rp >= 0:
                h.wr(0x94 + idx, rp)
                h.wr(rp, 0x10 + idx)
            else:
                h.wr(0x94 + idx, 0xFF)
            if bp >= 0:
                h.wr(0xA4 + idx, bp)
                h.wr(bp, 0x20 + idx)
            else:
                h.wr(0xA4 + idx, 0xFF)
        h.wr(0xC7, 0x10 if board.side_to_move == RED else 0x20)

    def _sync_rom_to_board(self, board: Board) -> None:
        """Read ROM RAM ($94-$B3, $C7) into Python board."""
        board.cells = [0] * len(board.cells)
        board.pieces[RED] = [-1] * 16
        board.pieces[BLACK] = [-1] * 16
        board.move_history = []

        for idx in range(16):
            rp = self.harness.rd(0x94 + idx)
            bp = self.harness.rd(0xA4 + idx)
            if rp < 0x84:
                board.pieces[RED][idx] = rp
                board.cells[rp] = 0x10 + idx
            if bp < 0x84:
                board.pieces[BLACK][idx] = bp
                board.cells[bp] = 0x20 + idx

        c7 = self.harness.rd(0xC7)
        board.side_to_move = RED if (c7 & 0x10) else BLACK

    # ── Public API ─────────────────────────────────────────

    @property
    def depth(self) -> int:
        """Current search depth (1-12)."""
        return self._depth

    @depth.setter
    def depth(self, value: int) -> None:
        self._depth = max(1, min(int(value), 12))

    def reset(self) -> None:
        """Reset the engine to the initial position.

        After calling this, the engine is in the starting position
        with Red to move.
        """
        self._reset_board()

    def get_side_to_move(self) -> int:
        """Return the side that should move next (RED=0, BLACK=1)."""
        return self._board.side_to_move

    def get_best_move(self, board: Optional[Board] = None) -> Optional[tuple[int, int]]:
        """Find the best move for the current side to move.

        Args:
            board: Board to analyze. If None, uses internal board state.

        Returns:
            (from_pos, to_pos) or None if no legal move exists.
            Positions are encoded as: pos = file * 12 + rank.

        Example:
            >>> engine = QiWangEngine(depth=2)
            >>> board = Board()
            >>> move = engine.get_best_move(board)
            >>> print(pos_to_notation(move[0]), '->', pos_to_notation(move[1]))
        """
        if board is None:
            board = self._board

        # Sync board to ROM, then run search
        self._sync_board_to_rom(board)
        side_flag = 0x10 if board.side_to_move == RED else 0x00
        self.harness.wr(0xC7, side_flag)

        move = self.harness.get_ai_move(self._depth)

        # Sanity check
        if move is not None:
            legal = generate_legal_moves(board, board.side_to_move)
            if move not in legal:
                raise QiWangEngineError(
                    f"ROM returned illegal move {move}. "
                    f"Legal moves: {legal}"
                )
        return move

    def make_move(self, board: Optional[Board] = None,
                  frm: int = -1, to: int = -1) -> bool:
        """Execute a move in the ROM engine state.

        This is the recommended way to advance the game — it keeps
        the ROM's internal state consistent.

        Args:
            board: Python Board to sync from (and back to). If None,
                uses internal board.
            frm: Source position (file*12 + rank).
            to:   Destination position (file*12 + rank).

        Returns:
            True if the move was executed successfully.
        """
        if board is None:
            board = self._board

        self._sync_board_to_rom(board)
        ok = self.harness.exec_move(frm, to)
        if ok:
            self._sync_rom_to_board(board)
            self._move_count += 1
        return ok

    def analyze(self, board: Optional[Board] = None) -> dict:
        """Run a full search and return detailed information.

        Args:
            board: Board to analyze. If None, uses internal board.

        Returns:
            Dictionary with keys:
                - move: (from_pos, to_pos) or None
                - score: evaluation (positive = good for side to move)
                - depth: search depth used
                - elapsed: seconds spent searching
                - legal_moves: number of legal moves found
                - board_synced: whether board was synced to ROM
        """
        t0 = time.time()
        move = self.get_best_move(board)
        elapsed = time.time() - t0
        side = board.side_to_move if board else self._board.side_to_move
        score = self.evaluate(board) if move else 0
        legal = generate_legal_moves(board, side) if board else []

        return {
            'move': move,
            'score': score,
            'depth': self._depth,
            'elapsed': elapsed,
            'legal_moves': len(legal),
            'side': 'RED' if side == RED else 'BLACK',
        }

    def evaluate(self, board: Optional[Board] = None) -> int:
        """Evaluate a position from the perspective of the side to move.

        Uses the ROM-extracted PST tables (ROM $8886).
        Positive = advantage for side to move.

        Args:
            board: Board to evaluate. If None, uses internal board.
        """
        if board is None:
            board = self._board
        return evaluate(board, board.side_to_move)

    def get_legal_moves(self, board: Optional[Board] = None) -> list[tuple[int, int]]:
        """Return all legal moves for the current side.

        Args:
            board: Board to get moves from. If None, uses internal board.
        """
        if board is None:
            board = self._board
        return generate_legal_moves(board, board.side_to_move)

    def get_rom_state(self) -> dict:
        """Return raw ROM state for debugging/inspection.

        Returns dict with keys: pieces_red, pieces_black, side_flag,
        c7, move_count.
        """
        return {
            'pieces_red':  [self.harness.rd(0x94 + i) for i in range(16)],
            'pieces_black': [self.harness.rd(0xA4 + i) for i in range(16)],
            'side_flag':   self.harness.rd(0xC7),
            'move_count':  self._move_count,
        }

    # ── Iteration helpers (for training / distillation) ────

    def play_auto(self, max_moves: int = 200, verbose: bool = True) -> str:
        """Auto-play a game (both sides = AI) for up to max_moves.

        Returns a result string: 'Red wins', 'Black wins', or 'Draw'.
        """
        board = Board()
        result = 'Draw'

        for step in range(max_moves):
            side_name = 'RED' if board.side_to_move == RED else 'BLACK'
            move = self.get_best_move(board)

            if move is None:
                legal = generate_legal_moves(board, board.side_to_move)
                if not legal:
                    result = 'Black wins' if board.side_to_move == RED else 'Red wins'
                break

            if verbose:
                print(f"Step {step:2d} {side_name}: "
                      f"{pos_to_notation(move[0])} -> {pos_to_notation(move[1])}")

            board.make_move(*move)
            self._sync_board_to_rom(board)
            side_flag = 0x10 if board.side_to_move == RED else 0x00
            self.harness.wr(0xC7, side_flag)
            self._move_count += 1

            legal2 = generate_legal_moves(board, board.side_to_move)
            if not legal2:
                result = 'Red wins' if board.side_to_move == BLACK else 'Black wins'
                break

        if verbose:
            print(f"\nResult: {result} ({step+1} moves)")
        return result
