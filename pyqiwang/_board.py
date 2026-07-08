"""
pyqiwang._board — Board representation and move generation.

Position encoding: pos = file * 12 + rank (file: 0-8, rank: 0-9).
Cell values: 0 = empty, 0x10+idx = Red piece, 0x20+idx = Black piece.
"""
from __future__ import annotations

import json
import os

# ── Constants ──────────────────────────────────────────────

BOARD_STRIDE = 12

EMPTY = 0
RED = 0
BLACK = 1

KING     = 1
ADVISOR  = 2
ELEPHANT = 3
ROOK     = 4
KNIGHT   = 5
CANNON   = 6
PAWN     = 7

PIECE_NAMES = {
    KING: '帅', ADVISOR: '仕', ELEPHANT: '相', ROOK: '车',
    KNIGHT: '马', CANNON: '炮', PAWN: '兵',
}
PIECE_NAMES_BLACK = {
    KING: '将', ADVISOR: '士', ELEPHANT: '象', ROOK: '車',
    KNIGHT: '馬', CANNON: '砲', PAWN: '卒',
}

# Piece order per side (matches ROM piece indices $00-$0F)
PIECE_TYPES = [
    KING, ROOK, ROOK, CANNON, CANNON, KNIGHT, KNIGHT,
    ADVISOR, ADVISOR, ELEPHANT, ELEPHANT,
    PAWN, PAWN, PAWN, PAWN, PAWN,
]

# Initial positions from ROM $E1FD (pos = file*12 + rank)
RED_INIT = [48, 96, 0, 86, 14, 84, 12, 60, 36, 72, 24, 99, 75, 51, 27, 3]
BLACK_INIT = [57, 105, 9, 91, 19, 93, 21, 69, 45, 81, 33, 102, 78, 54, 30, 6]

# Move deltas from ROM $CFDA
ADVISOR_DELTAS   = [-13, 11, -11, 13]
ELEPHANT_DELTAS  = [-26, 22, -22, 26]
ELEPHANT_LEGS    = [-13, 11, -11, 13]
KNIGHT_DELTAS    = [-14, 10, -10, 14, -25, -23, 23, 25]
KNIGHT_LEGS      = [-1, 1, -1, 1, -12, -12, 12, 12]

# Palace regions
RED_PALACE   = {f * 12 + r for f in range(3, 6) for r in range(0, 3)}
BLACK_PALACE = {f * 12 + r for f in range(3, 6) for r in range(7, 10)}

# Piece material values (for static exchange evaluation, not used by engine)
PIECE_VALUES = {
    KING: 10000, ROOK: 500, CANNON: 250, KNIGHT: 250,
    ADVISOR: 100, ELEPHANT: 100, PAWN: 50,
}


# ── Helpers ────────────────────────────────────────────────

def _encode_piece(side: int, idx: int) -> int:
    return 0x10 + side * 0x10 + idx

def _decode_piece(val: int):
    if val == 0:
        return None, None, None
    side = (val >> 5) & 1
    idx = val & 0x0F
    return side, idx, PIECE_TYPES[idx]


# ── Board ─────────────────────────────────────────────────

