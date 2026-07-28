# pyqiwang — FC 棋王 Dual-Path Chinese Chess AI

Reverse-engineering and native reimplementation of the AI from the FC game
**棋王** (Chess King). The project now keeps two implementation paths side by
side: the proven ROM-backed implementation and a new ROM-free pure-Python path.

## Implementation paths

| Path | Class / CLI | ROM required | Status |
|---|---|---:|---|
| ROM faithful | `QiWangEngine` / `--engine rom` | Yes | Preserved; executes ROM `$8597`, 100% move-faithful |
| Native Python | `NativeQiWangEngine` / `--engine native` | No | 33-ply book + iterative alpha-beta/quiescence; depth ceiling 8 |

The native path currently uses the existing Python rules, ROM-extracted PST
values, and an extracted 33-ply sequential opening line. Its search will be
translated and verified incrementally against the preserved ROM path. Keeping
both paths allows exact differential testing during the migration instead of
replacing the known-good implementation prematurely.

## Features

- **Preserved faithful AI** — runs ROM `$8597` through the Python 6502 emulator
- **ROM-free implementation path** — iterative alpha-beta, quiescence, TT, PV and bounded depth-8 search
- **PST evaluation tables** — extracted directly from ROM `$8886` via dynamic trace
- **Clean Python API** — ready for training, baselines, and differential verification
- **Zero external Python dependencies**

## Install

```bash
git clone https://github.com/KakaruHayate/pyqiwang.git
cd pyqiwang
```

The native path needs no ROM. To use the preserved faithful path, place the ROM
file `棋王(繁)[小天才](CN)[TAB](0.75Mb).nes` in the project root.

## Quick Start

### Preserved ROM-faithful path

```python
from pyqiwang import QiWangEngine, Board, RED, BLACK

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

### ROM-free native path

```python
from pyqiwang import NativeQiWangEngine, Board

engine = NativeQiWangEngine(depth=8, time_limit=5.0)
board = Board()
move = engine.get_best_move(board)
info = engine.analyze(board)
# Includes completed_depth, stopped, pv, nodes, score and elapsed.
# A bounded search returns the last fully completed iteration.
```

The native API mirrors the ROM engine's main methods, but its search is currently
a migration scaffold and must not yet be described as FC move-faithful. Passing
`book=True` enables the ROM-free extracted 33-ply sequential line; exact board
matching prevents the line from being applied after either player diverges.

## CLI

```bash
# Preserved ROM-faithful engine (default)
python -m pyqiwang --engine rom --depth 2

# ROM-free pure-Python implementation path
python -m pyqiwang --engine native --depth 2

# Request depth 8 with a practical per-move bound
python -m pyqiwang --engine native --depth 8 --time-limit 5
# Or use a deterministic node budget
python -m pyqiwang --engine native --depth 8 --node-limit 100000

# Play as Black
python -m pyqiwang --engine native --depth 3 --side black

# Auto-play demo (AI vs AI)
python -m pyqiwang --engine native --demo
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

### `NativeQiWangEngine`

The ROM-free implementation supports `get_best_move`, `make_move`, `evaluate`,
`analyze`, `get_legal_moves`, `play_auto`, `reset`, and the `depth` property.
`NativeQiWangEngine(depth=2, book=False, time_limit=None, node_limit=None)`
supports depths 1 through 8. It uses iterative deepening and returns the last
fully completed iteration when a time/node bound fires. `analyze()` additionally
reports `completed_depth`, `nodes`, `pv`, `stopped`, `backend='native'`,
`faithful=False`, and `from_book`. It does not expose raw ROM state.

The depth-8 ceiling is an extension target, not an assertion that today's pure
Python implementation can finish depth 8 quickly from every position. The
current architecture makes depth 8 safe and observable; move ordering, exact ROM
node rules and a compiled hot path are still required for practical completion.

### Generating ROM golden fixtures

`tools/generate_golden.py` is an opt-in development tool that records board
positions, ROM PST values, and ROM best moves without embedding ROM bytes:

```bash
python tools/generate_golden.py \
  --rom "path/to/qiwang.nes" \
  --output tests/fixtures/rom_depth1_golden.json \
  --depth 1 --positions 12
```

