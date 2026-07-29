#!/usr/bin/env python3
"""Compare the Python and optional Rust ROM execution cores."""
from __future__ import annotations

import argparse
import time

from pyqiwang import Board, QiWangEngine
from pyqiwang._fast6502 import find_fast6502_library


def measure(core: str, depth: int, rounds: int) -> dict:
    engine = QiWangEngine(depth=depth, core=core)
    board = Board()
    start_count = engine.harness.instr_count
    start = time.perf_counter()
    move = None
    for _ in range(rounds):
        move = engine.get_best_move(board)
    elapsed = time.perf_counter() - start
    instructions = engine.harness.instr_count - start_count
    return {
        "core": engine.execution_core,
        "move": move,
        "seconds": elapsed,
        "instructions": instructions,
        "ips": instructions / elapsed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--depth", type=int, default=1)
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args()
    cores = ["python"]
    if find_fast6502_library() is not None:
        cores.append("rust")
    results = [measure(core, args.depth, args.rounds) for core in cores]
    for result in results:
        print(
            f"{result['core']:6s}: move={result['move']} "
            f"seconds={result['seconds']:.6f} "
            f"instructions={result['instructions']} "
            f"ips={result['ips']:,.0f}"
        )
    if len(results) == 2:
        assert results[0]["move"] == results[1]["move"]
        print(f"speedup: {results[0]['seconds'] / results[1]['seconds']:.2f}x")
    else:
        print("Rust core not built; Python baseline only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
