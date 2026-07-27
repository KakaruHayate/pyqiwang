#!/usr/bin/env python3
"""Print FC QiWang search regions from known instruction boundaries."""
from __future__ import annotations

from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pyqiwang._harness import RomHarness, disasm_one

REGIONS = (
    (0xA211, 0xA400),
    (0x92AF, 0x94A0),
    (0xB1FB, 0xB350),
    (0xB298, 0xB3A0),
    (0xB392, 0xB500),
    (0xB583, 0xB700),
    (0xB607, 0xB780),
)


def main() -> int:
    rom = _REPO_ROOT / "棋王(繁)[小天才](CN)[TAB](0.75Mb).nes"
    harness = RomHarness(str(rom))
    harness.bus.prg_bank = 1
    for start, end in REGIONS:
        print(f"\n--- ${start:04X} ---")
        pc = start
        while pc < end:
            line, size = disasm_one(harness.bus, pc)
            print(line)
            pc += size
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