The checked-in depth-1 fixture records the source ROM SHA-256 and deterministic
random seed. Future native-search work can compare against this baseline on a
machine that does not have the ROM. The native path now agrees with the ROM on
all 12 initial depth-1 fixtures. This is a bounded milestone, not a claim of
complete native fidelity at deeper searches or arbitrary positions.

`tools/trace_root.py` captures ROM root candidates, their independent 16-bit
scores, running best values, and maximum internal level. The checked-in traces
show that ROM depth 1 reaches internal level 4 or 5 and retains the first
equal-scoring move. Native capture quiescence closes the initial fixture gap
from 8/12 to 12/12. Depth-2 traces additionally show that a horizon check is
scored normally unless a king is actually captured; matching that behavior
closes the independent depth-2 corpus. The ROM's exact deeper selective
node rules are still under reconstruction.

Independent random-playout baselines currently measure:

| Corpus | Independent selector/bound vs. ROM | Notes |
|---|---:|---|
| depth 1 golden, 12 positions | 12/12 | Original golden baseline |
| depth 1 independent, 24 positions | 23/24 | One remaining selective-search mismatch |
| depth 2 independent, 8 positions | 8/8 | Two root iterations reconstructed |
| depth 3 independent, 8 positions | 8/8 | Selector legality gate aligned |
| depth 4 independent, 8 positions | 8/8 | Four-iteration state machine aligned |

These depth 1-4 results belong to the isolated ROM-free experiment in
`tools/experiment_selector_bound.py`; they have not yet been integrated into
`NativeQiWangEngine`, which remains correctly marked `faithful=False`. The
Chinese document [`FC棋王算法解析.md`](FC棋王算法解析.md) explains the extracted
PST evaluation, root iterations, selector phases, seeded probes, bound slots,
history rotation, legality restoration, evidence and remaining unknowns.

The intended progression is: integrate the independently verified depth 1-4
state machine without removing the preserved ROM path, then retain the same
evaluation and search character while extending iterative search to depths 5-8.
Improvements that alter behavior (stronger ordering or compiled acceleration)
must be verified separately from ROM-fidelity changes.

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

### Results

Every game below was replayed through the rules engine afterwards: no
illegal moves, and each mate verified as a real one (side to move, zero
legal moves, in check).

**vs. Pikafish 2026-01-02 (NNUE)** — the ROM at 高级 (depth 4), Pikafish at
3 s/move, 8 threads, 2 GB hash. Replays: `replay_pf_red.html`,
`replay_pf_black.html`, `replay_pf_handicap.html`.

| ROM side | Pikafish setting | Result |
|---|---|---|
| Black | 3 s, 8 threads | Mated in 59 plies |
| Red | 3 s, 8 threads | Mated in 70 plies |
| Red | **10 ms, 1 thread** | Mated in 88 plies |

Pikafish wins even crippled to 10 ms on one thread — because that still
reaches **depth 8.4 on average**, twice the ROM's 高级 depth of 4, with an
NNUE evaluation on top. There is no setting at which this is a contest.

The scoreline is the least interesting part. Measuring *move agreement* on
positions from real play says more:

| ROM difficulty | Matches Pikafish's top move | Mean centipawn loss when it differs |
|---|---|---|
| 初级 (depth 2) | 4/12 | 40 cp |
| 高级 (depth 4) | 1/8 | 37 cp |

So the 1990s search is not blundering material — it agrees with a modern
NNUE engine a third of the time and gives up well under half a pawn when it
doesn't. It loses slowly, on positional judgement, over dozens of moves.

**vs. the bundled `ModernEngine`** (depth 4 / 3 s), a much weaker opponent.
Replays: `replay.html`, `replay_d4_red.html`, `replay_d4_black.html`.

| ROM difficulty | ROM side | Result |
|---|---|---|
| 高级 (depth 4) | Black | **ROM wins** — mate in 72 plies |
| 高级 (depth 4) | Red | Loses — mated in 128 plies |
| 初级 (depth 2), book on | Red | Draw by repetition, 84 plies |
| 初级 (depth 2), book off | Red | Loses — mated in 104 plies |

Controls, so these numbers mean something:

