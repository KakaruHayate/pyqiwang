"""
modern_ai.py — a modern Xiangqi engine to play against the 棋王 ROM AI.

Two backends, same interface:

* ``ModernEngine``   — self-contained pure-Python search. Iterative deepening,
  alpha-beta with a transposition table, quiescence search, killer/history
  move ordering, MVV-LVA capture ordering and a material + piece-square
  evaluation. No dependencies, so this always works.
* ``PikafishEngine`` — drives an external Pikafish binary over UCI. Far
  stronger (NNUE), but needs the binary + network downloaded separately.

``get_engine()`` picks Pikafish when a binary is available and otherwise
falls back to the built-in engine.

Both expose::

    engine.search(board, side) -> (from_pos, to_pos) | None
    engine.name  -> str

using pyqiwang's board representation (pos = file * 12 + rank).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import Optional

from pyqiwang._board import (
    Board, RED, BLACK, PIECE_TYPES,
    KING, ADVISOR, ELEPHANT, ROOK, KNIGHT, CANNON, PAWN,
    generate_moves, generate_legal_moves, is_in_check,
    BOARD_STRIDE,
)

MATE = 30000
INF = 1 << 30


# ══════════════════════════════════════════════════════════════
#  Evaluation
# ══════════════════════════════════════════════════════════════

# Material values, in centipawns, using the conventional modern Xiangqi
# weighting (rook ≫ cannon ≈ knight ≫ advisor ≈ elephant > pawn).
MATERIAL = {
    KING: 6000, ROOK: 900, CANNON: 450, KNIGHT: 400,
    ADVISOR: 200, ELEPHANT: 200, PAWN: 100,
}


def _mk_pst(rows: list[list[int]]) -> list[int]:
    """Build a 12*11 position-indexed table from 10 rank-major rows.

    ``rows[0]`` is rank 0 (Red's back rank) and ``rows[9]`` is rank 9.
    Each row lists 9 files, a→i.
    """
    tbl = [0] * (BOARD_STRIDE * 11)
    for rank, row in enumerate(rows):
        for file, v in enumerate(row):
            tbl[file * BOARD_STRIDE + rank] = v
    return tbl


# Piece-square tables from Red's point of view (rank 0 = Red's own back rank).
_PAWN_ROWS = [
    [0,  0,  0,  0,  0,  0,  0,  0,  0],
    [0,  0,  0,  0,  0,  0,  0,  0,  0],
    [0,  0,  0,  0,  0,  0,  0,  0,  0],
    [6,  0,  8,  0, 10,  0,  8,  0,  6],
    [10, 0, 14,  0, 18,  0, 14,  0, 10],
    [26, 30, 38, 46, 50, 46, 38, 30, 26],
    [42, 50, 62, 74, 80, 74, 62, 50, 42],
    [56, 66, 78, 90, 96, 90, 78, 66, 56],
    [64, 74, 86, 96, 100, 96, 86, 74, 64],
    [60, 70, 80, 90, 94, 90, 80, 70, 60],
]
_ROOK_ROWS = [
    [-2,  10,  6, 14, 12, 14,  6, 10, -2],
    [ 8,   4,  8, 16,  8, 16,  8,  4,  8],
    [ 4,   8,  6, 14, 12, 14,  6,  8,  4],
    [ 6,  10,  8, 14, 14, 14,  8, 10,  6],
    [12,  16, 14, 20, 20, 20, 14, 16, 12],
    [12,  14, 12, 18, 18, 18, 12, 14, 12],
    [12,  18, 16, 22, 22, 22, 16, 18, 12],
    [12,  12, 12, 18, 18, 18, 12, 12, 12],
    [16,  20, 18, 24, 26, 24, 18, 20, 16],
    [14,  14, 12, 18, 16, 18, 12, 14, 14],
]
_KNIGHT_ROWS = [
    [ 0, -4,  0,  0,  0,  0,  0, -4,  0],
    [ 0,  2,  4,  4, -2,  4,  4,  2,  0],
    [ 4,  2,  8,  8,  4,  8,  8,  2,  4],
    [ 2,  6,  8,  6, 10,  6,  8,  6,  2],
    [ 4, 12, 16, 14, 12, 14, 16, 12,  4],
    [ 6, 16, 14, 18, 16, 18, 14, 16,  6],
    [ 8, 24, 18, 24, 20, 24, 18, 24,  8],
    [12, 14, 16, 20, 18, 20, 16, 14, 12],
    [ 4, 10, 28, 16,  8, 16, 28, 10,  4],
    [ 4,  8, 16, 12,  4, 12, 16,  8,  4],
]
_CANNON_ROWS = [
    [0,  0,  2,  6,  6,  6,  2,  0,  0],
    [0,  2,  4,  6,  6,  6,  4,  2,  0],
    [4,  0,  8,  6, 10,  6,  8,  0,  4],
    [0,  0,  0,  2,  4,  2,  0,  0,  0],
    [0,  0,  0,  2,  4,  2,  0,  0,  0],
    [-2, 0,  4,  2,  6,  2,  4,  0, -2],
    [0,  0,  0,  2,  8,  2,  0,  0,  0],
    [4,  0, 10,  6, 10,  6, 10,  0,  4],
    [0,  2,  4,  6,  6,  6,  4,  2,  0],
    [0,  0,  2,  6,  6,  6,  2,  0,  0],
]
_ADVISOR_ROWS = [[0]*9 for _ in range(10)]
for _f, _r, _v in ((3, 0, 2), (5, 0, 2), (4, 1, 6), (3, 2, 2), (5, 2, 2)):
    _ADVISOR_ROWS[_r][_f] = _v
_ELEPHANT_ROWS = [[0]*9 for _ in range(10)]
for _f, _r, _v in ((2, 0, 4), (6, 0, 4), (0, 2, 2), (4, 2, 6), (8, 2, 2),
                   (2, 4, 4), (6, 4, 4)):
    _ELEPHANT_ROWS[_r][_f] = _v
_KING_ROWS = [[0]*9 for _ in range(10)]
for _f, _r, _v in ((3, 0, 8), (4, 0, 12), (5, 0, 8),
                   (3, 1, -4), (4, 1, -6), (5, 1, -4),
                   (3, 2, -10), (4, 2, -12), (5, 2, -10)):
    _KING_ROWS[_r][_f] = _v

_PST_RED = {
    PAWN: _mk_pst(_PAWN_ROWS), ROOK: _mk_pst(_ROOK_ROWS),
    KNIGHT: _mk_pst(_KNIGHT_ROWS), CANNON: _mk_pst(_CANNON_ROWS),
    ADVISOR: _mk_pst(_ADVISOR_ROWS), ELEPHANT: _mk_pst(_ELEPHANT_ROWS),
    KING: _mk_pst(_KING_ROWS),
}


def _mirror(tbl: list[int]) -> list[int]:
    """Flip a Red table vertically (rank r ↔ rank 9-r) for Black."""
    out = [0] * len(tbl)
    for file in range(9):
        for rank in range(10):
            out[file * BOARD_STRIDE + (9 - rank)] = tbl[file * BOARD_STRIDE + rank]
    return out


_PST_BLACK = {pt: _mirror(t) for pt, t in _PST_RED.items()}
_PST = {RED: _PST_RED, BLACK: _PST_BLACK}


def evaluate(board: Board, side: int) -> int:
    """Static evaluation in centipawns, positive = good for ``side``."""
    score = 0
    for s in (RED, BLACK):
        sign = 1 if s == side else -1
        pst = _PST[s]
        pieces = board.pieces[s]
        for idx in range(16):
            pos = pieces[idx]
            if pos < 0:
                continue
            pt = PIECE_TYPES[idx]
            score += sign * (MATERIAL[pt] + pst[pt][pos])
    return score


# ══════════════════════════════════════════════════════════════
#  Built-in modern search
# ══════════════════════════════════════════════════════════════

class ModernEngine:
    """Alpha-beta searcher with TT, quiescence, killers and history.

    Args:
        depth: nominal iterative-deepening ceiling.
        time_limit: soft wall-clock budget per move, in seconds. The search
            finishes the current iteration and then stops.
    """

    name = "ModernEngine (pure-Python alpha-beta)"

    def __init__(self, depth: int = 5, time_limit: float = 5.0):
        self.depth = depth
        self.time_limit = time_limit
        self.tt: dict[tuple, tuple] = {}
        self.killers: dict[int, list] = {}
        self.history: dict[tuple, int] = {}
        self.nodes = 0
        self.last_score = 0
        self.last_depth = 0
        self._deadline = 0.0

    # ── helpers ──────────────────────────────────────────────

    @staticmethod
    def _key(board: Board, side: int) -> tuple:
        return (tuple(board.pieces[RED]), tuple(board.pieces[BLACK]), side)

    @staticmethod
    def _ptype_at(board: Board, pos: int) -> int:
        val = board.cells[pos]
        return PIECE_TYPES[val & 0x0F] if val else 0

    def _order(self, board: Board, moves, side: int, ply: int, tt_move):
        """Sort moves best-first: TT move, then MVV-LVA captures, then
        killers, then history heuristic."""
        killers = self.killers.get(ply, ())

        def score(mv):
            frm, to = mv
            if mv == tt_move:
                return 1 << 24
            victim = board.cells[to]
            if victim:
                vt = PIECE_TYPES[victim & 0x0F]
                at = self._ptype_at(board, frm)
                return (1 << 20) + MATERIAL[vt] * 16 - MATERIAL[at]
            if mv in killers:
                return 1 << 18
            return self.history.get((side, frm, to), 0)

        return sorted(moves, key=score, reverse=True)

    @staticmethod
    def _king_alive(board: Board, side: int) -> bool:
        return board.pieces[side][PIECE_TYPES.index(KING)] >= 0

    def _see(self, board: Board, frm: int, to: int, side: int) -> int:
        """Static exchange evaluation for a capture on ``to``.

        Plays out the capture sequence on that square, always recapturing
        with the cheapest available attacker, and returns the net material
        swing for ``side``. Used to discard losing captures in quiescence,
        which otherwise happily grabs a defended piece and calls it profit.
        """
        gain = [MATERIAL[PIECE_TYPES[board.cells[to] & 0x0F]]]
        board.make_move(frm, to)
        stm = 1 - side
        try:
            depth = 0
            while depth < 24:
                caps = [(f, t) for (f, t) in generate_moves(board, stm)
                        if t == to]
                if not caps:
                    break
                # Recapture with the least valuable attacker.
                f, t = min(caps, key=lambda m: MATERIAL[
                    PIECE_TYPES[board.cells[m[0]] & 0x0F]])
                gain.append(MATERIAL[PIECE_TYPES[board.cells[t] & 0x0F]]
                            - gain[-1])
                board.make_move(f, t)
                depth += 1
                stm = 1 - stm
            for _ in range(depth):
                board.undo_move()
        finally:
            board.undo_move()

        # Negamax back up the swap list; either side may decline to recapture.
        for i in range(len(gain) - 1, 0, -1):
            gain[i - 1] = -max(-gain[i - 1], gain[i])
        return gain[0]

    def _timed_out(self) -> bool:
        return time.time() >= self._deadline

    # ── search ───────────────────────────────────────────────

    def _quiesce(self, board: Board, side: int, alpha: int, beta: int,
                 ply: int) -> int:
        """Search captures only, so the evaluation is never taken in the
        middle of an exchange."""
        self.nodes += 1
        stand = evaluate(board, side)
        if stand >= beta:
            return beta
        if stand > alpha:
            alpha = stand
        if ply > 12 or self._timed_out():
            return alpha

        caps = [(f, t) for (f, t) in generate_moves(board, side)
                if board.cells[t]]
        for frm, to in self._order(board, caps, side, ply, None):
            # Skip captures that lose material once the square is contested.
            # Without this the search will trade a cannon for a knight and
            # score it as a gain, because the recapture is past the horizon.
            if self._see(board, frm, to, side) < 0:
                continue
            board.make_move(frm, to)
            if is_in_check(board, side):
                board.undo_move()
                continue
            val = -self._quiesce(board, 1 - side, -beta, -alpha, ply + 1)
            board.undo_move()
            if val >= beta:
                return beta
            if val > alpha:
                alpha = val
        return alpha

    def _search(self, board: Board, side: int, depth: int,
                alpha: int, beta: int, ply: int) -> int:
        self.nodes += 1

        if not self._king_alive(board, side):
            return -MATE + ply
        if not self._king_alive(board, 1 - side):
            return MATE - ply

        alpha_orig = alpha
        key = self._key(board, side)
        tt_move = None
        hit = self.tt.get(key)
        if hit:
            tt_depth, tt_score, tt_flag, tt_move = hit
            if tt_depth >= depth:
                if tt_flag == 0:
                    return tt_score
                if tt_flag == 1 and tt_score > alpha:
                    alpha = tt_score
                elif tt_flag == 2 and tt_score < beta:
                    beta = tt_score
                if alpha >= beta:
                    return tt_score

        if depth <= 0:
            return self._quiesce(board, side, alpha, beta, ply)
        if self._timed_out():
            return evaluate(board, side)

        best = -INF
        best_move = None
        legal_count = 0

        for frm, to in self._order(board, generate_moves(board, side),
                                   side, ply, tt_move):
            board.make_move(frm, to)
            if is_in_check(board, side):
                board.undo_move()
                continue
            legal_count += 1
            captured = board.move_history[-1][3]
            val = -self._search(board, 1 - side, depth - 1,
                                -beta, -alpha, ply + 1)
            board.undo_move()

            if val > best:
                best, best_move = val, (frm, to)
            if val > alpha:
                alpha = val
            if alpha >= beta:
                if not captured:  # quiet move that caused a cutoff
                    ks = self.killers.setdefault(ply, [])
                    if (frm, to) not in ks:
                        ks.insert(0, (frm, to))
                        del ks[2:]
                    k = (side, frm, to)
                    self.history[k] = self.history.get(k, 0) + depth * depth
                break

        if legal_count == 0:
            # No legal move: checkmate if in check, otherwise stalemate —
            # which in Xiangqi is also a loss for the side to move.
            return -MATE + ply

        flag = 0 if alpha_orig < best < beta else (1 if best >= beta else 2)
        self.tt[key] = (depth, best, flag, best_move)
        return best

    def search(self, board: Board, side: Optional[int] = None):
        """Return the best ``(from_pos, to_pos)`` for ``side``, or None."""
        if side is None:
            side = board.side_to_move
        work = board.clone()
        work.move_history = []

        legal = generate_legal_moves(work, side)
        if not legal:
            return None

        self.nodes = 0
        self.killers.clear()
        self._deadline = time.time() + self.time_limit
        best_move = legal[0]

        for d in range(1, self.depth + 1):
            alpha, beta = -INF, INF
            local_best, local_score = None, -INF
            for frm, to in self._order(work, legal, side, 0,
                                       best_move):
                work.make_move(frm, to)
                val = -self._search(work, 1 - side, d - 1, -beta, -alpha, 1)
                work.undo_move()
                if val > local_score:
                    local_score, local_best = val, (frm, to)
                if val > alpha:
                    alpha = val
                if self._timed_out():
                    break
            if local_best is not None:
                best_move, self.last_score, self.last_depth = (
                    local_best, local_score, d)
            if self._timed_out() or abs(self.last_score) > MATE - 100:
                break

        return best_move


# ══════════════════════════════════════════════════════════════
#  Pikafish (UCI) backend
# ══════════════════════════════════════════════════════════════

_CHAR = {KING: 'k', ADVISOR: 'a', ELEPHANT: 'b', ROOK: 'r',
         KNIGHT: 'n', CANNON: 'c', PAWN: 'p'}
_FROM_CHAR = {v: k for k, v in _CHAR.items()}


def board_to_fen(board: Board, side: int) -> str:
    """Serialise a Board to Xiangqi FEN.

    FEN ranks run from rank 9 (Black's back rank) down to rank 0, and files
    a→i left to right. Red is uppercase.
    """
    rows = []
    for rank in range(9, -1, -1):
        row, empty = '', 0
        for file in range(9):
            val = board.cells[file * BOARD_STRIDE + rank]
            if not val:
                empty += 1
                continue
            if empty:
                row += str(empty)
                empty = 0
            ch = _CHAR[PIECE_TYPES[val & 0x0F]]
            row += ch.upper() if ((val >> 5) & 1) == RED else ch
        if empty:
            row += str(empty)
        rows.append(row)
    return f"{'/'.join(rows)} {'w' if side == RED else 'b'} - - 0 1"


def pos_to_uci(pos: int) -> str:
    return f"{chr(ord('a') + pos // BOARD_STRIDE)}{pos % BOARD_STRIDE}"


def uci_to_move(s: str) -> tuple[int, int]:
    f = (ord(s[0]) - ord('a')) * BOARD_STRIDE + int(s[1])
    t = (ord(s[2]) - ord('a')) * BOARD_STRIDE + int(s[3])
    return f, t


def find_pikafish() -> Optional[str]:
    """Locate a Pikafish binary on PATH or next to this file."""
    for name in ('pikafish', 'pikafish.exe'):
        p = shutil.which(name)
        if p:
            return p
    here = os.path.dirname(os.path.abspath(__file__))
    for sub in ('', 'engines', 'pikafish'):
        for name in ('pikafish.exe', 'pikafish'):
            p = os.path.join(here, sub, name)
            if os.path.isfile(p):
                return p
    return None


class PikafishEngine:
    """Drive an external Pikafish binary over the UCI protocol."""

    def __init__(self, path: Optional[str] = None, depth: int = 12,
                 movetime: Optional[int] = None, threads: int = 1,
                 hash_mb: int = 16):
        self.path = path or find_pikafish()
        if not self.path:
            raise FileNotFoundError("Pikafish binary not found")
        self.depth = depth
        self.movetime = movetime
        limit = f"{movetime} ms" if movetime else f"depth {depth}"
        self.name = f"Pikafish ({limit}, {threads}T)"
        self.last_score = 0
        self.last_depth = 0
        self.proc = subprocess.Popen(
            [self.path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1,
            cwd=os.path.dirname(self.path) or None,
        )
        self._send('uci')
        self._wait('uciok')
        # NNUE needs the network next to the binary; Threads/Hash are the two
        # options that actually move the needle on strength.
        self._send(f'setoption name Threads value {threads}')
        self._send(f'setoption name Hash value {hash_mb}')
        self._send('isready')
        self._wait('readyok')

    def _send(self, cmd: str) -> None:
        self.proc.stdin.write(cmd + '\n')
        self.proc.stdin.flush()

    def _wait(self, token: str, timeout: float = 30.0) -> list[str]:
        lines, end = [], time.time() + timeout
        while time.time() < end:
            line = self.proc.stdout.readline()
            if not line:
                break
            lines.append(line.strip())
            if line.startswith(token):
                return lines
        raise TimeoutError(f"Pikafish did not respond with {token!r}")

    def search(self, board: Board, side: Optional[int] = None):
        if side is None:
            side = board.side_to_move
        self._send(f'position fen {board_to_fen(board, side)}')
        self._send(f'go movetime {self.movetime}' if self.movetime
                   else f'go depth {self.depth}')
        lines = self._wait('bestmove', timeout=120.0)

        for line in reversed(lines):
            if line.startswith('info') and ' score cp ' in line:
                parts = line.split()
                self.last_score = int(parts[parts.index('cp') + 1])
                if 'depth' in parts:
                    self.last_depth = int(parts[parts.index('depth') + 1])
                break

        best = lines[-1].split()
        if len(best) < 2 or best[1] in ('(none)', 'none'):
            return None
        return uci_to_move(best[1])

    def close(self) -> None:
        try:
            self._send('quit')
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


def get_engine(prefer_pikafish: bool = True, depth: int = 5,
               time_limit: float = 5.0):
    """Return the strongest available opponent engine."""
    if prefer_pikafish and find_pikafish():
        try:
            return PikafishEngine(depth=max(depth, 10))
        except Exception as exc:  # pragma: no cover - depends on local binary
            print(f"  (Pikafish unavailable: {exc}; using built-in engine)")
    return ModernEngine(depth=depth, time_limit=time_limit)
