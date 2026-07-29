"""Optional modern runtime services around the ROM-faithful engine.

The runtime never substitutes another evaluator or searcher. It selects a ROM
search depth, caches completed whole-position searches, and exposes statistics.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from threading import Lock
from collections.abc import Callable
from typing import Optional

from pyqiwang._board import Board, generate_legal_moves, is_in_check
from pyqiwang._engine import QiWangEngine


@dataclass(slots=True)
class RuntimeStats:
    searches: int = 0
    cache_hits: int = 0
    elapsed: float = 0.0
    instructions: int = 0
    depth_counts: dict[int, int] = field(default_factory=dict)

    @property
    def hit_rate(self) -> float:
        total = self.searches + self.cache_hits
        return self.cache_hits / total if total else 0.0


@dataclass(frozen=True, slots=True)
class CachedMove:
    move: tuple[int, int] | None
    depth: int
    elapsed: float
    instructions: int


class ModernRomRuntime:
    """Cache and adaptive-depth policy for the original ROM search.

    Args:
        base_depth: Minimum ROM depth.
        max_depth: Maximum adaptive depth.
        cache_size: Maximum number of whole-position results.
        core: ROM execution core passed to :class:`QiWangEngine`.
    """

    def __init__(self, base_depth: int = 5, max_depth: int = 7,
                 cache_size: int = 50_000, core: str = "auto",
                 opening_lookup: Optional[Callable[[Board], tuple[int, int] | None]] = None,
                 endgame_lookup: Optional[Callable[[Board], tuple[int, int] | None]] = None) -> None:
        self.base_depth = max(1, min(int(base_depth), 12))
        self.max_depth = max(self.base_depth, min(int(max_depth), 12))
        self.cache_size = max(1, int(cache_size))
        self.core = core
        self.engine = QiWangEngine(depth=self.base_depth, book=False, core=core)
        self.opening_lookup = opening_lookup
        self.endgame_lookup = endgame_lookup
        self.knowledge_hits = {"opening": 0, "endgame": 0}
        self.cache: dict[tuple, CachedMove] = {}
        self.stats = RuntimeStats()
        self._lock = Lock()

    @staticmethod
    def position_key(board: Board, depth: int) -> tuple:
        return (tuple(board.pieces[0]), tuple(board.pieces[1]),
                board.side_to_move, depth)

    def choose_depth(self, board: Board) -> int:
        """Choose a conservative depth using only cheap position features."""
        legal_count = len(generate_legal_moves(board, board.side_to_move))
        remaining = sum(pos >= 0 for side in board.pieces for pos in side)
        checked = is_in_check(board, board.side_to_move)

        depth = self.base_depth
        if checked or legal_count <= 10:
            depth += 1
        if remaining <= 16 and legal_count <= 18:
            depth += 1
        elif remaining <= 22 and legal_count <= 14:
            depth += 1
        return min(depth, self.max_depth)

    def search(self, board: Optional[Board] = None,
               depth: Optional[int] = None) -> tuple[int, int] | None:
        if board is None:
            board = self.engine._board
        legal = None
        for name, lookup in (("opening", self.opening_lookup),
                             ("endgame", self.endgame_lookup)):
            if lookup is None:
                continue
            move = lookup(board)
            if move is None:
                continue
            if legal is None:
                legal = generate_legal_moves(board, board.side_to_move)
            if move not in legal:
                raise ValueError(f"{name} lookup returned illegal move {move}")
            self.knowledge_hits[name] += 1
            return move

        selected = self.choose_depth(board) if depth is None else max(
            1, min(int(depth), 12))
        key = self.position_key(board, selected)
        with self._lock:
            cached = self.cache.get(key)
            if cached is not None:
                self.stats.cache_hits += 1
                return cached.move

        before = self.engine.harness.instr_count
        started = time.perf_counter()
        move = self.engine.get_best_move(board, depth=selected)
        elapsed = time.perf_counter() - started
        instructions = self.engine.harness.instr_count - before
        record = CachedMove(move, selected, elapsed, instructions)
        with self._lock:
            if len(self.cache) >= self.cache_size:
                self.cache.clear()
            self.cache[key] = record
            self.stats.searches += 1
            self.stats.elapsed += elapsed
            self.stats.instructions += instructions
            self.stats.depth_counts[selected] = self.stats.depth_counts.get(selected, 0) + 1
        return move

    def _ponder_one(self, board: Board, reply: tuple[int, int], depth: int) -> tuple[tuple[int, int], CachedMove]:
        future = board.clone()
        future.make_move(*reply)
        worker = QiWangEngine(depth=depth, book=False, core=self.core)
        before = worker.harness.instr_count
        started = time.perf_counter()
        move = worker.get_best_move(future, depth=depth)
        elapsed = time.perf_counter() - started
        record = CachedMove(move, depth, elapsed,
                            worker.harness.instr_count - before)
        key = self.position_key(future, depth)
        with self._lock:
            if len(self.cache) >= self.cache_size:
                self.cache.clear()
            self.cache[key] = record
        return reply, record

    def ponder_replies(self, board: Board, depth: Optional[int] = None,
                       max_replies: int = 8, workers: int = 4) -> dict:
        """Speculatively analyze positions after likely opponent replies.

        The caller should invoke this while waiting for the opponent. Candidate
        replies use the board generator's deterministic order; no external
        evaluator chooses them. Results populate the ordinary whole-position
        cache and are reused automatically if the opponent plays one.
        """
        replies = generate_legal_moves(board, board.side_to_move)[:max(
            0, int(max_replies))]
        if not replies:
            return {"submitted": 0, "completed": 0, "seconds": 0.0}
        selected = self.choose_depth(board) if depth is None else max(
            1, min(int(depth), 12))
        started = time.perf_counter()
        completed = 0
        with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
            jobs = [pool.submit(self._ponder_one, board, reply, selected)
                    for reply in replies]
            for job in as_completed(jobs):
                job.result()
                completed += 1
        return {
            "submitted": len(replies),
            "completed": completed,
            "seconds": time.perf_counter() - started,
            "depth": selected,
        }

    def clear_cache(self) -> None:
        with self._lock:
            self.cache.clear()

    def get_stats(self) -> dict:
        return {
            "searches": self.stats.searches,
            "cache_hits": self.stats.cache_hits,
            "hit_rate": self.stats.hit_rate,
            "elapsed": self.stats.elapsed,
            "instructions": self.stats.instructions,
            "depth_counts": dict(self.stats.depth_counts),
            "cache_entries": len(self.cache),
            "knowledge_hits": dict(self.knowledge_hits),
        }
