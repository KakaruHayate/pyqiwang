#!/usr/bin/env python3
"""Generate ROM-derived golden fixtures for native-search development.

This is an opt-in development tool. It requires the legally obtained ROM file
and never embeds ROM bytes in its output. The generated JSON contains board
piece lists, side to move, ROM PST evaluation and the ROM's best move.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
import sys

# Allow direct execution from tools/ without requiring an installed package.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pyqiwang import Board
from pyqiwang._board import evaluate_raw, generate_legal_moves, pos_to_notation
from pyqiwang._engine import QiWangEngine

FORMAT_VERSION = 1
DEFAULT_SEED = 20260727


def board_record(board: Board) -> dict:
    return {
        "red": list(board.pieces[0]),
        "black": list(board.pieces[1]),
        "side": board.side_to_move,
    }


def board_key(board: Board) -> tuple:
    return (tuple(board.pieces[0]), tuple(board.pieces[1]), board.side_to_move)


def make_positions(count: int, seed: int, min_plies: int,
                   max_plies: int) -> list[Board]:
    """Create independent deterministic positions rather than one game prefix."""
    rng = random.Random(seed)
    positions: list[Board] = []
    seen: set[tuple] = set()
    attempts = 0
    while len(positions) < count and attempts < count * 100:
        attempts += 1
        board = Board()
        target = rng.randint(min_plies, max_plies)
        for _ in range(target):
            legal = generate_legal_moves(board, board.side_to_move)
            if not legal:
                break
            board.make_move(*rng.choice(legal))
        key = board_key(board)
        if key in seen or not generate_legal_moves(board, board.side_to_move):
            continue
        board.move_history = []
        positions.append(board)
        seen.add(key)
    if len(positions) != count:
        raise RuntimeError(f"Could only create {len(positions)} unique positions")
    return positions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", required=True, type=Path,
                        help="Path to the FC QiWang .nes file")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--depth", type=int, default=1)
    parser.add_argument("--positions", type=int, default=16)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--min-plies", type=int, default=0)
    parser.add_argument("--max-plies", type=int, default=40)
    args = parser.parse_args()
    if args.min_plies < 0 or args.max_plies < args.min_plies:
        parser.error("require 0 <= min-plies <= max-plies")

    rom_bytes = args.rom.read_bytes()
    rom_hash = hashlib.sha256(rom_bytes).hexdigest()
    engine = QiWangEngine(rom_path=str(args.rom), depth=args.depth, book=False)

    cases = []
    positions = make_positions(
        args.positions, args.seed, args.min_plies, args.max_plies
    )
    for index, board in enumerate(positions):
        move = engine.get_best_move(board)
        cases.append({
            "id": f"random-{index:03d}",
            "board": board_record(board),
            "evaluation_raw": evaluate_raw(board),
            "best_move": list(move) if move is not None else None,
            "best_move_notation": (
                pos_to_notation(move[0]) + pos_to_notation(move[1])
                if move is not None else None
            ),
        })

    fixture = {
        "format": FORMAT_VERSION,
        "source": {
            "rom_sha256": rom_hash,
            "search_entry": "$8597",
            "evaluation_entry": "$8886",
            "depth": args.depth,
            "seed": args.seed,
            "sampling": "independent-random-playout",
            "min_plies": args.min_plies,
            "max_plies": args.max_plies,
        },
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(fixture, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(cases)} cases to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
