#!/usr/bin/env python3
"""Maximum-strength ROM runtime vs Pikafish match driver."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pyqiwang import BLACK, RED, Board, ElephantBook, ModernRomRuntime
from pyqiwang._board import generate_legal_moves, is_in_check
from modern_ai import PikafishEngine
from match import describe, write_html


class CandidateBook:
    def __init__(self, book: ElephantBook, choice: int = 0) -> None:
        self.book = book
        self.choice = choice
        self.hits = 0
        self.misses = 0

    def lookup(self, board: Board):
        candidates = self.book.candidates(board)
        if not candidates:
            self.misses += 1
            return None
        self.hits += 1
        return candidates[min(self.choice, len(candidates) - 1)][0]


def play(book_path: str, runtime_side: int, book_choice: int,
         max_plies: int, movetime: int, html: str) -> dict:
    board = Board()
    source_book = ElephantBook(book_path)
    chooser = CandidateBook(source_book, book_choice)
    runtime = ModernRomRuntime(
        base_depth=6, max_depth=7, core="rust",
        opening_lookup=chooser.lookup,
    )
    pikafish = PikafishEngine(depth=10, movetime=movetime,
                              threads=1, hash_mb=64)
    seen, moves = {}, []
    result, winner, reason = "unresolved", None, "ply limit"
    try:
        for _ in range(max_plies):
            side = board.side_to_move
            legal = generate_legal_moves(board, side)
            if not legal:
                winner_side = 1 - side
                winner = "rom" if winner_side == runtime_side else "pikafish"
                result = f"{winner} wins"
                reason = "checkmate" if is_in_check(board, side) else "stalemate"
                break
            started = time.perf_counter()
            if side == runtime_side:
                before_hits = chooser.hits
                depth = runtime.choose_depth(board)
                move = runtime.search(board, depth=depth)
                from_book = chooser.hits > before_hits
                score = runtime.engine.evaluate(board)
                name = "ElephantEye book" if from_book else f"ROM runtime depth {depth}"
                kind = "rom"
            else:
                from_book = False
                move = pikafish.search(board, side)
                depth = pikafish.last_depth
                score = pikafish.last_score
                name = pikafish.name
                kind = "modern"
            elapsed = time.perf_counter() - started
            if move not in legal:
                winner = "pikafish" if side == runtime_side else "rom"
                result, reason = f"{winner} wins", "illegal move or resignation"
                break
            moves.append({
                "frm": move[0], "to": move[1],
                "side": "R" if side == RED else "B", "eng": kind,
                "engname": name, "text": describe(board, *move),
                "score": score, "t": round(elapsed, 3),
                "depth": depth, "book": from_book,
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
    subtitle = (f"最大棋力：ElephantEye谱+ROM base6/max7 执"
                f"{'红' if runtime_side == RED else '黑'} · {len(moves)} ply")
    write_html(html, Board(), moves, pikafish.name, subtitle,
               f"{result}: {reason}")
    return {
        "runtime_side": "red" if runtime_side == RED else "black",
        "book_choice": book_choice,
        "result": result,
        "winner": winner,
        "reason": reason,
        "played_plies": len(moves),
        "book_hits": chooser.hits,
        "book_misses": chooser.misses,
        "runtime_stats": runtime.get_stats(),
        "moves": moves,
        "html": html,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--book", required=True)
    parser.add_argument("--runtime-side", choices=("red", "black"), required=True)
    parser.add_argument("--book-choice", type=int, default=0)
    parser.add_argument("--moves", type=int, default=160)
    parser.add_argument("--pf-movetime", type=int, default=10)
    parser.add_argument("--html", required=True)
    parser.add_argument("--json", required=True)
    args = parser.parse_args()
    row = play(args.book, RED if args.runtime_side == "red" else BLACK,
               args.book_choice, args.moves, args.pf_movetime, args.html)
    Path(args.json).write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in row.items() if key != "moves"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
