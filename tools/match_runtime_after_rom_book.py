#!/usr/bin/env python3
"""Play ModernRomRuntime vs Pikafish after the full 33-ply ROM book."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pyqiwang import BLACK, RED, Board, ModernRomRuntime, QiWangEngine
from pyqiwang._board import generate_legal_moves, is_in_check
from modern_ai import PikafishEngine
from match import describe, write_html


def book_position() -> Board:
    board = Board()
    source = QiWangEngine(depth=2, book=True, core="rust")
    for ply in range(33):
        move = source.get_best_move(board)
        if move not in generate_legal_moves(board, board.side_to_move):
            raise RuntimeError(f"book failed at ply {ply + 1}: {move}")
        board.make_move(*move)
    return board


def play(runtime_side: int, max_plies: int, movetime: int, html: str) -> dict:
    board = book_position()
    start = board.clone()
    runtime = ModernRomRuntime(base_depth=5, max_depth=6, core="rust")
    pikafish = PikafishEngine(depth=10, movetime=movetime, threads=1, hash_mb=64)
    seen, moves = {}, []
    result, winner, reason = "unresolved", None, "ply limit"
    try:
        for _ in range(max_plies):
            side = board.side_to_move
            legal = generate_legal_moves(board, side)
            if not legal:
                winner_side = 1 - side
                winner = "runtime" if winner_side == runtime_side else "pikafish"
                result = f"{winner} wins"
                reason = "checkmate" if is_in_check(board, side) else "stalemate"
                break
            started = time.perf_counter()
            if side == runtime_side:
                depth = runtime.choose_depth(board)
                move = runtime.search(board, depth=depth)
                score = runtime.engine.evaluate(board)
                name = f"ModernRomRuntime depth {depth}"
                kind = "rom"
            else:
                depth = pikafish.last_depth
                move = pikafish.search(board, side)
                score = pikafish.last_score
                name = pikafish.name
                kind = "modern"
            elapsed = time.perf_counter() - started
            if move not in legal:
                winner = "pikafish" if side == runtime_side else "runtime"
                result, reason = f"{winner} wins", "illegal move or resignation"
                break
            moves.append({
                "frm": move[0], "to": move[1],
                "side": "R" if side == RED else "B", "eng": kind,
                "engname": name, "text": describe(board, *move),
                "score": score, "t": round(elapsed, 3), "depth": depth,
            })
            board.make_move(*move)
            key = (tuple(board.pieces[RED]), tuple(board.pieces[BLACK]), board.side_to_move)
            seen[key] = seen.get(key, 0) + 1
            if seen[key] >= 3:
                result, reason = "draw", "threefold repetition"
                break
    finally:
        pikafish.close()
    subtitle = (f"完整ROM棋谱33 ply后 · ModernRomRuntime执"
                f"{'红' if runtime_side == RED else '黑'} · 接手后{len(moves)} ply")
    write_html(html, start, moves, pikafish.name, subtitle, f"{result}: {reason}")
    return {
        "runtime_side": "red" if runtime_side == RED else "black",
        "book_plies": 33,
        "result": result,
        "winner": winner,
        "reason": reason,
        "played_plies": len(moves),
        "runtime_stats": runtime.get_stats(),
        "moves": moves,
        "html": html,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-side", choices=("red", "black"), required=True)
    parser.add_argument("--moves", type=int, default=160)
    parser.add_argument("--pf-movetime", type=int, default=10)
    parser.add_argument("--html", required=True)
    parser.add_argument("--json", required=True)
    args = parser.parse_args()
    row = play(RED if args.runtime_side == "red" else BLACK,
               args.moves, args.pf_movetime, args.html)
    Path(args.json).write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in row.items() if key != "moves"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
