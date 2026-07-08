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
| `QiWangEngine(rom_path=None, depth=2)` | Initialize engine. ROM auto-detected if not specified. |
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
              ROM $8597 search algorithm (native)
                          ↓
              $C0/$C1: best move returned
```

1. The Python `Board` state is written to ROM zero-page RAM
2. The 6502 emulator executes the ROM's `$8597` subroutine
3. The ROM generates candidates via `$8701`, runs alpha-beta search via `$CE9E`
4. The best move is read back from `$C0/$C1`
5. All evaluation uses the ROM's 14 PST tables from `$8886`

## Verification

| Metric | Result |
|--------|--------|
| Move legality | 100% (20/20) |
| PST evaluation | 10/10 test positions, 100% match |
| Auto-play completion | 100% (5/5 games) |

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

tests/
├── __init__.py
├── test_game.py         # Auto-play test
└── verify_fidelity.py   # ROM vs Python move comparison
```

## License

MIT
