"""
pyqiwang — Interactive Chinese Chess game against the 棋王 AI.

Usage:
    python -m pyqiwang               # interactive game
    python -m pyqiwang --depth 3     # set search depth (1-12)
    python -m pyqiwang --demo        # auto-play demo
"""

from __future__ import annotations

import argparse
import time

from pyqiwang import (
    QiWangEngine, Board, RED, BLACK,
    pos_to_notation, notation_to_pos,
    generate_legal_moves, is_in_check,
    BOARD_STRIDE, PIECE_TYPES,
)


def _main():
    parser = argparse.ArgumentParser(
        description="Chinese Chess — 棋王 ROM AI engine"
    )
    parser.add_argument('--depth', type=int, default=2,
                        help='Search depth (default: 2, range 1-12)')
    parser.add_argument('--demo', action='store_true',
                        help='Auto-play demo (both sides AI)')
    parser.add_argument('--side', type=str, default='red',
                        choices=['red', 'black'],
                        help='Play as red (default) or black')
    args = parser.parse_args()

    engine = QiWangEngine(depth=args.depth)

    if args.demo:
        _demo(engine)
        return

    human_side = RED if args.side != 'black' else BLACK
    _play_interactive(engine, human_side)


def _play_interactive(engine: QiWangEngine, human_side: int) -> None:
    board = Board()
    print("=" * 50)
    print("  Chinese Chess — 棋王 AI Engine")
    print(f"  Depth: {engine.depth}  |  You: {'RED' if human_side==RED else 'BLACK'}")
    print("=" * 50)
    print("Move format: e7e5 (from + to squares)")
    print("Commands: quit, undo, reset\n")

    while True:
        side = board.side_to_move
        print_board(board)

        legal = generate_legal_moves(board, side)
        if not legal:
            if is_in_check(board, side):
                winner = 'Black' if side == RED else 'Red'
                print(f"Checkmate! {winner} wins!")
            else:
                print("Stalemate!")
            break

        if side == human_side:
            move_str = input(
                f"{'Red' if side==RED else 'Black'} to move > "
            ).strip()
            if move_str in ('quit', 'q', 'exit'):
                break
            if move_str == 'undo':
                print("Undo not available in ROM mode")
                continue
            if move_str == 'reset':
                engine.reset()
                board = Board()
                continue
            if len(move_str) < 4:
                print("Format: a0a1 (file+rank, e.g. a0a1)")
                continue
            frm = notation_to_pos(move_str[:2])
            to = notation_to_pos(move_str[2:])
            if (frm, to) not in legal:
                print("Illegal move!")
                continue
            engine.make_move(board, frm, to)
            print(f"  You: {pos_to_notation(frm)} -> {pos_to_notation(to)}")
        else:
            print("AI thinking...")
            t0 = time.time()
            move = engine.get_best_move(board)
            elapsed = time.time() - t0
            if move is None:
                print("AI resigns!")
                break
            engine.make_move(board, *move)
            print(f"  AI:  {pos_to_notation(move[0])} -> {pos_to_notation(move[1])}  ({elapsed:.1f}s)")


def _demo(engine: QiWangEngine) -> None:
    print("Auto-play demo (both sides = AI)...\n")
    result = engine.play_auto(max_moves=200, verbose=True)
    print(f"Result: {result}")


def print_board(board: Board) -> None:
    """Pretty-print the board to the terminal."""
    FILE_CHARS = 'abcdefghi'
    pieces_red = {
        'K': '帅', 'A': '仕', 'B': '相', 'R': '车', 'N': '马', 'C': '炮', 'P': '兵',
    }
    pieces_black = {
        'K': '将', 'A': '士', 'B': '象', 'R': '車', 'N': '馬', 'C': '砲', 'P': '卒',
    }
    type_to_char = {
        1: 'K', 2: 'A', 3: 'B', 4: 'R', 5: 'N', 6: 'C', 7: 'P',
    }

    print()
    print("    0    1    2    3    4    5    6    7    8    9")
    for file in range(8, -1, -1):
        line = f"  {file} "
        for rank in range(10):
            pos = file * BOARD_STRIDE + rank
            val = board.cells[pos]
            if val == 0:
                line += "  .  "
            else:
                side = (val >> 5) & 1
                idx = val & 0x0F
                ptype = PIECE_TYPES[idx]
                ch = type_to_char.get(ptype, '?')
                name = pieces_red[ch] if side == RED else pieces_black[ch]
                line += f"  {name} "
        print(line)
    print(f"     {'a':>4}    {'b':>4}    {'c':>4}    {'d':>4}    {'e':>4}    "
          f"{'f':>4}    {'g':>4}    {'h':>4}    {'i':>4}")
    side_name = 'Red' if board.side_to_move == RED else 'Black'
    print(f"  {side_name} to move\n")


if __name__ == '__main__':
    _main()
