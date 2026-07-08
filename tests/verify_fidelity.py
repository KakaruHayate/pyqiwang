#!/usr/bin/env python3
"""verify_fidelity_v2.py — ROM $8597 ground truth verification.

Strategy: Use ROM harness directly for AI moves (100% fidelity).
Compare against Python AIEngine for reference only.
All ROM moves must be legal in Python board representation.
"""
import sys
sys.path.insert(0, '.')
from rom_harness import RomHarness
from chinese_chess_ai import (
    AIEngine, ROMSearchEngine, Board, RED, BLACK,
    generate_legal_moves, is_in_check, evaluate
)
import time

h = RomHarness()

def sync_board(h, b):
    """Sync Python board from ROM RAM."""
    b.cells = [0] * len(b.cells)
    for idx in range(16):
        b.pieces[RED][idx] = -1
        b.pieces[BLACK][idx] = -1
    for idx in range(16):
        rp = h.rd(0x94+idx)
        bp = h.rd(0xA4+idx)
        if rp < 0x84:
            b.pieces[RED][idx] = rp
            b.cells[rp] = 0x10 + idx
        if bp < 0x84:
            b.pieces[BLACK][idx] = bp
            b.cells[bp] = 0x20 + idx
    c7 = h.rd(0xC7)
    b.side_to_move = RED if (c7 & 0x10) else BLACK
    b.move_history = []

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--depth', type=int, default=2)
    parser.add_argument('--trials', type=int, default=10)
    parser.add_argument('--steps', type=int, default=6)
    args = parser.parse_args()

    rom_engine = ROMSearchEngine(depth=args.depth, harness=h)
    py_engine = AIEngine(depth=args.depth)

    ok_legal = 0; tot_legal = 0
    ok_py = 0; tot_py = 0
    game_oks = 0
    mismatches = []

    t0 = time.time()

    for trial in range(args.trials):
        h.boot()
        h.new_game(side_to_move=0x10, book=False)

        game_ok = True
        for step in range(args.steps):
            # ROM move (ground truth)
            rom_move = h.get_ai_move(args.depth)
            if rom_move is None:
                break
            tot_legal += 1

            # Sync Python board from ROM RAM
            b = Board()
            sync_board(h, b)

            # Check legality
            legal = generate_legal_moves(b, b.side_to_move)
            if rom_move in legal:
                ok_legal += 1
            else:
                game_ok = False
                if len(mismatches) < 10:
                    mismatches.append(
                        f"  trial{trial} step{step}: ROM move {rom_move} NOT legal!")
                # Don't break - continue to collect more data

            # Compare with Python AIEngine (reference)
            py_move = py_engine.search_best_move(b)
            tot_py += 1
            if rom_move == py_move:
                ok_py += 1
            elif len(mismatches) < 10:
                mismatches.append(
                    f"  trial{trial} step{step}: ROM={rom_move} PY={py_move}")

            # Execute ROM move
            if not h.exec_move(*rom_move):
                game_ok = False
                break

        if game_ok:
            game_oks += 1

    t1 = time.time()

    print(f"=== Fidelity Report (depth={args.depth}, {args.trials} trials, {args.steps} steps) ===")
    print(f"Time: {t1-t0:.1f}s")
    print(f"Legality:     {ok_legal}/{tot_legal} ({100*ok_legal//max(tot_legal,1)}%)")
    print(f"Python match: {ok_py}/{tot_py} ({100*ok_py//max(tot_py,1)}%)")
    print(f"Complete games: {game_oks}/{args.trials}")
    if mismatches:
        print("\nMismatches (first 10):")
        for m in mismatches[:10]:
            print(m)

if __name__ == '__main__':
    main()
