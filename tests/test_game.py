#!/usr/bin/env python3
"""Test a complete game using ROM $8597 as AI."""
import sys
sys.path.insert(0, '.')
from rom_harness import RomHarness
from chinese_chess_ai import Board, RED, BLACK, generate_legal_moves, is_in_check

h = RomHarness()

def sync_board(h, b):
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

def pos_to_notation(pos):
    file = pos // 12
    rank = pos % 12
    return f"{chr(ord('a')+file)}{rank}"

h.boot()
h.init_board()
h.new_game(side_to_move=0x10, book=False)

print("=== Auto-play game (Red vs Black AI) ===")
print(f"{'='*60}")

for step in range(100):
    b = Board()
    sync_board(h, b)
    side_name = "RED" if b.side_to_move == RED else "BLACK"
    
    # Get AI move
    move = h.get_ai_move(2)
    if move is None:
        legal = generate_legal_moves(b, b.side_to_move)
        if not legal:
            if is_in_check(b, b.side_to_move):
                print(f"\n{side_name} is checkmated!")
            else:
                print(f"\nStalemate!")
        break
    
    # Check legality
    legal = generate_legal_moves(b, b.side_to_move)
    if move not in legal:
        print(f"\n*** ILLEGAL MOVE at step {step}: {move}")
        print(f"  Side: {side_name}")
        print(f"  Legal moves: {len(legal)}")
        break
    
    # Execute
    frm_n = pos_to_notation(move[0])
    to_n = pos_to_notation(move[1])
    print(f"Step {step:2d} {side_name:6s}: {frm_n} -> {to_n}")
    
    h.exec_move(*move)
    
    # Check for game end
    b2 = Board()
    sync_board(h, b2)
    legal2 = generate_legal_moves(b2, b2.side_to_move)
    if not legal2:
        if is_in_check(b2, b2.side_to_move):
            print(f"\n{side_name} wins! Checkmate at step {step}!")
        else:
            print(f"\nStalemate at step {step}!")
        break
else:
    print(f"\nGame reached {step} steps without conclusion")

print(f"{'='*60}")
print("Game completed successfully!")
