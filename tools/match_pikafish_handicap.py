#!/usr/bin/env python3
"""Play ROM depth 6 against Pikafish from a simplified material handicap."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pyqiwang import BLACK, RED, Board, QiWangEngine
from pyqiwang._board import generate_legal_moves, is_in_check
from modern_ai import PikafishEngine
from match import describe, write_html

HANDICAPS = {
    "right-knight": ("h9",),
    "left-knight": ("b9",),
    "both-knights": ("b9", "h9"),
}


def remove_piece(board: Board, square: str, side: int) -> None:
    file = ord(square[0]) - ord("a")
    rank = int(square[1])
    pos = file * 12 + rank
    value = board.cells[pos]
    if value == 0 or ((value >> 5) & 1) != side:
        raise ValueError(f"no expected side piece at {square}")
    index = value & 0x0F
    board.cells[pos] = 0
    board.pieces[side][index] = -1


def play(handicap: str, max_plies: int, movetime: int,
         out_html: str) -> dict:
    board = Board()
    for square in HANDICAPS[handicap]:
        remove_piece(board, square, BLACK)
    start = board.clone()
    rom_side = RED
    rom = QiWangEngine(depth=6, book=False, core="rust")
    pikafish = PikafishEngine(depth=10, movetime=movetime,
                              threads=1, hash_mb=64)
    seen = {}
    moves = []
    result, reason, winner = "unresolved", "ply limit", None
    rom_times = []
    try:
        for _ in range(max_plies):
            side = board.side_to_move
            legal = generate_legal_moves(board, side)
            if not legal:
                winner_side = 1 - side
                winner = "rom" if winner_side == rom_side else "pikafish"
                reason = "checkmate" if is_in_check(board, side) else "stalemate"
                result = f"{winner} wins"
                break
            started = time.perf_counter()
            if side == rom_side:
                move = rom.get_best_move(board)
                score = rom.evaluate(board)
                engine_name = "ROM depth 6"
            else:
                move = pikafish.search(board, side)
                score = pikafish.last_score
                engine_name = pikafish.name
            elapsed = time.perf_counter() - started
            if side == rom_side:
                rom_times.append(elapsed)
            if move not in legal:
                winner = "pikafish" if side == rom_side else "rom"
                result, reason = f"{winner} wins", "illegal move or resignation"
                break
            moves.append({
                "frm": move[0], "to": move[1],
                "side": "R" if side == RED else "B",
                "eng": "rom" if side == rom_side else "modern",
                "engname": engine_name, "text": describe(board, *move),
                "score": score, "t": round(elapsed, 3),
            })
            board.make_move(*move)
            key = (tuple(board.pieces[RED]), tuple(board.pieces[BLACK]),
                   board.side_to_move)
            seen[key] = seen.get(key, 0) + 1
            if seen[key] >= 3:
                result, reason = "draw", "threefold repetition"
                break
    finally:
        pikafish.close()

    removed = ", ".join(HANDICAPS[handicap])
    subtitle = (f"Pikafish 执黑让子 [{removed}] · 无铁兵等补偿规则 · "
                f"ROM depth 6 执红 · {len(moves)} ply")
    write_html(out_html, start, moves, pikafish.name, subtitle,
               f"{result}: {reason}")
    return {
        "handicap": handicap,
        "removed_black_squares": list(HANDICAPS[handicap]),
        "traditional_compensation_rules": False,
        "rom_side": "red",
        "result": result,
        "winner": winner,
        "reason": reason,
        "played_plies": len(moves),
        "rom_mean_seconds": sum(rom_times) / len(rom_times) if rom_times else 0.0,
        "moves": moves,
        "html": out_html,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--handicap", choices=tuple(HANDICAPS), required=True)
    parser.add_argument("--moves", type=int, default=160)
    parser.add_argument("--pf-movetime", type=int, default=10)
    parser.add_argument("--out", required=True)
    parser.add_argument("--json", required=True)
    args = parser.parse_args()
    result = play(args.handicap, args.moves, args.pf_movetime, args.out)
    Path(args.json).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items()
                      if key != "moves"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