class Board:
    """Chinese chess board state.

    Cells use ROM encoding: 0x10+idx = Red, 0x20+idx = Black, 0 = empty.
    Position encoding: pos = file * 12 + rank.
    """

    def __init__(self):
        self.cells: list[int] = [0] * (BOARD_STRIDE * 11)
        self.pieces: list[list[int]] = [list(RED_INIT), list(BLACK_INIT)]
        self.side_to_move: int = RED
        self.move_history: list[tuple] = []
        self._init_board()

    def _init_board(self) -> None:
        self.cells = [0] * (BOARD_STRIDE * 11)
        for side in range(2):
            for idx in range(16):
                pos = self.pieces[side][idx]
                if pos >= 0:
                    self.cells[pos] = _encode_piece(side, idx)

    # ── Coordinate helpers ────────────────────────────────

    def pos_to_coord(self, pos: int) -> tuple[int, int]:
        return pos // BOARD_STRIDE, pos % BOARD_STRIDE

    def coord_to_pos(self, file: int, rank: int) -> int:
        return file * BOARD_STRIDE + rank

    def is_valid_pos(self, pos: int) -> bool:
        f, r = self.pos_to_coord(pos)
        return 0 <= f <= 8 and 0 <= r <= 9

    def get_side(self, pos: int) -> int | None:
        val = self.cells[pos]
        if val == 0:
            return None
        return (val >> 5) & 1

    # ── Move execution ────────────────────────────────────

    def make_move(self, frm: int, to: int) -> None:
        moving_val = self.cells[frm]
        side, idx, _ = _decode_piece(moving_val)

        captured_val = self.cells[to]
        captured_side, captured_idx = None, None
        if captured_val != 0:
            captured_side, captured_idx, _ = _decode_piece(captured_val)
            self.pieces[captured_side][captured_idx] = -1

        self.cells[to] = moving_val
        self.cells[frm] = 0
        self.pieces[side][idx] = to

        self.move_history.append(
            (frm, to, moving_val, captured_val, captured_side, captured_idx)
        )
        self.side_to_move = 1 - self.side_to_move

    def undo_move(self) -> None:
        if not self.move_history:
            return
        frm, to, moving_val, captured_val, cs, ci = self.move_history.pop()
        side, idx, _ = _decode_piece(moving_val)

        self.cells[frm] = moving_val
        self.cells[to] = captured_val
        self.pieces[side][idx] = frm
        if captured_val != 0:
            self.pieces[cs][ci] = to

        self.side_to_move = 1 - self.side_to_move

    def clone(self) -> Board:
        b = Board.__new__(Board)
        b.cells = list(self.cells)
        b.pieces = [list(self.pieces[0]), list(self.pieces[1])]
        b.side_to_move = self.side_to_move
        b.move_history = list(self.move_history)
        return b


# ── Move generation ────────────────────────────────────────

def generate_piece_moves(board: Board, side: int, pos: int,
                         ptype: int) -> list[tuple[int, int]]:
    moves: list[tuple[int, int]] = []
    file, rank = board.pos_to_coord(pos)

    if ptype == KING:
        for delta in [-1, 1, -12, 12]:
            to = pos + delta
            if not board.is_valid_pos(to):
                continue
            palace = RED_PALACE if side == RED else BLACK_PALACE
            if to not in palace:
                continue
            if board.get_side(to) == side:
                continue
            moves.append((pos, to))

    elif ptype == ADVISOR:
        for delta in ADVISOR_DELTAS:
            to = pos + delta
            if not board.is_valid_pos(to):
                continue
            palace = RED_PALACE if side == RED else BLACK_PALACE
            if to not in palace:
                continue
            if board.get_side(to) == side:
                continue
            moves.append((pos, to))

    elif ptype == ELEPHANT:
        for delta, leg in zip(ELEPHANT_DELTAS, ELEPHANT_LEGS):
            to = pos + delta
            if not board.is_valid_pos(to):
                continue
            # Cannot cross river
            to_file, to_rank = board.pos_to_coord(to)
            if side == RED and to_rank > 4:
                continue
            if side == BLACK and to_rank < 5:
                continue
            if board.cells[pos + leg] != 0:
                continue  # leg blocked
            if board.get_side(to) == side:
                continue
            moves.append((pos, to))

    elif ptype == KNIGHT:
        for delta, leg in zip(KNIGHT_DELTAS, KNIGHT_LEGS):
            to = pos + delta
            if not board.is_valid_pos(to):
                continue
            if board.cells[pos + leg] != 0:
                continue  # leg blocked
            if board.get_side(to) == side:
                continue
            moves.append((pos, to))

    elif ptype == ROOK:
        for direction in [-1, 1, -BOARD_STRIDE, BOARD_STRIDE]:
            to = pos + direction
            while board.is_valid_pos(to):
                target_side = board.get_side(to)
                if target_side == side:
                    break
                moves.append((pos, to))
                if target_side is not None:
                    break
                to += direction

    elif ptype == CANNON:
        for direction in [-1, 1, -BOARD_STRIDE, BOARD_STRIDE]:
            to = pos + direction
            jumped = False
            while board.is_valid_pos(to):
                target_val = board.cells[to]
                if not jumped:
                    if target_val == 0:
                        moves.append((pos, to))
                    else:
                        jumped = True
                else:
                    if target_val != 0:
                        target_side = board.get_side(to)
                        if target_side != side:
                            moves.append((pos, to))
                        break
                to += direction

    elif ptype == PAWN:
        # Red pawns: forward = +1 (rank increases toward Black).
        # Black pawns: forward = -1 (rank decreases toward Red).
        forward = 1 if side == RED else -1
        for delta in [forward]:
            to = pos + delta
            if not board.is_valid_pos(to):
                continue
            if board.get_side(to) == side:
                continue
            moves.append((pos, to))
        # After crossing river: also allow sideways
        _, rank = board.pos_to_coord(pos)
        crossed = (rank >= 5) if side == RED else (rank <= 4)
        if crossed:
            for delta in [-1, 1]:
                to = pos + delta
                if not board.is_valid_pos(to):
                    continue
                if board.get_side(to) == side:
                    continue
                moves.append((pos, to))

    return moves


