# pyqiwang — Chinese Chess AI Engine (100% ROM-faithful)

Reverse-engineered AI from the FC game **棋王** (Chess King). Uses a 6502 CPU emulator
to run the ROM's native search subroutine, achieving **100% move fidelity** with the original.

## Features

- **100% faithful AI** — runs the ROM's `$8597` search through a Python 6502 emulator
- **PST evaluation tables** — extracted directly from ROM `$8886` via dynamic trace
- **Clean Python API** — ready for training, baselines, and knowledge distillation
- **Zero external dependencies** — pure Python (3.14+)

## Install

```bash
git clone https://github.com/KakaruHayate/pyqiwang.git
cd pyqiwang
```

Place the ROM file `棋王(繁)[小天才](CN)[TAB](0.75Mb).nes` in the project root.

## Quick Start

```python
from pyqiwang import QiWangEngine, Board, RED, BLACK

# Initialize engine (loads ROM automatically)
engine = QiWangEngine(depth=2)

# Create a board and get the best move
board = Board()
move = engine.get_best_move(board)
# Returns (from_pos, to_pos) where pos = file * 12 + rank

# Execute the move in engine state
engine.make_move(board, *move)

# Analyze a position
info = engine.analyze(board)
# info = {'move': (frm, to), 'score': int, 'depth': int, 'elapsed': float, ...}

# Evaluate a position
score = engine.evaluate(board)  # positive = advantage for side to move
```

## CLI

```bash
# Interactive game (play against the AI)
python -m pyqiwang --depth 2

# Play as Black
python -m pyqiwang --depth 3 --side black

# Auto-play demo (AI vs AI)
python -m pyqiwang --demo
```

## API Reference

### `QiWangEngine`

| Method | Description |
|--------|-------------|
| `QiWangEngine(rom_path=None, depth=2, book=False)` | Initialize engine. ROM auto-detected if not specified. `book=True` enables the ROM's opening book. |
| `get_best_move(board=None) → (int, int) \| None` | Best move for current side. |
| `make_move(board=None, frm, to) → bool` | Execute move in ROM state. |
| `evaluate(board=None) → int` | Position evaluation (positive = good for side to move). |
| `analyze(board=None) → dict` | Full search info: move, score, depth, elapsed. |
| `get_legal_moves(board=None) → list[(int, int)]` | All legal moves. |
| `play_auto(max_moves=200, verbose=True) → str` | Auto-play both sides (for training). |
| `reset()` | Reset to initial position. |

### `Board`

| Method | Description |
|--------|-------------|
| `Board()` | Create board in initial position. |
| `make_move(frm, to)` | Execute move on Python board. |
| `undo_move()` | Take back last move. |
| `clone()` | Deep copy. |
| `pos_to_coord(pos) → (file, rank)` | Convert position to coordinates. |
| `coord_to_pos(file, rank) → int` | Convert coordinates to position. |
| `is_valid_pos(pos) → bool` | Check if position is on the board. |
| `get_side(pos) → int \| None` | Which side occupies a position. |

### Constants

```python
RED = 0    # 红方
BLACK = 1  # 黑方
KING, ADVISOR, ELEPHANT, ROOK, KNIGHT, CANNON, PAWN
PIECE_NAMES, PIECE_NAMES_BLACK, PIECE_TYPES
BOARD_STRIDE = 12  # pos = file * 12 + rank
```

## How It Works

```
Python Board  ←→  Engine sync
                          ↓
                  _harness.py (ROM interface)
                          ↓
                  _mos6502.py (6502 CPU emulator)
                          ↓
        ROM $CD26 opening book  →  ROM $8597 search (native)
                          ↓
              $C0/$C1: best move returned
```

This mirrors the ROM's own move path at `$D1DA`/`$D1E7`: consult the book
first, fall through to the search when it doesn't apply.

1. The Python `Board` state is written to ROM zero-page RAM
2. The 6502 emulator executes the ROM's `$8597` subroutine
3. The ROM generates candidates via `$8701`, runs alpha-beta search via `$CE9E`
4. The best move is read back from `$C0/$C1`
5. All evaluation uses the ROM's 14 PST tables from `$8886`

## What is reproduced

The AI's **move selection** is faithful by construction — `$8597` is the
ROM's own code, executed instruction by instruction. Verified further:

* `get_best_move()` is a **pure function of the board**: asking for a
  position on a fresh engine, after other searches, or after searching the
  same set in reverse order all give identical moves (12/12 positions).
* Instrumenting every RAM read-before-write during a search gives 163
  dependency addresses. All but ten are set by `_sync_board_to_rom()` /
  `new_game()`; the ten (`$F3-$FF`) are scratch, and forcing them to
  `$00/$FF/$55/$AA` never changes the move (5/5 positions).
