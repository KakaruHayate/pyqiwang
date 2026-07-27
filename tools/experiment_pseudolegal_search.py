#!/usr/bin/env python3
"""Measure parity when Native internal search uses ROM-style pseudo-legal moves."""
from __future__ import annotations

import json
from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pyqiwang._native as native
from pyqiwang._board import generate_moves
from tools.trace_native_root import board_from_record

CORPORA = [
    ("depth1-golden", "rom_depth1_golden.json", 1),
    ("depth1-independent", "rom_depth1_independent.json", 1),
    ("depth2-independent", "rom_depth2_independent.json", 2),
]


def main() -> int:
    fixture_dir = _REPO_ROOT / "tests" / "fixtures"
    native.is_in_check = lambda board, side: False
    native.generate_legal_moves = generate_moves

    for name, filename, depth in CORPORA:
        data = json.loads((fixture_dir / filename).read_text(encoding="utf-8"))
        rows = []
        for case in data["cases"]:
            want = tuple(case["best_move"]) if case["best_move"] else None
            engine = native.NativeQiWangEngine(depth=depth, book=False)
            got = engine.get_best_move(board_from_record(case["board"]))
            rows.append((case["id"], want, got))
        mismatches = [row for row in rows if row[1] != row[2]]
        print(f"{name}: {len(rows) - len(mismatches)}/{len(rows)}")
        for row in mismatches:
            print(f"  {row[0]}: ROM={row[1]} Native={row[2]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
