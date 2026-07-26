#!/usr/bin/env python3
"""Correctness tests for the pyqiwang board, evaluation and engine.

Run with::

    python -m tests.test_game            # fast checks
    python -m tests.test_game --slow     # also exercise the ROM engine

The move-generation test compares against a reference generator written
independently in (file, rank) coordinates, so a shared mistake in the
delta tables cannot hide.
"""
from __future__ import annotations

import argparse
import random
import sys

from pyqiwang import Board, RED, BLACK
from pyqiwang._board import (
    PIECE_TYPES, KING, ADVISOR, ELEPHANT, ROOK, KNIGHT, CANNON, PAWN,
    generate_moves, generate_legal_moves, is_in_check, evaluate_raw,
    BOARD_STRIDE as S,
)


# ── Reference move generator (independent of _board's delta tables) ──

def _fr(p): return p // S, p % S
def _po(f, r): return f * S + r
def _on(f, r): return 0 <= f <= 8 and 0 <= r <= 9


def _side_at(b, f, r):
    v = b.cells[_po(f, r)]
    return None if v == 0 else (v >> 5) & 1


def reference_moves(b: Board, side: int) -> list[tuple[int, int]]:
    """Generate pseudo-legal moves straight from the rules of Xiangqi."""
    out = []
    for idx in range(16):
        p = b.pieces[side][idx]
        if p < 0:
            continue
        t = PIECE_TYPES[idx]
        f, r = _fr(p)
        lo, hi = (0, 2) if side == RED else (7, 9)

        if t in (KING, ADVISOR):
            steps = ((1, 0), (-1, 0), (0, 1), (0, -1)) if t == KING else \
                    ((1, 1), (1, -1), (-1, 1), (-1, -1))
            for df, dr in steps:
                nf, nr = f + df, r + dr
                if 3 <= nf <= 5 and lo <= nr <= hi and _side_at(b, nf, nr) != side:
                    out.append((p, _po(nf, nr)))

        elif t == ELEPHANT:
            for df, dr in ((2, 2), (2, -2), (-2, 2), (-2, -2)):
                nf, nr = f + df, r + dr
                if not _on(nf, nr):
                    continue
                if (nr > 4) if side == RED else (nr < 5):
                    continue  # may not cross the river
                if b.cells[_po(f + df // 2, r + dr // 2)]:
                    continue  # eye blocked
                if _side_at(b, nf, nr) != side:
                    out.append((p, _po(nf, nr)))

        elif t == KNIGHT:
            for df, dr in ((1, 2), (-1, 2), (1, -2), (-1, -2),
                           (2, 1), (2, -1), (-2, 1), (-2, -1)):
                nf, nr = f + df, r + dr
                if not _on(nf, nr):
                    continue
                lf, lr = ((f, r + (1 if dr > 0 else -1)) if abs(dr) == 2
                          else (f + (1 if df > 0 else -1), r))
                if b.cells[_po(lf, lr)]:
                    continue  # leg blocked
                if _side_at(b, nf, nr) != side:
                    out.append((p, _po(nf, nr)))

        elif t in (ROOK, CANNON):
            for df, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nf, nr = f + df, r + dr
                jumped = False
                while _on(nf, nr):
                    o = _side_at(b, nf, nr)
                    if t == ROOK:
                        if o is None:
                            out.append((p, _po(nf, nr)))
                        else:
                            if o != side:
                                out.append((p, _po(nf, nr)))
                            break
                    elif not jumped:
                        if o is None:
                            out.append((p, _po(nf, nr)))
                        else:
                            jumped = True
                    elif o is not None:
                        if o != side:
                            out.append((p, _po(nf, nr)))
                        break
                    nf, nr = nf + df, nr + dr

        elif t == PAWN:
            cands = [(0, 1 if side == RED else -1)]
            if (r >= 5) if side == RED else (r <= 4):
                cands += [(1, 0), (-1, 0)]   # sideways after the river
            for df, dr in cands:
                nf, nr = f + df, r + dr
                if _on(nf, nr) and _side_at(b, nf, nr) != side:
                    out.append((p, _po(nf, nr)))
    return out


def random_position(rng: random.Random, max_plies: int = 40) -> Board:
    b = Board()
    for _ in range(rng.randint(0, max_plies)):
        legal = generate_legal_moves(b, b.side_to_move)
        if not legal:
            break
        b.make_move(*rng.choice(legal))
    return b


# ── Tests ────────────────────────────────────────────────────

def test_move_generation(trials: int = 300) -> bool:
    rng = random.Random(11)
    bad = 0
    for _ in range(trials):
        b = random_position(rng)
        for side in (RED, BLACK):
            got = sorted(set(generate_moves(b, side)))
            want = sorted(set(reference_moves(b, side)))
            if got != want:
                bad += 1
                if bad <= 3:
                    print(f"  ! extra={sorted(set(got) - set(want))} "
                          f"missing={sorted(set(want) - set(got))}")
    print(f"move generation vs reference: {2 * trials - bad}/{2 * trials}")
    return bad == 0


def test_make_unmake(trials: int = 200) -> bool:
    """make_move followed by undo_move must restore the position exactly."""
    rng = random.Random(5)
    bad = 0
    for _ in range(trials):
        b = random_position(rng, 30)
        before = (list(b.cells), list(b.pieces[RED]), list(b.pieces[BLACK]),
                  b.side_to_move)
        for frm, to in generate_legal_moves(b, b.side_to_move)[:8]:
            b.make_move(frm, to)
            b.undo_move()
            after = (list(b.cells), list(b.pieces[RED]), list(b.pieces[BLACK]),
                     b.side_to_move)
            if before != after:
                bad += 1
                break
    print(f"make/unmake round-trip: {trials - bad}/{trials}")
    return bad == 0


def test_legal_moves_escape_check(trials: int = 120) -> bool:
    """No 'legal' move may leave one's own king in check."""
    rng = random.Random(17)
    bad = 0
    for _ in range(trials):
        b = random_position(rng)
        side = b.side_to_move
        for frm, to in generate_legal_moves(b, side):
            b.make_move(frm, to)
            if is_in_check(b, side):
                bad += 1
            b.undo_move()
    print(f"legal moves leave king safe: {'ok' if bad == 0 else f'{bad} bad'}")
    return bad == 0


def test_evaluation_matches_rom(trials: int = 10) -> bool:
    """Python evaluate_raw() must equal the ROM's own $8886 evaluation.

    The ROM leaves the 16-bit score at $C8/$C9 (little endian).
    """
    from pyqiwang import QiWangEngine
    engine = QiWangEngine(depth=2)
    rng = random.Random(7)
    ok = 0
    for _ in range(trials):
        b = random_position(rng, 14)
        engine._sync_board_to_rom(b)
        engine.harness.call_subroutine(0x8886)
        rom = engine.harness.rd(0xC8) | (engine.harness.rd(0xC9) << 8)
        if rom == evaluate_raw(b):
            ok += 1
    print(f"PST evaluation vs ROM $8886: {ok}/{trials}")
    return ok == trials


def test_engine_opening() -> bool:
    """The engine must reproduce the ROM's documented opening move."""
    from pyqiwang import QiWangEngine
    move = QiWangEngine(depth=2).get_best_move(Board())
    ok = move == (86, 50)   # h2->e2, 炮二平五
    print(f"opening move h2->e2 (炮二平五): {move} {'ok' if ok else 'WRONG'}")
    return ok


def test_opening_book() -> bool:
    """The ROM's opening book must play a legal line and hand off to search.

    The book at $CD26 is a *sequential* walk through a stored line: it
    advances its own pointer and executes the move itself via $E49E, so it
    only applies while the game follows that line from the start.
    """
    from pyqiwang import QiWangEngine
    engine = QiWangEngine(depth=2, book=True)
    board = Board()
    book_plies = 0

    for _ in range(60):
        from_book = engine._book_applies(board)
        move = engine.get_best_move(board)
        if move is None:
            break
        if move not in generate_legal_moves(board, board.side_to_move):
            print(f"  ! book/search move {move} is illegal")
            return False
        book_plies += from_book
        board.make_move(*move)
        if not from_book:
            break   # book is done; we only needed to see the handoff

    # The stored line is 33 plies long and starts 炮八平五 (c0->e2).
    ok = book_plies >= 30
    print(f"opening book: {book_plies} book plies then search "
          f"{'ok' if ok else 'TOO SHORT'}")
    return ok


def test_book_leaves_no_residue() -> bool:
    """After the book runs, search must still match a pristine engine.

    book_move() mutates ROM RAM directly, so this guards against state that
    _sync_board_to_rom() fails to restore.
    """
    from pyqiwang import QiWangEngine
    engine = QiWangEngine(depth=2, book=True)
    board = Board()
    while engine._book_applies(board):
        move = engine.get_best_move(board)
        if move is None:
            break
        board.make_move(*move)

    pristine = QiWangEngine(depth=2, book=False)
    ok = 0
    for _ in range(4):
        a = engine.get_best_move(board)
        b = pristine.get_best_move(board)
        if a != b:
            print(f"  ! post-book={a} pristine={b}")
            break
        ok += 1
        if a is None:
            break
        board.make_move(*a)
    print(f"post-book search matches pristine: {ok}/4")
    return ok == 4


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--slow', action='store_true',
                   help='also run the ROM-backed tests (needs the ROM)')
    a = p.parse_args()

    results = [
        test_move_generation(),
        test_make_unmake(),
        test_legal_moves_escape_check(),
    ]
    if a.slow:
        results += [test_engine_opening(), test_evaluation_matches_rom(),
                    test_opening_book(), test_book_leaves_no_residue()]
    else:
        print("(skipping ROM tests; pass --slow to include them)")

    print("PASS" if all(results) else "FAIL")
    return 0 if all(results) else 1


if __name__ == '__main__':
    sys.exit(main())
