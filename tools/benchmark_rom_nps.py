#!/usr/bin/env python3
"""Measure ROM search entry rate and compare it with Pikafish UCI NPS."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pyqiwang import Board, QiWangEngine
from modern_ai import board_to_fen, find_pikafish

# In the active program bank, the repeatedly entered recursive search frame is
# $8FB4. $CE9E belongs to the alternate/book bank and is not executed by $8597.
NODE_PC = 0x8FB4


def budget(depth: int) -> int:
    if depth <= 4:
        return 200_000_000
    if depth == 5:
        return 1_000_000_000
    if depth == 6:
        return 16_000_000_000
    return 2_000_000_000 * (8 ** (depth - 6))


def rom_measure(depth: int) -> dict:
    engine = QiWangEngine(depth=depth, core="rust", book=False)
    board = Board()
    engine._sync_board_to_rom(board)
    started = time.perf_counter()
    instructions, entries = engine.harness.call_subroutine_count_pc(
        0x8597, NODE_PC, a=depth, max_instructions=budget(depth))
    elapsed = time.perf_counter() - started
    move = (engine.harness.rd(0xC0), engine.harness.rd(0xC1))
    return {
        "engine": "ROM",
        "depth": depth,
        "node_definition": "entries at active-bank recursive search frame $8FB4",
        "node_pc": f"${NODE_PC:04X}",
        "move": move,
        "seconds": elapsed,
        "nodes": entries,
        "nps": entries / elapsed if elapsed else 0,
        "instructions": instructions,
        "instructions_per_second": instructions / elapsed if elapsed else 0,
        "instructions_per_node": instructions / entries if entries else 0,
    }


def pikafish_measure(depth: int) -> dict:
    path = find_pikafish()
    if not path:
        raise FileNotFoundError("Pikafish not found")
    proc = subprocess.Popen(
        [path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, bufsize=1,
        cwd=str(Path(path).parent),
    )
    def send(command: str) -> None:
        proc.stdin.write(command + "\n")
        proc.stdin.flush()
    try:
        send("uci")
        for line in proc.stdout:
            if line.startswith("uciok"):
                break
        send("setoption name Threads value 1")
        send("setoption name Hash value 64")
        send("isready")
        for line in proc.stdout:
            if line.startswith("readyok"):
                break
        send(f"position fen {board_to_fen(Board(), 0)}")
        started = time.perf_counter()
        send(f"go depth {depth}")
        info = None
        bestmove = None
        for line in proc.stdout:
            text = line.strip()
            if text.startswith("info ") and " nodes " in text:
                info = text.split()
            if text.startswith("bestmove"):
                bestmove = text.split()[1]
                break
        elapsed = time.perf_counter() - started
        if info is None:
            raise RuntimeError("Pikafish produced no node information")
        def value(name: str, default=0):
            return int(info[info.index(name) + 1]) if name in info else default
        return {
            "engine": "Pikafish",
            "depth": value("depth", depth),
            "node_definition": "Pikafish UCI nodes",
            "move": bestmove,
            "seconds": elapsed,
            "reported_time_ms": value("time"),
            "nodes": value("nodes"),
            "nps": value("nps"),
        }
    finally:
        try:
            send("quit")
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom-depths", type=int, nargs="+", default=[4, 5, 6])
    parser.add_argument("--pikafish-depths", type=int, nargs="+", default=[10, 12, 16])
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    report = {"rom": [], "pikafish": []}
    for depth in args.rom_depths:
        row = rom_measure(depth)
        report["rom"].append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    for depth in args.pikafish_depths:
        row = pikafish_measure(depth)
        report["pikafish"].append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    if args.out:
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
