#!/usr/bin/env python3
"""Compare simple selective-search models with ROM depth-1 golden moves."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyqiwang import BLACK, RED, Board
from pyqiwang._board import evaluate_raw, generate_legal_moves, is_in_check


def load_board(record: dict) -> Board:
    board = Board()
    board.pieces[RED] = list(record["red"])
    board.pieces[BLACK] = list(record["black"])
    board.side_to_move = record["side"]
    board.move_history = []
    board._init_board()
    return board


def recapture_quiesce(board: Board, side: int, target: int, ply: int = 0) -> int:
    """Search check evasions or captures back onto the previous landing square."""
    stand = evaluate_raw(board)
    if ply >= 12:
        return stand
    checked = is_in_check(board, side)
    moves = generate_legal_moves(board, side)
    selected = moves if checked else [move for move in moves if move[1] == target]
    if not selected:
        return stand
    values = []
    for move in selected:
        board.make_move(*move)
        values.append(recapture_quiesce(board, 1 - side, move[1], ply + 1))
        board.undo_move()
    return max(values) if side == RED else min(values)


def choose_recaptures(board: Board):
    root = board.side_to_move
    best_move = None
    best_score = None
    for move in generate_legal_moves(board, root):
        board.make_move(*move)
        score = recapture_quiesce(board, board.side_to_move, move[1])
        board.undo_move()
        better = (best_score is None or
                  (root == RED and score > best_score) or
                  (root == BLACK and score < best_score))
        if better:
            best_score, best_move = score, move
    return best_move


def choose(board: Board, reply_mode: str):
    root = board.side_to_move
    best_move = None
    best_score = None
    for move in generate_legal_moves(board, root):
        board.make_move(*move)
        replies = generate_legal_moves(board, board.side_to_move)
        if reply_mode == "captures":
            replies = [reply for reply in replies if board.cells[reply[1]]]
        if replies:
            values = []
            for reply in replies:
                board.make_move(*reply)
                values.append(evaluate_raw(board))
                board.undo_move()
            score = min(values) if root == RED else max(values)
        else:
            score = evaluate_raw(board)
        board.undo_move()
        better = (best_score is None or
                  (root == RED and score > best_score) or
                  (root == BLACK and score < best_score))
        if better:
            best_score, best_move = score, move
    return best_move


def main() -> None:
    corpora = (
        "rom_depth1_golden.json",
        "rom_depth1_independent.json",
    )
    for name in corpora:
        data = json.loads((ROOT / "tests/fixtures" / name).read_text())
        for mode in ("captures", "all", "recaptures"):
            agreement = 0
            print(name, mode)
            for case in data["cases"]:
                board = load_board(case["board"])
                got = (choose_recaptures(board) if mode == "recaptures"
                       else choose(board, mode))
                want = tuple(case["best_move"])
                agreement += got == want
                print(case["id"], want, got, got == want)
            print("agreement", agreement, "/", len(data["cases"]))


if __name__ == "__main__":
    main()