def _rook_slide(board: Board, side: int, pos: int, delta: int):
    """Slide along a direction (Rook)."""
    moves = []
    to = pos + delta
    while board.is_valid_pos(to):
        target = board.get_side(to)
        if target is None:
            moves.append((pos, to))
        elif target == side:
            break
        else:
            moves.append((pos, to))
            break
        to += delta
    return moves


def _cannon_slide(board: Board, side: int, pos: int, delta: int):
    """Slide along a direction (Cannon). Must jump exactly 1 piece to capture."""
    moves = []
    to = pos + delta
    jumped = False
    while board.is_valid_pos(to):
        if not jumped:
            if board.cells[to] == 0:
                moves.append((pos, to))
            else:
                jumped = True
        else:
            if board.cells[to] != 0:
                if board.get_side(to) != side:
                    moves.append((pos, to))
                break
        to += delta
    return moves


def generate_moves(board: Board, side: int) -> list[tuple[int, int]]:
    moves = []
    for idx in range(16):
        pos = board.pieces[side][idx]
        if pos < 0:
            continue
        ptype = PIECE_TYPES[idx]
        moves.extend(generate_piece_moves(board, side, pos, ptype))
    return moves


# ── Check detection ────────────────────────────────────────

def _find_king(board: Board, side: int) -> int:
    king_idx = PIECE_TYPES.index(KING)
    return board.pieces[side][king_idx]


def is_in_check(board: Board, side: int) -> bool:
    """Return True if 'side' king is under attack."""
    king_pos = _find_king(board, side)
    opp = 1 - side
    for idx in range(16):
        pos = board.pieces[opp][idx]
        if pos < 0:
            continue
        ptype = PIECE_TYPES[idx]
        pmoves = generate_piece_moves(board, opp, pos, ptype)
        for _, to in pmoves:
            if to == king_pos:
                return True
    # King-to-king (face-to-face)
    opp_king = _find_king(board, opp)
    kf, kr = board.pos_to_coord(king_pos)
    okf, _ = board.pos_to_coord(opp_king)
    if kf == okf:
        blocked = False
        lo, hi = min(kr, board.pos_to_coord(opp_king)[1]), max(kr, board.pos_to_coord(opp_king)[1])
        for r in range(lo + 1, hi):
            if board.cells[kf * BOARD_STRIDE + r] != 0:
                blocked = True
                break
        if not blocked:
            return True
    return False


