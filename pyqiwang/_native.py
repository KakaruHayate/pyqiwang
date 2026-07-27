"""Pure-Python implementation path for pyqiwang.

This module deliberately does not import the ROM harness or the 6502 emulator.
It is the starting point for a native reimplementation of the FC QiWang AI.
The current search is a deterministic alpha-beta reference search using the
ROM-extracted PST evaluation. It is not yet claimed to reproduce every ROM
search decision; fidelity will be added incrementally against the preserved
ROM implementation.
"""
from __future__ import annotations

import time
from typing import Optional

from pyqiwang._book import SequentialOpeningBook
from pyqiwang._board import (
    KING,
    PIECE_TYPES,
    RED,
    Board,
    evaluate,
    generate_moves,
    generate_legal_moves,
    is_in_check,
    pos_to_notation,
)

Move = tuple[int, int]
MATE_SCORE = 30000
INFINITY = 32767
KING_INDEX = PIECE_TYPES.index(KING)
TT_EXACT = 0
TT_LOWER = 1
TT_UPPER = 2
QUIESCENCE_MAX_PLY = 12


class _SearchStopped(Exception):
    """Internal control flow for time/node bounded searches."""


class NativeQiWangEngineError(Exception):
    """Raised when the pure-program engine receives an invalid operation."""


