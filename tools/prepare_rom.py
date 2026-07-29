#!/usr/bin/env python3
"""Verify a known Qi Wang ROM and extract the 64KB runtime PRG locally."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pyqiwang._rom_image import RomImageError, extract_verified_prg, load_manifest


def main() -> int:
    manifest = load_manifest()
    parser = argparse.ArgumentParser(
        description="Verify the known-good Qi Wang iNES image and extract qiwang.prg"
    )
    parser.add_argument("source", help="path to the legally obtained .nes image")
    parser.add_argument(
        "--output",
        default="qiwang.prg",
        help="local output path (default: qiwang.prg)",
    )
    args = parser.parse_args()

    try:
        output = extract_verified_prg(args.source, args.output)
    except (OSError, RomImageError) as exc:
        parser.exit(1, f"error: {exc}\n")

    runtime = manifest["runtime"]
    print(f"Verified source ROM: {manifest['source']['sha256']}")
    print(f"Wrote runtime image: {Path(output).resolve()}")
    print(f"Runtime SHA-256: {runtime['sha256']}")
    print("The output is local and gitignored; do not redistribute it without permission.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
