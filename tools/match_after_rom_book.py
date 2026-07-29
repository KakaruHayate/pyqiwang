#!/usr/bin/env python3
"""Play ROM depth 6 vs Pikafish after the full 33-ply ROM book line."""
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
from pyqiwang._board import generate_legal_moves, is_in_check, pos_to_notation
from modern_ai import PikafishEngine
from match import describe, write_html


def sq_move(move: tuple[int, int]) -> str:
    return pos_to_notation(move[0]) + pos_to_notation(move[1])


def build_book_position() -> tuple[Board, list[dict]]:
    source = QiWangEngine(depth=2, book=True, core="rust")
    board = Board()
    records = []
    while len(records) < 33 and source._book_applies(board):
        move = source.get_best_move(board)
        if move is None or move not in generate_legal_moves(board, board.side_to_move):
            raise RuntimeError(f"book failed at ply {len(records) + 1}: {move}")
        records.append({"ply": len(records) + 1, "move": sq_move(move)})
        board.make_move(*move)
    if len(records) != 33:
        raise RuntimeError(f"expected 33 book plies, got {len(records)}")
    return board, records


def play(rom_side: int, max_plies: int, movetime: int, out_html: str) -> dict:
    board, book = build_book_position()
    start = board.clone()
    rom = QiWangEngine(depth=6, book=False, core="rust")
    pikafish = PikafishEngine(depth=10, movetime=movetime, threads=1, hash_mb=64)
    seen = {}
    moves = []
    result = "unresolved"
    reason = "ply limit"
    winner = None
    rom_times = []
    try:
        for ply in range(max_plies):
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
                result = f"{winner} wins"
                reason = "illegal move or resignation"
                break
            text = describe(board, *move)
            moves.append({
                "frm": move[0], "to": move[1],
                "side": "R" if side == RED else "B",
                "eng": "rom" if side == rom_side else "modern",
                "engname": engine_name, "text": text,
                "score": score, "t": round(elapsed, 3),
            })
            board.make_move(*move)
            key = (tuple(board.pieces[RED]), tuple(board.pieces[BLACK]), board.side_to_move)
            seen[key] = seen.get(key, 0) + 1
            if seen[key] >= 3:
                result = "draw"
                reason = "threefold repetition"
                break
    finally:
        pikafish.close()

    subtitle = (f"完整 ROM 棋谱 33 ply 后接手 · ROM depth 6 执"
                f"{'红' if rom_side == RED else '黑'} · 接手后 {len(moves)} ply")
    write_html(out_html, start, moves, pikafish.name, subtitle, f"{result}: {reason}")
    return {
        "rom_side": "red" if rom_side == RED else "black",
        "book_plies": len(book),
        "book": book,
        "start_side": "red" if start.side_to_move == RED else "black",
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
    parser.add_argument("--rom-side", choices=("red", "black"), required=True)
    parser.add_argument("--moves", type=int, default=160)
    parser.add_argument("--pf-movetime", type=int, default=10)
    parser.add_argument("--out", required=True)
    parser.add_argument("--json", required=True)
    args = parser.parse_args()
    result = play(RED if args.rom_side == "red" else BLACK,
                  args.moves, args.pf_movetime, args.out)
    Path(args.json).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items()
                      if key not in ("book", "moves")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