class NativeQiWangEngine:
    """ROM-free, pure-Python QiWang implementation path.

    The public methods intentionally mirror :class:`QiWangEngine` where that
    makes sense, so callers can switch implementations without changing their
    board-management code.

    This first implementation provides a deterministic fixed-depth alpha-beta
    search over the existing Python rules and ROM-extracted PST evaluation.
    It is a migration scaffold, not yet a claim of move-for-move ROM fidelity.
    """

    backend = "native"
    faithful = False

    def __init__(self, depth: int = 2, book: bool = False,
                 time_limit: float | None = None,
                 node_limit: int | None = None):
        self._depth = max(1, min(int(depth), 8))
        self._use_book = bool(book)
        self._book = SequentialOpeningBook() if self._use_book else None
        if time_limit is not None and time_limit <= 0:
            raise ValueError("time_limit must be positive")
        if node_limit is not None and node_limit <= 0:
            raise ValueError("node_limit must be positive")
        self.time_limit = time_limit
        self.node_limit = node_limit
        self._board = Board()
        self._move_count = 0
        self.nodes = 0
        self.last_score = 0
        self.last_depth = 0
        self.last_pv: list[Move] = []
        self.stopped = False
        self._deadline: float | None = None
        self._tt: dict[tuple, tuple[int, int, int, Move | None]] = {}

    @property
    def depth(self) -> int:
        return self._depth

    @depth.setter
    def depth(self, value: int) -> None:
        self._depth = max(1, min(int(value), 8))

    def reset(self) -> None:
        self._board = Board()
        self._move_count = 0
        self.nodes = 0
        self.last_score = 0
        self.last_depth = 0
        self.last_pv = []
        self.stopped = False
        self._tt.clear()

    def get_side_to_move(self) -> int:
        return self._board.side_to_move

    @staticmethod
    def _king_alive(board: Board, side: int) -> bool:
        return board.pieces[side][KING_INDEX] >= 0

    @staticmethod
    def _key(board: Board, side: int) -> tuple:
        return (tuple(board.pieces[0]), tuple(board.pieces[1]), side)

    def _visit(self) -> None:
        self.nodes += 1
        if self.node_limit is not None and self.nodes >= self.node_limit:
            raise _SearchStopped
        if self._deadline is not None and time.perf_counter() >= self._deadline:
            raise _SearchStopped

    @staticmethod
    def _order_moves(moves: list[Move], preferred: Move | None) -> list[Move]:
        if preferred is None or preferred not in moves:
            return moves
        return [preferred] + [move for move in moves if move != preferred]

    def _quiesce(self, board: Board, side: int,
                 alpha: int, beta: int, ply: int) -> int:
        """Extend legal capture sequences before applying the PST score.

        ROM depth values control top-level iterations rather than a strict ply
        count. ROM traces also show that a horizon position under attack is
        scored normally unless a king has actually been captured: it does not
        switch to a complete check-evasion search or assign a mate score there.
        Capture quiescence remains an approximation of the ROM's selective
        node rules, but this terminal behavior is directly trace-backed.
        """
        self._visit()
        if not self._king_alive(board, side):
            return -MATE_SCORE + ply
        if not self._king_alive(board, 1 - side):
            return MATE_SCORE - ply

        stand = evaluate(board, side)
        if stand >= beta:
            return stand
        if stand > alpha:
            alpha = stand
        if ply >= QUIESCENCE_MAX_PLY:
            return alpha

        for frm, to in generate_moves(board, side):
            captured = board.cells[to]
            if not captured:
                continue
            board.make_move(frm, to)
            if is_in_check(board, side):
                board.undo_move()
                continue
            try:
                score = -self._quiesce(
                    board, 1 - side, -beta, -alpha, ply + 1
                )
            finally:
                board.undo_move()
            if score >= beta:
                return score
            if score > alpha:
                alpha = score
        return alpha

    def _search(self, board: Board, side: int, depth: int,
                alpha: int, beta: int, ply: int) -> int:
        self._visit()

        if not self._king_alive(board, side):
            return -MATE_SCORE + ply
        if not self._king_alive(board, 1 - side):
            return MATE_SCORE - ply
        if depth <= 0:
            return self._quiesce(board, side, alpha, beta, ply)

        alpha_original = alpha
        key = self._key(board, side)
        preferred = None
        hit = self._tt.get(key)
        if hit is not None:
            hit_depth, hit_score, hit_flag, preferred = hit
            if hit_depth >= depth:
                if hit_flag == TT_EXACT:
                    return hit_score
                if hit_flag == TT_LOWER:
                    alpha = max(alpha, hit_score)
                elif hit_flag == TT_UPPER:
                    beta = min(beta, hit_score)
                if alpha >= beta:
                    return hit_score

        found = False
        best = -INFINITY
        best_move = None
        moves = self._order_moves(generate_moves(board, side), preferred)
        for frm, to in moves:
            board.make_move(frm, to)
            if is_in_check(board, side):
                board.undo_move()
                continue
            found = True
            try:
                score = -self._search(
                    board, 1 - side, depth - 1, -beta, -alpha, ply + 1
                )
            finally:
                board.undo_move()

            if score > best:
                best = score
                best_move = (frm, to)
            if score > alpha:
                alpha = score
            if alpha >= beta:
                break

        if not found:
            return -MATE_SCORE + ply
        flag = (TT_UPPER if best <= alpha_original else
                TT_LOWER if best >= beta else TT_EXACT)
        self._tt[key] = (depth, best, flag, best_move)
        return best

    def _root_search(self, work: Board, side: int, legal: list[Move],
                     depth: int, preferred: Move | None) -> tuple[Move, int]:
        best_move = legal[0]
        best_score = -INFINITY
        alpha = -INFINITY
        beta = INFINITY
        for frm, to in self._order_moves(legal, preferred):
            work.make_move(frm, to)
            try:
                score = -self._search(
                    work, 1 - side, depth - 1, -beta, -alpha, 1
                )
            finally:
                work.undo_move()
            if score > best_score:
                best_score = score
                best_move = (frm, to)
            if score > alpha:
                alpha = score
        return best_move, best_score

    def _principal_variation_after_root(self, board: Board, root: Move,
                                        depth: int) -> list[Move]:
        work = board.clone()
        work.move_history = []
        work.make_move(*root)
        pv: list[Move] = []
        for _ in range(depth):
            hit = self._tt.get(self._key(work, work.side_to_move))
            if hit is None or hit[3] is None:
                break
            move = hit[3]
            if move not in generate_legal_moves(work, work.side_to_move):
                break
            pv.append(move)
            work.make_move(*move)
        return pv

    def get_best_move(self, board: Optional[Board] = None) -> Optional[Move]:
        if board is None:
            board = self._board

        side = board.side_to_move
        if self._book is not None:
            book_move = self._book.probe(board)
            if book_move is not None:
                self.nodes = 0
                self.last_score = evaluate(board, side)
                self.last_depth = 0
                self.last_pv = [book_move]
                self.stopped = False
                return book_move

        work = board.clone()
        work.move_history = []
        legal = generate_legal_moves(work, side)
        if not legal:
            self.nodes = 0
            self.last_score = -MATE_SCORE
            self.last_depth = 0
            self.last_pv = []
            self.stopped = False
            return None

        self.nodes = 0
        self.last_depth = 0
        self.last_pv = []
        self.stopped = False
        self._tt.clear()
        self._deadline = (time.perf_counter() + self.time_limit
                          if self.time_limit is not None else None)
        best_move = legal[0]
        best_score = -INFINITY

        # Iterative deepening is required for a practical depth-8 ceiling. A
        # bounded search always returns the last fully completed iteration.
        for current_depth in range(1, self._depth + 1):
            try:
                candidate, score = self._root_search(
                    work, side, legal, current_depth, best_move
                )
            except _SearchStopped:
                self.stopped = True
                break
            best_move, best_score = candidate, score
            self.last_depth = current_depth
            self.last_score = score
            self.last_pv = [best_move] + self._principal_variation_after_root(
                work, best_move, current_depth - 1
            )

        self._deadline = None
        if self.last_depth == 0:
            # The bound fired during the first iteration. Returning the stable
            # first legal move is safer than exposing a partially searched one.
            self.last_score = evaluate(board, side)
            self.last_pv = [best_move]
        return best_move

    def make_move(self, board: Optional[Board] = None,
                  frm: int = -1, to: int = -1) -> bool:
        if board is None:
            board = self._board
        if (frm, to) not in generate_legal_moves(board, board.side_to_move):
            return False
        board.make_move(frm, to)
        self._move_count += 1
        return True

    def evaluate(self, board: Optional[Board] = None) -> int:
        if board is None:
            board = self._board
        return evaluate(board, board.side_to_move)

    def get_legal_moves(self, board: Optional[Board] = None) -> list[Move]:
        if board is None:
            board = self._board
        return generate_legal_moves(board, board.side_to_move)

    def analyze(self, board: Optional[Board] = None) -> dict:
        if board is None:
            board = self._board
        side = board.side_to_move
        started = time.perf_counter()
        book_move = self._book.probe(board) if self._book is not None else None
        move = self.get_best_move(board)
        elapsed = time.perf_counter() - started
        return {
            "move": move,
            "score": self.last_score,
            "depth": self._depth,
            "completed_depth": self.last_depth,
            "elapsed": elapsed,
            "legal_moves": len(generate_legal_moves(board, side)),
            "side": "RED" if side == RED else "BLACK",
            "nodes": self.nodes,
            "backend": self.backend,
            "faithful": self.faithful,
            "from_book": book_move is not None,
            "stopped": self.stopped,
            "pv": list(self.last_pv),
        }

    def play_auto(self, max_moves: int = 200, verbose: bool = True) -> str:
        board = Board()
        result = "Draw"
        played = 0
        for step in range(max_moves):
            move = self.get_best_move(board)
            if move is None:
                result = "Black wins" if board.side_to_move == RED else "Red wins"
                break
            if verbose:
                side_name = "RED" if board.side_to_move == RED else "BLACK"
                print(
                    f"Step {step:2d} {side_name}: "
                    f"{pos_to_notation(move[0])} -> {pos_to_notation(move[1])}"
                )
            board.make_move(*move)
            self._move_count += 1
            played += 1
        if verbose:
            print(f"\nResult: {result} ({played} moves)")
        return result
