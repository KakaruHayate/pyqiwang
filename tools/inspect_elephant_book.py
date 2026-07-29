#!/usr/bin/env python3
"""Inspect a user-supplied ElephantEye BOOK.DAT with pyqiwang positions."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pyqiwang import Board
from pyqiwang.elephant_book import ElephantBook


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("book", help="path to ElephantEye BOOK.DAT")
    args = parser.parse_args()
    book = ElephantBook(args.book)
    candidates = book.candidates(Board())
    print(json.dumps({
        "records": book.stats()["records"],
        "initial_candidates": [
            {"move": list(move), "weight": weight}
            for move, weight in candidates
        ],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
