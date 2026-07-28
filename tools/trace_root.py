#!/usr/bin/env python3
"""Trace FC QiWang ROM root candidates for a stored golden position."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pyqiwang import BLACK, RED, Board, QiWangEngine, pos_to_notation
from pyqiwang._harness import SENTINEL, disasm_one
from pyqiwang._mos6502 import FLAG_C, FLAG_N, FLAG_V, FLAG_Z


def board_from_record(record: dict) -> Board:
    board = Board()
    board.pieces[RED] = list(record["red"])
    board.pieces[BLACK] = list(record["black"])
    board.side_to_move = int(record["side"])
    board.move_history = []
    board._init_board()
    return board


def trace_root(engine: QiWangEngine, board: Board, depth: int,
               focus_moves: set[tuple[int, int]] | None = None,
               instruction_trace_min_level: int | None = None) -> dict:
    engine._sync_board_to_rom(board)
    harness = engine.harness
    cpu = harness.cpu
    attempts: list[dict] = []
    current: dict | None = None
    max_level = 0
    current_max_level = 0
    current_level_counts: dict[int, int] = {}
    current_events: list[dict] = []
    instruction_trace: list[dict] = []

    def start_candidate() -> None:
        nonlocal current, current_max_level, current_level_counts, current_events
        if harness.rd(0xC6) != 0:
            return
        current_max_level = 0
        current_level_counts = {}
        current_events = []
        current = {
            "move": [harness.rd(0xC0), harness.rd(0xC1)],
            "iteration": harness.rd(0xCF),
            "static_before_raw": harness.rd(0xC8) | (harness.rd(0xC9) << 8),
        }

    def compare_candidate() -> None:
        nonlocal current
        if harness.rd(0xC6) != 0:
            return
        if current is None:
            start_candidate()
        current["score_raw"] = harness.rd(0x0773) | (harness.rd(0x07F3) << 8)
        current["best_before_raw"] = harness.rd(0x0772) | (harness.rd(0x07F2) << 8)
        current["side"] = board.side_to_move

    def finish_candidate() -> None:
        nonlocal current
        if current is None:
            return
        current["best_after_raw"] = harness.rd(0x0772) | (harness.rd(0x07F2) << 8)
        current["best_move_after"] = [harness.rd(0x0400), harness.rd(0x0408)]
        current["max_internal_level"] = current_max_level
        current["level_counts"] = {
            str(level): count
            for level, count in sorted(current_level_counts.items())
        }
        if current_events:
            current["events"] = current_events
        attempts.append(current)
        current = None

    def record_level() -> None:
        nonlocal max_level, current_max_level
        level = harness.rd(0xC6)
        max_level = max(max_level, level)
        current_max_level = max(current_max_level, level)
        current_level_counts[level] = current_level_counts.get(level, 0) + 1

    def read_u16(lo_base: int, hi_base: int, index: int) -> int:
        return harness.rd(lo_base + index) | (harness.rd(hi_base + index) << 8)

    def flags() -> dict[str, int]:
        return {
            "c": int(cpu.get_flag(FLAG_C)),
            "z": int(cpu.get_flag(FLAG_Z)),
            "n": int(cpu.get_flag(FLAG_N)),
            "v": int(cpu.get_flag(FLAG_V)),
        }

    def branch_state(pc: int) -> dict | None:
        opcode = harness.rd(pc)
        conditions = {
            0x10: not cpu.get_flag(FLAG_N),
            0x30: cpu.get_flag(FLAG_N),
            0x50: not cpu.get_flag(FLAG_V),
            0x70: cpu.get_flag(FLAG_V),
            0x90: not cpu.get_flag(FLAG_C),
            0xB0: cpu.get_flag(FLAG_C),
            0xD0: not cpu.get_flag(FLAG_Z),
            0xF0: cpu.get_flag(FLAG_Z),
        }
        if opcode not in conditions:
            return None
        offset = harness.rd(pc + 1)
        if offset & 0x80:
            offset -= 0x100
        return {
            "taken": bool(conditions[opcode]),
            "target": (pc + 2 + offset) & 0xFFFF,
            "fallthrough": (pc + 2) & 0xFFFF,
        }

    def is_focused() -> bool:
        if current is None:
            return False
        return focus_moves is None or tuple(current["move"]) in focus_moves

    def record_instruction() -> None:
        if instruction_trace_min_level is None or not is_focused():
            return
        level = harness.rd(0xC6)
        if level < instruction_trace_min_level:
            return
        pc = cpu.pc
        if not (0x92AF <= pc < 0x9400 or 0xA211 <= pc < 0xA400 or
                0xB1FB <= pc < 0xB900):
            return
        disassembly, _ = disasm_one(harness.bus, pc)
        instruction_trace.append({
            "pc": pc,
            "instruction": disassembly,
            "level": level,
            "move": [harness.rd(0xC0), harness.rd(0xC1)],
            "a": cpu.a,
            "x": cpu.x,
            "y": cpu.y,
            "p": cpu.p,
            "cf": harness.rd(0xCF),
            "selector": harness.rd(0x05F2 + level),
            "score_raw": harness.rd(0xC8) | (harness.rd(0xC9) << 8),
            "bound_raw": read_u16(0x0672, 0x06F2, level),
            "best_raw": read_u16(0x0772, 0x07F2, level),
        })

    def search_state(index: int) -> dict[str, int] | None:
        if not 0 <= index < 0x80:
            return None
        return {
            "bound_raw": read_u16(0x0672, 0x06F2, index),
            "previous_bound_raw": read_u16(0x0671, 0x06F1, index),
            "best_raw": read_u16(0x0772, 0x07F2, index),
            "child_raw": read_u16(0x0773, 0x07F3, index),
            "selector": harness.rd(0x05F2 + index),
            "history_move": [harness.rd(0x0490 + index),
                             harness.rd(0x0498 + index)],
            "previous_history_move": [harness.rd(0x04A0 + index),
                                      harness.rd(0x04A8 + index)],
            "saved_stack_pointer": harness.rd(0x0572 + index),
        }

    def record_event(name: str) -> None:
        if current is None:
            return
        root_move = tuple(current["move"])
        if focus_moves is not None and root_move not in focus_moves:
            return
        level = harness.rd(0xC6)
        index = cpu.x
        disassembly, _ = disasm_one(harness.bus, cpu.pc)
        event = {
            "event": name,
            "pc": cpu.pc,
            "instruction": disassembly,
            "registers": {
                "a": cpu.a,
                "x": cpu.x,
                "y": cpu.y,
                "sp": cpu.sp,
                "p": cpu.p,
            },
            "flags": flags(),
            "level": level,
            "index": index,
            "move": [harness.rd(0xC0), harness.rd(0xC1)],
            "generator_target": cpu.x if cpu.pc in (0x8DC7, 0x903B) else None,
            "score_raw": harness.rd(0xC8) | (harness.rd(0xC9) << 8),
            "parent_level_state": search_state(level - 1),
            "level_state": search_state(level),
            "child_level_state": search_state(level + 1),
            "index_state": search_state(index),
            "ce": harness.rd(0xCE),
            "cf": harness.rd(0xCF),
        }
        branch = branch_state(cpu.pc)
        if branch is not None:
            event["branch"] = branch
        current_events.append(event)

    cpu.a = depth & 0xFF
    cpu.push16((SENTINEL - 1) & 0xFFFF)
    cpu.pc = 0x8597
    pc_hooks = {
        0x86F3: start_candidate,
        0x86CD: finish_candidate,
        0x86E8: finish_candidate,
        0xA211: lambda: (record_level(), record_event("red_node")),
        0xA217: lambda: record_event("red_node_seed_best"),
        0x92AF: lambda: (record_level(), record_event("black_node")),
        0x92B5: lambda: record_event("black_node_seed_best"),
        0xB607: lambda: record_event("try_entry_b607"),
        0xB583: lambda: record_event("try_entry_b583"),
        0xB27F: lambda: record_event("try_entry_b27f"),
        0xB25B: lambda: record_event("try_entry_b25b"),
        0xB281: lambda: record_event("try_entry_b25b_after_dedup"),
        0xB1FB: lambda: record_event("try_entry_b1fb"),
        0xB5E3: lambda: record_event("try_entry_b5e3"),
        # Red-node static-score bound gates.
        0xA268: lambda: record_event("red_static_iteration_gate"),
        0xA26C: lambda: record_event("red_static_vs_bound_begin"),
        0xA277: lambda: record_event("red_static_vs_bound_branch"),
        0xA279: lambda: record_event("red_previous_bound_begin"),
        0xA284: lambda: record_event("red_previous_bound_branch"),
        0xA290: lambda: record_event("red_store_best"),
        0xA29C: lambda: record_event("red_selector_set_negative"),
        0xA326: lambda: record_event("red_selector_finish_primary_history"),
        0xA35D: lambda: record_event("red_selector_finish_secondary_history"),
        0xA360: lambda: record_event("red_selector_finish_directed_scan"),
        0xA40E: lambda: record_event("red_selector_to_fullwidth_gate"),
        0xA41C: lambda: record_event("red_fullwidth_begin"),
        0x903B: lambda: record_event("red_selector_table_generator"),
        # Black-node static-score bound gates.
        0x9305: lambda: record_event("black_static_iteration_gate"),
        0x9309: lambda: record_event("black_bound_vs_static_begin"),
        0x9314: lambda: record_event("black_bound_vs_static_branch"),
        0x9316: lambda: record_event("black_static_vs_previous_bound_begin"),
        0x9321: lambda: record_event("black_static_vs_previous_bound_branch"),
        0x932D: lambda: record_event("black_store_best"),
        0x9339: lambda: record_event("black_selector_set_negative"),
        0x93C3: lambda: record_event("black_selector_finish_primary_history"),
        0x93FA: lambda: record_event("black_selector_finish_secondary_history"),
        0x93FD: lambda: record_event("black_selector_finish_directed_scan"),
        0x94AB: lambda: record_event("black_selector_to_fullwidth_gate"),
        0x94B9: lambda: record_event("black_fullwidth_begin"),
        0x8DC7: lambda: record_event("black_selector_table_generator"),
        # Per-level null-window seed and post-move incremental PST state.
        0xB29C: lambda: record_event("red_seed_entry_compare_best_active"),
        0xB2A9: lambda: record_event("red_seed_entry_compare_branch"),
        0xB298: lambda: record_event("red_seed_entry_fallback_alt"),
        0xB2AB: lambda: record_event("red_seed_child_bound_plus_one"),
        0xB2BC: lambda: record_event("red_save_parent_state"),
        0xB2D9: lambda: record_event("red_capture_detected"),
        0xB2FD: lambda: record_event("red_after_capture_score_update"),
        0xB329: lambda: record_event("red_post_move_score"),
        0xB346: lambda: record_event("red_child_recurse_gate_branch"),
        0xB348: lambda: record_event("red_before_child_recurse"),
        0xB36A: lambda: record_event("red_seed_restore_without_research"),
        0xB624: lambda: record_event("black_seed_entry_compare_active_best"),
        0xB631: lambda: record_event("black_seed_entry_compare_branch"),
        0xB620: lambda: record_event("black_seed_entry_fallback_alt"),
        0xB633: lambda: record_event("black_seed_child_bound_minus_one"),
        0xB644: lambda: record_event("black_save_parent_state"),
        0xB661: lambda: record_event("black_capture_detected"),
        0xB685: lambda: record_event("black_after_capture_score_update"),
        0xB6B1: lambda: record_event("black_post_move_score"),
        0xB6CE: lambda: record_event("black_child_recurse_gate_branch"),
        0xB6D0: lambda: record_event("black_before_child_recurse"),
        0xB6F2: lambda: record_event("black_seed_restore_without_research"),
        # Alternate recursive path used by random-015. These paths copy the
        # adjacent-level bound instead of seeding bound +/- 1.
        0xB392: lambda: record_event("red_alt_save_move_state"),
        0xB424: lambda: record_event("red_copy_adjacent_bound"),
        0xB435: lambda: record_event("red_alt_recurse"),
        0xB466: lambda: (compare_candidate(), record_event("red_alt_compare_child_best")),
        0xB477: lambda: record_event("red_alt_update_best"),
        0xB4A7: lambda: record_event("red_alt_bound_vs_best_begin"),
        0xB4B4: lambda: record_event("red_alt_bound_vs_best_branch"),
        0xB4B8: lambda: record_event("red_alt_best_vs_previous_bound_begin"),
        0xB4C5: lambda: record_event("red_alt_best_vs_previous_bound_branch"),
        0xB4C7: lambda: record_event("red_alt_raise_bound_to_best"),
        0xB4D5: lambda: record_event("red_alt_selector_dispatch"),
        0xB4DC: lambda: record_event("red_alt_selector_negative_branch"),
        0xB4DE: lambda: record_event("red_alt_selector_zero_branch"),
        0xB4F7: lambda: record_event("red_alt_rotate_history"),
        0xB503: lambda: record_event("red_alt_store_history"),
        0xB50D: lambda: record_event("red_alt_restore_stack"),
        0xB71A: lambda: record_event("black_alt_save_move_state"),
        0xB7AC: lambda: record_event("black_copy_adjacent_bound"),
        0xB7BD: lambda: record_event("black_alt_recurse"),
        0xB7EE: lambda: (compare_candidate(), record_event("black_alt_compare_child_best")),
        0xB7FF: lambda: record_event("black_alt_update_best"),
        0xB82F: lambda: record_event("black_alt_best_vs_bound_begin"),
        0xB83C: lambda: record_event("black_alt_best_vs_bound_branch"),
        0xB840: lambda: record_event("black_alt_previous_bound_vs_best_begin"),
        0xB84D: lambda: record_event("black_alt_previous_bound_vs_best_branch"),
        0xB84F: lambda: record_event("black_alt_lower_bound_to_best"),
        0xB85D: lambda: record_event("black_alt_selector_dispatch"),
        0xB864: lambda: record_event("black_alt_selector_negative_branch"),
        0xB866: lambda: record_event("black_alt_selector_zero_branch"),
        0xB87F: lambda: record_event("black_alt_rotate_history"),
        0xB88B: lambda: record_event("black_alt_store_history"),
        0xB895: lambda: record_event("black_alt_restore_stack"),
        # Child-return bound gates in the two symmetric try-move paths.
        0xB350: lambda: record_event("red_child_return"),
        0xB357: lambda: record_event("red_bound_vs_child_begin"),
        0xB364: lambda: record_event("red_bound_vs_child_branch"),
        0xB6D8: lambda: record_event("black_child_return"),
        0xB6DF: lambda: record_event("black_child_vs_bound_begin"),
        0xB6EC: lambda: record_event("black_child_vs_bound_branch"),
    }
    executed = 0
    while executed < 200_000_000:
        if cpu.pc == SENTINEL:
            break
        callback = pc_hooks.get(cpu.pc)
        if callback is not None:
            callback()
        record_instruction()
        cpu.step()
        executed += 1
        harness.instr_count += 1
    else:
        raise TimeoutError(
            f"Search did not reach sentinel after {executed} instructions "
            f"(PC=${cpu.pc:04X})"
        )
    result = [harness.rd(0xC0), harness.rd(0xC1)]
    trace = {
        "result": result,
        "result_notation": pos_to_notation(result[0]) + pos_to_notation(result[1]),
        "candidate_count": harness.rd(0x0500),
        "max_internal_level": max_level,
        "attempts": attempts,
    }
    if instruction_trace:
        trace["instruction_trace"] = instruction_trace
    return trace


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--case", default="random-000")
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--depth", type=int, default=1)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--focus-move",
        action="append",
        default=[],
        help="Record detailed events only for FROM,TO (repeatable)",
    )
    parser.add_argument(
        "--instruction-trace-min-level",
        type=int,
        help="Record every search-region instruction at or above this level",
    )
    args = parser.parse_args()

    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    case = next((item for item in fixture["cases"] if item["id"] == args.case), None)
    if case is None:
        raise SystemExit(f"Unknown fixture case: {args.case}")
    board = board_from_record(case["board"])
    engine = QiWangEngine(rom_path=str(args.rom), depth=args.depth, book=False)
    focus_moves = {
        tuple(map(int, item.split(",")))
        for item in args.focus_move
    } or None
    result = {
        "case": args.case,
        "expected": case["best_move"],
        "trace": trace_root(
            engine,
            board,
            args.depth,
            focus_moves,
            args.instruction_trace_min_level,
        ),
    }
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"Wrote root trace to {args.output}")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
