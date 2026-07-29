#!/usr/bin/env python3
"""Differential checks for the optional compiled 6502 core."""
from __future__ import annotations

import argparse
import random
import time

from pyqiwang import Board, QiWangEngine, generate_legal_moves
from pyqiwang._fast6502 import Fast6502Unavailable, find_fast6502_library
from pyqiwang._harness import RomHarness


def _cpu_state(harness: RomHarness) -> tuple:
    cpu, bus = harness.cpu, harness.bus
    return (
        cpu.a, cpu.x, cpu.y, cpu.sp, cpu.pc, cpu.p, cpu.cycles,
        bus.prg_bank, bus.open_bus, bus.reg4100, bus.ppustatus_toggle,
        bus.pad1, bus._pad1_shift, bus._pad_strobe,
        bytes(bus.ram),
    )


def _fresh_pair() -> tuple[RomHarness, RomHarness]:
    return RomHarness(core="python"), RomHarness(core="rust")


def test_boot_state() -> None:
    python, rust = _fresh_pair()
    python.boot()
    rust.boot()
    assert _cpu_state(rust) == _cpu_state(python)


def test_instruction_checkpoints() -> None:
    python, rust = _fresh_pair()
    for checkpoint in (1, 17, 100, 1_003, 10_007):
        for _ in range(checkpoint):
            python.cpu.step()
        for _ in range(checkpoint):
            rust.fast_runner.step(rust.cpu, rust.bus)
        assert _cpu_state(rust) == _cpu_state(python), checkpoint


def test_rom_subroutines() -> None:
    python, rust = _fresh_pair()
    for harness in (python, rust):
        harness.boot()
        harness.init_board()
        harness.new_game(side_to_move=0x10, book=False)
        harness.call_subroutine(0x8886)
    assert _cpu_state(rust) == _cpu_state(python)


def test_hook_fallback() -> None:
    harness = RomHarness(core="rust")
    hits = []
    harness.cpu.reset()
    reset_pc = harness.cpu.pc
    harness.run_until(
        0xd019,
        max_instructions=5_000_000,
        pc_hooks={reset_pc: lambda: hits.append(harness.cpu.pc)},
    )
    assert harness.core == "rust"
    assert harness.cpu.pc == 0xd019
    assert hits == [reset_pc]


def test_opening_book_nmi() -> None:
    python = QiWangEngine(depth=1, book=True, core="python")
    rust = QiWangEngine(depth=1, book=True, core="rust")
    python_move = python.get_best_move(Board())
    rust_move = rust.get_best_move(Board())
    assert rust_move == python_move
    assert _cpu_state(rust.harness) == _cpu_state(python.harness)


def _random_board(seed: int, plies: int) -> Board:
    rng = random.Random(seed)
    board = Board()
    for _ in range(plies):
        legal = generate_legal_moves(board, board.side_to_move)
        if not legal:
            break
        board.make_move(*rng.choice(legal))
    return board


def test_random_search_states(depth: int, positions: int = 4) -> None:
    python = QiWangEngine(depth=depth, core="python")
    rust = QiWangEngine(depth=depth, core="rust")
    for index in range(positions):
        board = _random_board(20260729 + index, 7 + index * 5)
        python_move = python.get_best_move(board)
        rust_move = rust.get_best_move(board)
        assert rust_move == python_move, (depth, index, python_move, rust_move)
        assert _cpu_state(rust.harness) == _cpu_state(python.harness), (depth, index)


def test_search_state(depth: int = 1) -> None:
    python = QiWangEngine(depth=depth, core="python")
    rust = QiWangEngine(depth=depth, core="rust")
    board = Board()
    python_start = python.harness.instr_count
    rust_start = rust.harness.instr_count
    python_move = python.get_best_move(board)
    rust_move = rust.get_best_move(board)
    assert rust_move == python_move
    assert _cpu_state(rust.harness) == _cpu_state(python.harness)
    assert rust.harness.instr_count - rust_start == python.harness.instr_count - python_start


def benchmark(depth: int, rounds: int) -> None:
    results = {}
    for core in ("python", "rust"):
        engine = QiWangEngine(depth=depth, core=core)
        board = Board()
        start_count = engine.harness.instr_count
        start = time.perf_counter()
        move = None
        for _ in range(rounds):
            move = engine.get_best_move(board)
        elapsed = time.perf_counter() - start
        instructions = engine.harness.instr_count - start_count
        results[core] = elapsed
        print(
            f"{core:6s}: move={move} seconds={elapsed:.6f} "
            f"instructions={instructions} ips={instructions / elapsed:,.0f}"
        )
    print(f"speedup: {results['python'] / results['rust']:.2f}x")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", action="store_true")
    parser.add_argument("--depth", type=int, default=1)
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args()
    if find_fast6502_library() is None:
        print("SKIP: compiled fast6502 library is not built")
        return 0
    try:
        test_instruction_checkpoints()
        test_boot_state()
        test_rom_subroutines()
        test_hook_fallback()
        test_opening_book_nmi()
        test_search_state(args.depth)
        test_random_search_states(args.depth)
    except Fast6502Unavailable as exc:
        print(f"SKIP: {exc}")
        return 0
    print("fast6502 differential tests: PASS")
    if args.benchmark:
        benchmark(args.depth, args.rounds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