* `ModernEngine` depth 4 against **itself** draws by repetition (92 plies),
  so the losses above reflect a real strength gap rather than a first-move
  advantage.
* The ROM's own difficulty ladder works: ROM depth 3 beats ROM depth 2 as
  Black (56 plies) and draws as Red, i.e. depth genuinely buys strength.
* At 初级 the opening book flipped a loss into a draw against the same
  opponent — off: mated in 104; on: drawn in 84. Note this is a single game
  per condition and the book contributed only its first move before the
  opponent left the line, so treat it as suggestive, not measured.
* 高级 costs about **70 s per move** in this emulator (初级 ≈ 3 s,
  中级 ≈ 8 s), which is why the samples are small.

The split result against `ModernEngine` at 高级 — winning as Black, losing
as Red — is one game each, so it does not establish a colour preference.

### Using Pikafish

Download a build and the NNUE network from the
[Pikafish releases](https://github.com/official-pikafish/Pikafish/releases),
put the binary and `pikafish.nnue` in `engines/` (gitignored), and pick the
executable matching your CPU:

```bash
python match.py --rom-depth 4 --pf-movetime 3000 --pf-threads 8 --pf-hash 2048
```

`match.py` uses Pikafish automatically when it finds one; `--no-pikafish`
forces the built-in engine.

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
├── _engine.py           # Preserved ROM-backed QiWangEngine
├── _native.py           # ROM-free NativeQiWangEngine path
├── _book.py             # Sequential opening-book probe
├── opening_book.json    # Extracted 33-ply ROM line
├── _board.py            # Board, move generation, evaluation
├── _harness.py          # ROM loader + subroutine caller
├── _mos6502.py          # MOS6502 CPU emulator
└── pst_tables.json      # 14 PST tables extracted from ROM $8886

modern_ai.py             # Modern opponent: pure-Python search + Pikafish UCI
match.py                 # ROM vs modern engine, terminal + HTML replay

replay.html              # Example games (open in a browser, drag the slider)
replay_d4_red.html
replay_d4_black.html
replay_pf_red.html       # vs Pikafish
replay_pf_black.html
replay_pf_handicap.html

tests/
├── __init__.py
├── test_game.py         # Move gen / eval / engine correctness
└── verify_fidelity.py   # ROM vs engine move-for-move comparison
```

## Conclusions

**The reproduction is faithful, and this was tested rather than assumed.**
Running the ROM's own `$8597` inside a 6502 emulator makes move selection
correct by construction, but only if the ROM's state is fully restored on
every call — which is where the real bugs were. Instrumenting every RAM
read-before-write during a search identified the exact 163-address
dependency set and confirmed nothing outside it matters. The engine now
reproduces the ROM move for move over self-play games, at depth 2 and 3.

**Five bugs were found by testing, not by reading.** The most damaging one
zeroed the `$FF` off-board sentinels, so the ROM's sliding move generation
ran off the board. Every one of them survived a codebase that claimed "100%
fidelity" with a verification table — because both test files failed at
import and nobody had run them. Write the reference implementation
independently: the move-generation bugs were only visible against a
generator rewritten from the rules in different coordinates.

**The AI is weaker than its era's reputation, but not crude.** Against
Pikafish it plays the top move roughly a third of the time and gives up
about 40 centipawns when it doesn't. It loses by slow positional drift over
dozens of moves, not by hanging pieces — reasonable for 14 piece-square
tables and a depth-4 search on a 6502. Its own difficulty ladder is real:
depth 3 beats depth 2 head to head.

**Caveats worth keeping.** The strength numbers are one game per condition —
高级 costs ~70 s per move under emulation, which caps the sample. The
opening-book result (a loss becoming a draw) is suggestive only: the book
supplied a single move before the opponent left the line. Nothing here is a
statistically meaningful rating; it is a characterisation.

**What was wrong along the way.** An earlier pass concluded the opening
book was unimplementable, blaming the Mapper 133 bank model. That was
backwards — `$CD26` returns carry *clear* when it has played a move, and
misreading that convention produced a false observation that then got an
invented mechanism to explain it. The book works, and plays 33 plies of
中炮 theory. When an observation and a mechanism disagree, re-check the
observation first.

## License

MIT
