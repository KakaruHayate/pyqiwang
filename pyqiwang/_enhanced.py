"""Enhanced Xiangqi search: iterative deepening PVS with a transposition table.

This is deliberately separate from :class:`QiWangEngine`: the latter remains
ROM-faithful, while this engine explores how much strength a conventional
search framework can add around the same board representation.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

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
    generate_moves,
    is_in_check,
)

MATE = 30000
INF = 32000
EXACT = 0
LOWER = 1
UPPER = 2

MATERIAL = {
    KING: 10000,
    ROOK: 500,
    CANNON: 250,
    KNIGHT: 250,
    ADVISOR: 100,
    ELEPHANT: 100,
    PAWN: 50,
}


@dataclass(slots=True)
class TTEntry:
    depth: int
    score: int
    flag: int
    move: tuple[int, int] | None


class SearchTimeout(Exception):
    pass


class EnhancedEngine:
    """Iterative-deepening PVS searcher with TT, killers and history.

    ``depth`` is a conventional ply depth, unlike the original ROM's root
    iteration parameter. ``time_limit=None`` performs a fixed-depth search.
    """

    name = "pyqiwang EnhancedEngine (PVS+TT)"

    def __init__(self, depth: int = 8, time_limit: float | None = None,
                 tt_size: int = 500_000) -> None:
        self.depth = max(1, int(depth))
        self.time_limit = time_limit
        self.tt_size = max(1_000, int(tt_size))
        self.tt: dict[tuple, TTEntry] = {}
        self.killers: dict[int, list[tuple[int, int]]] = {}
        self.history: dict[tuple[int, int, int], int] = {}
        self.nodes = 0
        self.qnodes = 0
        self.tt_hits = 0
        self.tt_cutoffs = 0
        self.beta_cutoffs = 0
        self.last_score = 0
        self.last_depth = 0
        self.last_pv: list[tuple[int, int]] = []
        self.last_elapsed = 0.0
        self._deadline: float | None = None

    @staticmethod
    def _key(board: Board, side: int) -> tuple:
        return (tuple(board.pieces[RED]), tuple(board.pieces[BLACK]), side)

    @staticmethod
    def _king_alive(board: Board, side: int) -> bool:
        return board.pieces[side][0] >= 0

    @staticmethod
    def _evaluate(board: Board, side: int) -> int:
        score = 0
        for current in (RED, BLACK):
            sign = 1 if current == side else -1
            for index, pos in enumerate(board.pieces[current]):
                if pos < 0:
                    continue
                piece = PIECE_TYPES[index]
                value = MATERIAL[piece]
                file, rank = divmod(pos, 12)
                forward = rank if current == RED else 9 - rank
                if piece == PAWN:
                    value += forward * 5
                    if forward >= 5:
                        value += 18 + (4 - abs(file - 4)) * 2
                elif piece in (KNIGHT, CANNON, ROOK):
                    value += 4 - abs(file - 4)
                score += sign * value
        return score

    def _check_time(self) -> None:
        if self._deadline is not None and time.perf_counter() >= self._deadline:
            raise SearchTimeout

    @staticmethod
    def _piece_value(board: Board, pos: int) -> int:
        value = board.cells[pos]
        return MATERIAL[PIECE_TYPES[value & 0x0F]] if value else 0

    def _ordered(self, board: Board, moves: list[tuple[int, int]], side: int,
                 ply: int, tt_move: tuple[int, int] | None) -> list[tuple[int, int]]:
        killers = self.killers.get(ply, ())

        def priority(move: tuple[int, int]) -> int:
            frm, to = move
            if move == tt_move:
                return 1 << 30
            victim = board.cells[to]
            if victim:
                return (1 << 25) + self._piece_value(board, to) * 32 - self._piece_value(board, frm)
            if move in killers:
                return (1 << 22) - killers.index(move)
            return self.history.get((side, frm, to), 0)

        return sorted(moves, key=priority, reverse=True)

    @staticmethod
    def _legal_after_make(board: Board, side: int) -> bool:
        return not is_in_check(board, side)

    def _store(self, key: tuple, entry: TTEntry) -> None:
        old = self.tt.get(key)
        if old is None and len(self.tt) >= self.tt_size:
            self.tt.clear()
        if old is None or entry.depth >= old.depth:
            self.tt[key] = entry

    def _quiesce(self, board: Board, side: int, alpha: int, beta: int,
                 ply: int) -> int:
        self.qnodes += 1
        if (self.qnodes & 1023) == 0:
            self._check_time()
        if not self._king_alive(board, side):
            return -MATE + ply
        if not self._king_alive(board, 1 - side):
            return MATE - ply

        checked = is_in_check(board, side)
        stand = self._evaluate(board, side)
        if not checked:
            if stand >= beta:
                return stand
            if stand > alpha:
                alpha = stand
        if ply >= 32:
            return alpha if not checked else stand

        moves = generate_moves(board, side)
        if not checked:
            moves = [move for move in moves if board.cells[move[1]]]
        legal = 0
        for frm, to in self._ordered(board, moves, side, ply, None):
            board.make_move(frm, to)
            if not self._legal_after_make(board, side):
                board.undo_move()
                continue
            legal += 1
            score = -self._quiesce(board, 1 - side, -beta, -alpha, ply + 1)
            board.undo_move()
            if score >= beta:
                return score
            if score > alpha:
                alpha = score
        if checked and legal == 0:
            return -MATE + ply
        return alpha

    def _pvs(self, board: Board, side: int, depth: int, alpha: int,
             beta: int, ply: int) -> int:
        self.nodes += 1
        if (self.nodes & 1023) == 0:
            self._check_time()
        if not self._king_alive(board, side):
            return -MATE + ply
        if not self._king_alive(board, 1 - side):
            return MATE - ply
        if depth <= 0:
            return self._quiesce(board, side, alpha, beta, ply)

        alpha_original = alpha
        key = self._key(board, side)
        entry = self.tt.get(key)
        tt_move = entry.move if entry else None
        if entry and entry.depth >= depth:
            self.tt_hits += 1
            if entry.flag == EXACT:
                return entry.score
            if entry.flag == LOWER:
                alpha = max(alpha, entry.score)
            elif entry.flag == UPPER:
                beta = min(beta, entry.score)
            if alpha >= beta:
                self.tt_cutoffs += 1
                return entry.score

        best = -INF
        best_move = None
        legal = 0
        for frm, to in self._ordered(board, generate_moves(board, side), side, ply, tt_move):
            captured = board.cells[to]
            board.make_move(frm, to)
            if not self._legal_after_make(board, side):
                board.undo_move()
                continue
            legal += 1
            if legal == 1:
                score = -self._pvs(board, 1 - side, depth - 1, -beta, -alpha, ply + 1)
            else:
                score = -self._pvs(board, 1 - side, depth - 1, -alpha - 1, -alpha, ply + 1)
                if alpha < score < beta:
                    score = -self._pvs(board, 1 - side, depth - 1, -beta, -alpha, ply + 1)
            board.undo_move()

            if score > best:
                best, best_move = score, (frm, to)
            if score > alpha:
                alpha = score
            if alpha >= beta:
                self.beta_cutoffs += 1
                if not captured:
                    killer_list = self.killers.setdefault(ply, [])
                    move = (frm, to)
                    if move not in killer_list:
                        killer_list.insert(0, move)
                        del killer_list[2:]
                    history_key = (side, frm, to)
                    self.history[history_key] = self.history.get(history_key, 0) + depth * depth
                break

        if legal == 0:
            return -MATE + ply
        flag = UPPER if best <= alpha_original else (LOWER if best >= beta else EXACT)
        self._store(key, TTEntry(depth, best, flag, best_move))
        return best

    def _root(self, board: Board, side: int, depth: int,
              preferred: tuple[int, int] | None) -> tuple[int, tuple[int, int] | None]:
        alpha, beta = -INF, INF
        best_score, best_move = -INF, None
        legal = 0
        for frm, to in self._ordered(board, generate_moves(board, side), side, 0, preferred):
            board.make_move(frm, to)
            if not self._legal_after_make(board, side):
                board.undo_move()
                continue
            legal += 1
            if legal == 1:
                score = -self._pvs(board, 1 - side, depth - 1, -beta, -alpha, 1)
            else:
                score = -self._pvs(board, 1 - side, depth - 1, -alpha - 1, -alpha, 1)
                if alpha < score < beta:
                    score = -self._pvs(board, 1 - side, depth - 1, -beta, -alpha, 1)
            board.undo_move()
            if score > best_score:
                best_score, best_move = score, (frm, to)
            if score > alpha:
                alpha = score
        return (best_score, best_move) if legal else (-MATE, None)

    def _extract_pv(self, board: Board, side: int, limit: int) -> list[tuple[int, int]]:
        work = board.clone()
        pv = []
        for _ in range(limit):
            entry = self.tt.get(self._key(work, side))
            if entry is None or entry.move is None:
                break
            move = entry.move
            work.make_move(*move)
            if is_in_check(work, side):
                break
            pv.append(move)
            side = 1 - side
        return pv

    def search(self, board: Board, side: int | None = None) -> tuple[int, int] | None:
        if side is None:
            side = board.side_to_move
        work = board.clone()
        work.move_history = []
        started = time.perf_counter()
        self._deadline = None if self.time_limit is None else started + self.time_limit
        self.nodes = self.qnodes = self.tt_hits = self.tt_cutoffs = self.beta_cutoffs = 0
        self.killers.clear()
        root_legal = []
        for move in generate_moves(work, side):
            work.make_move(*move)
            if self._legal_after_make(work, side):
                root_legal.append(move)
            work.undo_move()
        best_move = root_legal[0] if root_legal else None
        completed_score = self._evaluate(work, side) if best_move else -MATE
        completed_depth = 0

        for current_depth in range(1, self.depth + 1):
            try:
                score, move = self._root(work, side, current_depth, best_move)
                self._check_time()
            except SearchTimeout:
                break
            if move is None:
                best_move = None
                completed_score = score
                completed_depth = current_depth
                break
            best_move = move
            completed_score = score
            completed_depth = current_depth
            if abs(score) >= MATE - 128:
                break

        self.last_score = completed_score
        self.last_depth = completed_depth
        self.last_elapsed = time.perf_counter() - started
        self.last_pv = self._extract_pv(work, side, completed_depth)
        return best_move

    def stats(self) -> dict:
        total = self.nodes + self.qnodes
        return {
            "depth": self.last_depth,
            "score": self.last_score,
            "nodes": self.nodes,
            "qnodes": self.qnodes,
            "total_nodes": total,
            "elapsed": self.last_elapsed,
            "nps": int(total / self.last_elapsed) if self.last_elapsed else 0,
            "tt_entries": len(self.tt),
            "tt_hits": self.tt_hits,
            "tt_cutoffs": self.tt_cutoffs,
            "beta_cutoffs": self.beta_cutoffs,
            "pv": list(self.last_pv),
        }
