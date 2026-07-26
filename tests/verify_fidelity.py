#!/usr/bin/env python3
"""ROM fidelity verification.

The ROM is its own ground truth: we let it play against itself using its
*internal* state (``$E49E`` executes each move in ROM RAM), and at every ply
we independently ask ``QiWangEngine`` — which syncs a Python ``Board`` into
ROM RAM from scratch — for its move. The two must agree exactly, otherwise
the Python-side board sync is lossy.

Also checks that every ROM move is legal under the Python move generator.

    python -m tests.verify_fidelity --depth 2 --plies 40
"""
from __future__ import annotations

import argparse
import sys
import time

from pyqiwang import QiWangEngine, Board, RED, BLACK
from pyqiwang._board import generate_legal_moves, pos_to_notation
from pyqiwang._harness import RomHarness


def rom_to_board(h: RomHarness) -> Board:
    """Build a Python Board from the ROM's own piece tables."""
    b = Board()
    b.cells = [0] * len(b.cells)
    b.pieces[RED] = [-1] * 16
    b.pieces[BLACK] = [-1] * 16
    b.move_history = []
    for i in range(16):
        rp, bp = h.rd(0x94 + i), h.rd(0xA4 + i)
        if rp < 0x84:
            b.pieces[RED][i] = rp
            b.cells[rp] = 0x10 + i
        if bp < 0x84:
            b.pieces[BLACK][i] = bp
            b.cells[bp] = 0x20 + i
    b.side_to_move = RED if (h.rd(0xC7) & 0x10) else BLACK
    return b


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--depth', type=int, default=2)
    p.add_argument('--plies', type=int, default=40)
    p.add_argument('-v', '--verbose', action='store_true')
    a = p.parse_args()

    h = RomHarness()
    h.boot()
    h.new_game(side_to_move=0x10, book=False)
    engine = QiWangEngine(depth=a.depth)

    agree = legal_ok = total = 0
    problems: list[str] = []
    t0 = time.time()

    for ply in range(a.plies):
        board = rom_to_board(h)
        side = 'R' if board.side_to_move == RED else 'B'

        truth = h.get_ai_move(a.depth)   # ROM, from its own state
        if truth is None:
            break
        total += 1

        if truth in generate_legal_moves(board, board.side_to_move):
            legal_ok += 1
        else:
            problems.append(f"ply {ply} {side}: ROM move {truth} is illegal")

        mine = engine.get_best_move(board)   # engine, from a synced board
        if mine == truth:
            agree += 1
        else:
            problems.append(f"ply {ply} {side}: ROM={truth} engine={mine}")

        if a.verbose:
            mark = 'ok' if mine == truth else 'MISMATCH'
            print(f"  ply {ply:3d} {side}  "
                  f"{pos_to_notation(truth[0])}->{pos_to_notation(truth[1])}  {mark}")

        if not h.exec_move(*truth):
            problems.append(f"ply {ply}: ROM exec_move rejected {truth}")
            break

    print(f"\ndepth={a.depth}  plies={total}  ({time.time() - t0:.0f}s)")
    print(f"  engine matches ROM : {agree}/{total}")
    print(f"  ROM moves legal    : {legal_ok}/{total}")
    for line in problems[:20]:
        print(f"  ! {line}")

    ok = total > 0 and agree == total and legal_ok == total
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