def generate_legal_moves(board: Board, side: int) -> list[tuple[int, int]]:
    moves = generate_moves(board, side)
    legal = []
    for frm, to in moves:
        board.make_move(frm, to)
        if not is_in_check(board, side):
            legal.append((frm, to))
        board.undo_move()
    return legal


# ── Notation ───────────────────────────────────────────────

def pos_to_notation(pos: int) -> str:
    file = pos // BOARD_STRIDE
    rank = pos % BOARD_STRIDE
    return f"{chr(ord('a') + file)}{rank}"

def notation_to_pos(s: str) -> int:
    s = s.strip()
    file = ord(s[0]) - ord('a')
    rank = int(s[1])
    return file * BOARD_STRIDE + rank


# ── Evaluation ─────────────────────────────────────────────

def _build_pst():
    """Build piece-square tables for positional evaluation.

    Tables extracted from ROM $8886 via dynamic trace.
    The ROM computes: score16 = 0x8000 + Σ(red PST) - Σ(black PST)
    """
    _ROM_PST: dict[int, dict[int, list[int]]] = {}

    try:
        _path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             'pst_tables.json')
        with open(_path) as f:
            _data = json.load(f)
        _name_to_type = {'K': KING, 'A': ADVISOR, 'B': ELEPHANT,
                         'R': ROOK, 'N': KNIGHT, 'C': CANNON, 'P': PAWN}
        _default: dict[int, list[int]] = {
            KING: [0]*108, ADVISOR: [0]*108, ELEPHANT: [0]*108,
            ROOK: [0]*108, KNIGHT: [0]*108, CANNON: [0]*108, PAWN: [0]*108,
        }
        for side_key in ('red', 'black'):
            side = RED if side_key == 'red' else BLACK
            _ROM_PST[side] = {}
            for pname, ptype in _name_to_type.items():
                entry = _data.get(f"{side_key}_{pname}", {})
                raw = entry.get('data', _default[ptype]) if isinstance(entry, dict) else _default[ptype]
                if not isinstance(raw, list) or len(raw) != 108:
                    raw = _default[ptype]
                _ROM_PST[side][ptype] = raw
    except Exception:
        _ROM_PST = {RED: {}, BLACK: {}}

    if RED not in _ROM_PST or not _ROM_PST[RED]:
        _default2 = {
            KING: [0]*108, ADVISOR: [0]*108, ELEPHANT: [0]*108,
            ROOK: [0]*108, KNIGHT: [0]*108, CANNON: [0]*108, PAWN: [0]*108,
        }
        _ROM_PST = {RED: dict(_default2), BLACK: dict(_default2)}

    return _ROM_PST


ROM_PST = _build_pst()


def evaluate(board: Board, side: int) -> int:
    """Evaluate position from 'side's perspective.

    Uses ROM-extracted PST tables. Positive = good for side.
    Formula: 0x8000 + Σ(red) - Σ(black)
    """
    score = 0x8000
    for idx in range(16):
        pos = board.pieces[RED][idx]
        if pos >= 0:
            score += ROM_PST[RED].get(PIECE_TYPES[idx], [0]*108)[pos]
    for idx in range(16):
        pos = board.pieces[BLACK][idx]
        if pos >= 0:
            score -= ROM_PST[BLACK].get(PIECE_TYPES[idx], [0]*108)[pos]
    score &= 0xFFFF
    if side == RED:
        return score - 0x8000
    return 0x8000 - score


def evaluate_raw(board: Board) -> int:
    """Evaluate position, return raw 16-bit value (Red-relative).

    Positive = Red advantage. Mirrors ROM $8886 output exactly.
    """
    score = 0x8000
    for idx in range(16):
        pos = board.pieces[RED][idx]
        if pos >= 0:
            score += ROM_PST[RED].get(PIECE_TYPES[idx], [0]*108)[pos]
    for idx in range(16):
        pos = board.pieces[BLACK][idx]
        if pos >= 0:
            score -= ROM_PST[BLACK].get(PIECE_TYPES[idx], [0]*108)[pos]
    return score & 0xFFFF