* Difficulty maps to depth through the ROM's table at `$D06E`
  (`$B8` 0-15 → depth 2, 16-23 → 3, 24-31 → 4), i.e. 初级/中级/高级 —
  exactly the `depth` argument this package takes.

### Opening book

The ROM consults a book at `$CD26` *before* the search, from the caller at
`$D1DA`. This is reproduced — pass `book=True`:

```python
engine = QiWangEngine(depth=2, book=True)
```

Two things were needed to make it work:

1. `$CD26` is gated by `$E4FA`, which computes `$FFE2 ^ $FFD1 ^ $0437` and
   only enables the book when the result is 0 — a second anti-tamper
   checksum alongside the known `$0436` one. `new_game()` now sets `$0437`
   accordingly.
2. `$CD26` does **not** behave like `$8597`. It executes the move itself via
   `$E49E` and returns with carry *clear*; carry *set* (`$CD84`/`$CDB8`)
   means the line is exhausted, and it clears `$B6` bit 7 on the way out.
   `$C0/$C1` do not hold the move on this path, so `book_move()` recovers it
   by diffing the board across the call.

The stored line is **33 plies** and opens 炮八平五 / 砲8平5 / 马二进三 —
recognisable 中炮 theory. Because the book is a *sequential* walk through
that line rather than a position lookup, it only applies while the game has
followed it from the start; `_book_applies()` checks this and the engine
falls through to search otherwise. Verified: all 33 moves legal, and search
after the book still matches a pristine engine exactly.

## Verification

Reproduce with `python -m tests.test_game --slow` and
`python -m tests.verify_fidelity --depth 2 --plies 40`:

| Check | Result |
|-------|--------|
| Move generation vs. an independent reference generator | 600/600 positions |
| `make_move`/`undo_move` round-trip | 200/200 |
| Legal moves never leave own king in check | pass |
| Opening move = ROM's `h2->e2` (炮二平五) | pass |
| PST evaluation vs. ROM `$8886` | 10/10 exact |
| Engine vs. ROM self-play, depth 2 | 40/40 moves identical |
| Engine vs. ROM self-play, depth 3 | 30/30 moves identical |
| Opening book line legal + hands off to search | 33 plies, pass |
| Search after book == pristine engine | 4/4 |

The fidelity test is the strong one: the ROM plays itself from its own
internal state, and at each ply the engine is asked the same question after
syncing a Python `Board` into ROM RAM from scratch. Any lossy round-trip
shows up as a mismatch.

## Playing against a modern engine

`match.py` plays the ROM AI against a modern engine and visualises the game
in the terminal, then writes a self-contained HTML replay with a move slider.

```bash
python match.py                                    # ROM plays Red
python match.py --rom-side black --rom-depth 3
python match.py --modern-depth 6 --out game.html
python match.py --no-book                          # disable the ROM's book
```

The opponent is [Pikafish](https://github.com/official-pikafish/Pikafish)
(UCI/NNUE) when a binary is found on `PATH` or in `engines/`, otherwise the
bundled `modern_ai.ModernEngine` — a pure-Python alpha-beta searcher with a
transposition table, quiescence search with SEE pruning, killer/history move
ordering and MVV-LVA capture ordering. Use `--no-pikafish` to force it.

## Use Cases

### Training opponent / baseline

```python
engine = QiWangEngine(depth=2)
while not game_over:
    my_move = my_agent.select_move(board)
    board.make_move(*my_move)
    opponent_move = engine.get_best_move(board)
    board.make_move(*opponent_move)
```

### Knowledge distillation

```python
engine = QiWangEngine(depth=3)
for position in positions:
    info = engine.analyze(position.board)
    best_move = info['move']
    eval_score = info['score']
    # Use as training labels for your model
```

### Evaluation

```python
engine = QiWangEngine(depth=2)
for board in test_positions:
    score = engine.evaluate(board)
    legal_moves = engine.get_legal_moves(board)
```

## Project Structure

```
pyqiwang/
├── __init__.py          # Public API exports
├── __main__.py          # CLI: python -m pyqiwang
├── _engine.py           # QiWangEngine (high-level API)
├── _board.py            # Board, move generation, evaluation
├── _harness.py          # ROM loader + subroutine caller
├── _mos6502.py          # MOS6502 CPU emulator
└── pst_tables.json      # 14 PST tables extracted from ROM $8886

modern_ai.py             # Modern opponent: pure-Python search + Pikafish UCI
match.py                 # ROM vs modern engine, terminal + HTML replay

tests/
├── __init__.py
├── test_game.py         # Move gen / eval / engine correctness
└── verify_fidelity.py   # ROM vs engine move-for-move comparison
```

## License

MIT
