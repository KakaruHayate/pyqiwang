#!/usr/bin/env python3
"""Independent selector/bound search experiment for the ROM-free engine.

The goal is not to replace NativeQiWangEngine yet.  This script combines the
trace-backed selector candidate order with explicit per-level ROM-style raw
score bounds, best/child state and history rotation, then measures corpus
agreement before any production integration.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pyqiwang import BLACK, RED, Board
from pyqiwang._board import (
    ADVISOR,
    ADVISOR_DELTAS,
    BLACK_PALACE,
    BOARD_STRIDE,
    CANNON,
    ELEPHANT,
    ELEPHANT_DELTAS,
    ELEPHANT_LEGS,
    KING,
    KNIGHT,
    KNIGHT_DELTAS,
    KNIGHT_LEGS,
    PAWN,
    PIECE_TYPES,
    RED_PALACE,
    ROOK,
    evaluate_raw,
    generate_legal_moves,
    generate_piece_moves,
)
from tools.experiment_selector_candidates import (
    Candidate,
    Move,
    SelectorCandidatePrototype,
    SelectorFrame,
    board_from_record,
)

RAW_MIN = 0x0000
RAW_MAX = 0xFFFF
MAX_LEVEL = 12
DEFAULT_MAX_NODES = 1_000_000


class SearchLimitReached(RuntimeError):
    """Raised when an experimental search exceeds its explicit node budget."""


@dataclass
class BoundTrace:
    level: int
    side: int
    move: Move | None
    stand_raw: int
    bound_raw: int
    previous_bound_raw: int
    best_raw: int
    child_raw: int
    selector: int
    history_move: Move | None
    previous_history_move: Move | None
    event: str


class SelectorBoundExperiment:
    """Raw-score minimax using trace-backed selective candidates and bounds."""

    def __init__(self, max_nodes: int | None = DEFAULT_MAX_NODES,
                 capture_trace: bool = False):
        self.frames = [SelectorFrame(level=i, side=RED) for i in range(16)]
        self.trace: list[BoundTrace] = []
        self.root_trace: list[dict] = []
        self.nodes = 0
        self.max_nodes = max_nodes
        self.capture_trace = capture_trace
        self._legal_cache: dict[tuple, frozenset[Move]] = {}
        self._evaluation_cache: dict[tuple, int] = {}
        self.iteration_nodes: list[int] = []
        self.root_move_nodes: list[dict] = []
        self.active_root_move: dict | None = None

    @staticmethod
    def _better(side: int, candidate: int, best: int) -> bool:
        return candidate > best if side == RED else candidate < best

    @staticmethod
    def _cutoff(side: int, best: int, bound: int) -> bool:
        # ROM red path raises a lower bound; black lowers the symmetric bound.
        return best >= bound if side == RED else best <= bound

    @staticmethod
    def _initial_best(side: int) -> int:
        # $869C seeds the root incumbent with the ROM's finite sentinels rather
        # than the full 16-bit extrema: red starts at $1000, black at $F000.
        return 0x1000 if side == RED else 0xF000

    @staticmethod
    def _board_key(board: Board, side: int) -> tuple:
        return (side, tuple(board.pieces[RED]), tuple(board.pieces[BLACK]))

    @staticmethod
    def _is_square_attacked(board: Board, target: int, attacker: int) -> bool:
        """Test the ROM `$8049` question without allocating reply lists.

        The search gate only needs to know whether the moving side's king is
        attacked after a candidate has been made.  Test each opposing piece
        directly against that one square; this preserves the board module's
        Xiangqi geometry while avoiding `generate_piece_moves()` allocations for
        pieces that cannot possibly reach the king.
        """
        if target < 0:
            return True
        target_file, target_rank = board.pos_to_coord(target)
        for index, frm in enumerate(board.pieces[attacker]):
            if frm < 0:
                continue
            ptype = PIECE_TYPES[index]
            file, rank = board.pos_to_coord(frm)
            delta = target - frm

            if ptype == KING:
                palace = RED_PALACE if attacker == RED else BLACK_PALACE
                if target in palace and delta in (-1, 1, -BOARD_STRIDE, BOARD_STRIDE):
                    return True
                # The board API models flying generals outside ordinary king
                # moves, so preserve that explicit attack here as well.
                if file == target_file:
                    step = 1 if target > frm else -1
                    pos = frm + step
                    while pos != target and board.cells[pos] == 0:
                        pos += step
                    if pos == target:
                        return True

            elif ptype == ADVISOR:
                palace = RED_PALACE if attacker == RED else BLACK_PALACE
                if target in palace and delta in ADVISOR_DELTAS:
                    return True

            elif ptype == ELEPHANT:
                if delta in ELEPHANT_DELTAS:
                    leg = ELEPHANT_LEGS[ELEPHANT_DELTAS.index(delta)]
                    if board.cells[frm + leg] != 0:
                        continue
                    if attacker == RED and target_rank <= 4:
                        return True
                    if attacker == BLACK and target_rank >= 5:
                        return True

            elif ptype == KNIGHT:
                if delta in KNIGHT_DELTAS:
                    leg = KNIGHT_LEGS[KNIGHT_DELTAS.index(delta)]
                    if board.cells[frm + leg] == 0:
                        return True

            elif ptype in (ROOK, CANNON):
                if file != target_file and rank != target_rank:
                    continue
                if file == target_file:
                    step = 1 if target > frm else -1
                else:
                    step = BOARD_STRIDE if target > frm else -BOARD_STRIDE
                screens = 0
                pos = frm + step
                while pos != target:
                    if board.cells[pos] != 0:
                        screens += 1
                    pos += step
                if (ptype == ROOK and screens == 0) or (
                        ptype == CANNON and screens == 1):
                    return True

            elif ptype == PAWN:
                forward = 1 if attacker == RED else -1
                if delta == forward:
                    return True
                crossed = rank >= 5 if attacker == RED else rank <= 4
                if crossed and delta in (-BOARD_STRIDE, BOARD_STRIDE):
                    return True
        return False

    @classmethod
    def _is_legal_after_move(cls, board: Board, side: int) -> bool:
        king = board.pieces[side][0]
        return not cls._is_square_attacked(board, king, 1 - side)

    @staticmethod
    def _rom_pseudo_moves(board: Board, side: int) -> list[Move]:
        moves: list[Move] = []
        for index, frm in enumerate(board.pieces[side]):
            if frm >= 0:
                moves.extend(generate_piece_moves(
                    board, side, frm, PIECE_TYPES[index]
                ))
        return moves

    def _rom_selector_legal_moves(self, board: Board, side: int) -> set[Move]:
        """Return the per-node move set accepted by the ROM legality gate."""
        key = self._board_key(board, side)
        cached = self._legal_cache.get(key)
        if cached is not None:
            return set(cached)
        legal: set[Move] = set()
        for move in self._rom_pseudo_moves(board, side):
            board.make_move(*move)
            if self._is_legal_after_move(board, side):
                legal.add(move)
            board.undo_move()
        self._legal_cache[key] = frozenset(legal)
        return legal

    def _record(self, frame: SelectorFrame, event: str,
                move: Move | None, stand_raw: int) -> None:
        if not self.capture_trace:
            return
        self.trace.append(BoundTrace(
            level=frame.level,
            side=frame.side,
            move=move,
            stand_raw=stand_raw,
            bound_raw=frame.bound_raw,
            previous_bound_raw=frame.previous_bound_raw,
            best_raw=frame.best_raw,
            child_raw=frame.child_raw,
            selector=frame.selector,
            history_move=frame.history_move,
            previous_history_move=frame.previous_history_move,
            event=event,
        ))

    def _selector_moves(self, board: Board, frame: SelectorFrame) -> list[Move]:
        legal = self._rom_selector_legal_moves(board, frame.side)
        candidates = SelectorCandidatePrototype(board, frame, legal).generate()
        moves: list[Move] = []
        for candidate in candidates:
            if candidate.move in legal and candidate.move not in moves:
                moves.append(candidate.move)
        return moves

    @staticmethod
    def _rom_full_width_moves(board: Board, side: int,
                              legal_moves: set[Move] | None = None) -> list[Move]:
        """Approximate $A41C/$94B9 ordering with ROM piece-index order.

        The full-width routines visit piece slots 0..15, while the generic
        Python generator happens to use the same slot order but different
        per-piece delta order.  Keep this isolated so the remaining ROM delta
        order can be translated without affecting the formal board API.
        """
        moves: list[Move] = []
        for index in range(16):
            frm = board.pieces[side][index]
            if frm < 0:
                continue
            moves.extend(generate_piece_moves(
                board, side, frm, PIECE_TYPES[index]
            ))
        legal = legal_moves if legal_moves is not None else set(
            generate_legal_moves(board, side)
        )
        return [move for move in moves if move in legal]

    def _search(self, board: Board, side: int, level: int, bound_raw: int,
                previous_bound_raw: int, current_move: Move | None,
                saved_target: int | None, iteration: int = 0,
                history_seed: Move | None = None,
                previous_history_seed: Move | None = None) -> int:
        if self.max_nodes is not None and self.nodes >= self.max_nodes:
            raise SearchLimitReached(
                f"selector/bound search exceeded {self.max_nodes} nodes"
            )
        self.nodes += 1
        position_key = self._board_key(board, side)
        stand = self._evaluation_cache.get(position_key)
        if stand is None:
            stand = evaluate_raw(board)
            self._evaluation_cache[position_key] = stand
        frame = self.frames[level]
        frame.level = level
        frame.side = side
        frame.bound_raw = bound_raw
        frame.previous_bound_raw = previous_bound_raw
        frame.child_raw = stand
        frame.current_move = current_move
        frame.saved_target = saved_target
        # $CF is decremented at every selective node.  The ROM table-driver
        # always scans targets 0..2, but scans targets 3..15 only while CF>=FE.
        # The depth-1 root seed is $00, so level 1 observes $FF, level 2 $FE,
        # and level 3 $FD.
        frame.cf = (iteration - level) & 0xFF
        if frame.cf < 0x80:
            # The positive-CF gate bypasses stand-pat but does not preserve the
            # stale frame incumbent.  $A268/$9305 is preceded by the routine's
            # side sentinel store: $F000 for a black-to-move node and $1000 for
            # a red-to-move node.  Focused depth-2 traces expose these exact
            # values at level 1 before selector/full-width generation.
            frame.best_raw = self._initial_best(side)
        if history_seed is not None:
            frame.history_move = history_seed
        if previous_history_seed is not None:
            frame.previous_history_move = previous_history_seed
        self._record(frame, "node", current_move, stand)

        # $A268/$9305 decrement CF and bypass the complete static-score gate
        # while the result is nonnegative.  Therefore the first two plies of
        # ROM iteration 1 retain their existing per-level incumbent instead of
        # replacing it with stand-pat.  Once CF is negative, $A26C/$9309 run the
        # side-symmetric bound normalization below.
        iteration_gate = frame.cf < 0x80
        if not iteration_gate:
            if side == RED:
                if stand > bound_raw:
                    if stand >= previous_bound_raw:
                        frame.best_raw = stand
                        self._record(
                            frame, "static-bound-return", current_move, stand
                        )
                        return stand
                    frame.bound_raw = stand
            else:
                if stand < bound_raw:
                    if stand <= previous_bound_raw:
                        frame.best_raw = stand
                        self._record(
                            frame, "static-bound-return", current_move, stand
                        )
                        return stand
                    frame.bound_raw = stand
            frame.best_raw = stand
            self._record(frame, "normalize-bound", current_move, stand)
        else:
            self._record(frame, "iteration-gate-bypass", current_move, stand)
        bound_raw = frame.bound_raw
        if level >= MAX_LEVEL:
            return frame.best_raw if iteration_gate else stand

        if iteration_gate:
            # Generate legality once per node.  ROM's $8049/check-response
            # gates reject the same pseudo-legal selector moves before recurse;
            # reusing this set avoids recomputing the whole move list for every
            # candidate in the selector and full-width suffix.
            legal_moves = self._rom_selector_legal_moves(board, frame.side)
            # CF>=0 does not replace the selector phases.  It executes them
            # first, then $A40E/$94AB falls through into $A41C/$94B9 and
            # appends the ordinary full-width generators.  This prefix is
            # observable in ROM depth-2 traces: saved-target and history moves
            # precede the piece-index-ordered full-width list.
            candidates = SelectorCandidatePrototype(
                board, frame, legal_moves
            ).generate()
            candidates.extend(
                Candidate(move, "full-width", 2, "$B55F/$B1D7")
                for move in self._rom_full_width_moves(
                    board, frame.side, legal_moves
                )
            )
            # Selector/full-width calls share the try-move dedup table.  A move
            # found in an earlier selector phase is not tried again by the
            # full-width suffix, even though the ROM generator reaches it.
            deduped: list[Candidate] = []
            seen: set[Move] = set()
            for candidate in candidates:
                if candidate.move in seen:
                    continue
                seen.add(candidate.move)
                # The ROM's $E0 check-response selector sends pseudo-legal
                # table/history candidates through $B32E/$B6B3.  Moves that
                # leave the checked king attacked are restored at $B36A/$B6F2
                # without recursion.  Filtering here is the equivalent board-
                # state effect and also applies harmlessly to ordinary CF>=0
                # selector prefixes; the full-width suffix is already legal.
                if candidate.move in legal_moves:
                    deduped.append(candidate)
            candidates = deduped
        else:
            # Negative-CF nodes also pass all selector candidates through the
            # same ROM legality/check-response gate.  Compute that set once;
            # the prior per-candidate `generate_legal_moves()` call dominated
            # depth-4 runtime without changing any search decisions.
            legal_moves = self._rom_selector_legal_moves(board, frame.side)
            candidates = SelectorCandidatePrototype(
                board, frame, legal_moves
            ).generate()
            candidates = [
                candidate for candidate in candidates
                if candidate.move in legal_moves
            ]
        if not candidates:
            return stand

        # The iteration gate preserves the incumbent already stored in the
        # frame; the negative-CF path stores stand at $A290/$932D.
        best = frame.best_raw if iteration_gate else stand
        frame.best_raw = best
        searched: set[Move] = set()
        for candidate in candidates:
            move = candidate.move
            if move in searched:
                continue
            searched.add(move)
            frame.selector = candidate.selector
            board.make_move(*move)
            try:
                # $B29C/$B624 first try a one-point seeded child only when the
                # current incumbent has reached the active bound.  A failed
                # probe restores immediately; only a child that can improve the
                # parent enters $B424/$B7AC for the alternate full re-search.
                seed_probe = (
                    best >= bound_raw if side == RED else bound_raw >= best
                )
                re_search = not seed_probe
                child = best
                if seed_probe:
                    seed_bound = bound_raw + (1 if side == RED else -1)
                    child = self._search(
                        board,
                        1 - side,
                        level + 1,
                        seed_bound & 0xFFFF,
                        bound_raw,
                        move,
                        move[1],
                        iteration,
                    )
                    re_search = (
                        child > bound_raw if side == RED else child < bound_raw
                    )
                    self._record(
                        frame,
                        "seed-research" if re_search else "seed-restore",
                        move,
                        stand,
                    )
                if re_search:
                    child = self._search(
                        board,
                        1 - side,
                        level + 1,
                        # $B424/$B7AC copy the parent active bound into the
                        # child's adjacent slot; the child active slot receives
                        # the parent's previous/adjacent bound.
                        previous_bound_raw,
                        bound_raw,
                        move,
                        move[1],
                        iteration,
                    )
            finally:
                board.undo_move()
            frame.child_raw = child
            improved = self._better(side, child, best)
            if improved:
                best = child
                frame.best_raw = child
                self._record(frame, "update-best", move, stand)

            crossed_active = (
                best > bound_raw if side == RED else best < bound_raw
            )
            crossed_previous = (
                best >= previous_bound_raw if side == RED
                else best <= previous_bound_raw
            )
            if improved and crossed_active and not crossed_previous:
                # $B4C7/$B84F tighten the active bound to the new incumbent.
                # Subsequent candidates then enter the seeded one-point path
                # against this value rather than repeatedly using the stale
                # node-entry bound.
                bound_raw = best
                frame.bound_raw = best
                self._record(frame, "raise-active-bound", move, stand)
            if crossed_previous:
                # $B4D5/$B85D updates move history only on a cutoff, and only
                # for selector phases 0 or 1.  Negative (primary-history) and
                # phase-2 candidates restore the frame without rotation.
                if frame.level < 8 and frame.selector in (0, 1):
                    if frame.selector == 0:
                        frame.previous_history_move = frame.history_move
                    frame.history_move = move
                    self._record(frame, "rotate-history", move, stand)
                self._record(frame, "previous-bound-cutoff", move, stand)
                break
        return best

    def score_root_move(self, board: Board, move: Move,
                        root_bound_raw: int,
                        history_seeds: dict[int, tuple[Move | None, Move | None]] |
                        None = None,
                        child_bound_raw: int | None = None,
                        iteration: int = 0,
                        child_previous_raw: int | None = None) -> int:
        side = board.side_to_move
        seeds = history_seeds or {}
        for level, (history, previous_history) in seeds.items():
            self.frames[level].history_move = history
            self.frames[level].previous_history_move = previous_history
        child_bound = (
            child_bound_raw if child_bound_raw is not None else
            (0x0F00 if side == BLACK else 0xF000)
        )
        board.make_move(*move)
        try:
            return self._search(
                board,
                1 - side,
                1,
                child_bound,
                (child_previous_raw if child_previous_raw is not None
                 else root_bound_raw),
                move,
                move[1],
                iteration,
            )
        finally:
            board.undo_move()

    def _root_iteration(self, board: Board, legal: list[Move],
                        preferred: Move | None,
                        root_bound_raw: int,
                        iteration: int = 0) -> tuple[Move, int]:
        side = board.side_to_move
        ordered = ([preferred] if preferred in legal else []) + [
            move for move in legal if move != preferred
        ]
        best_move = ordered[0]
        best_raw = self._initial_best(side)
        # $869C resets only the root incumbent; the per-level frames and their
        # history moves persist across root candidates and iterations.
        self.frames[0].best_raw = best_raw
        for move in ordered:
            nodes_before = self.nodes
            self.active_root_move = {
                "iteration": iteration,
                "move": move,
                "preferred": preferred,
                "nodes_before": nodes_before,
            }
            child_bound = None
            if preferred is not None and move != preferred:
                # Root $B29C/$B624 null-window entry after the previous
                # iteration's preferred move: red seeds active+1, black -1.
                child_bound = best_raw + (1 if side == RED else -1)
            best_before = best_raw
            score = self.score_root_move(
                board,
                move,
                best_raw,
                child_bound_raw=child_bound,
                iteration=iteration,
                child_previous_raw=(
                    root_bound_raw if preferred is not None and move == preferred
                    else None
                ),
            )
            probe_score = score if child_bound is not None else None
            if (child_bound is not None and side == RED and
                    self._better(side, score, best_raw)):
                # The red root's $B29C probe enters $B424 when its child raises
                # the incumbent.  Black root challengers in the traced corpus
                # retain the $B624 probe result; their symmetric alternate gate
                # is reached inside the recursive node rather than reopened by
                # the root iterator.
                score = self.score_root_move(
                    board,
                    move,
                    best_raw,
                    child_bound_raw=root_bound_raw,
                    child_previous_raw=best_raw,
                    iteration=iteration,
                )
            diagnostic = {
                "iteration": iteration,
                "move": move,
                "preferred": preferred,
                "root_bound_raw": root_bound_raw,
                "child_bound_raw": child_bound,
                "best_before_raw": best_before,
                "probe_score_raw": probe_score,
                "score_raw": score,
                "nodes": self.nodes - nodes_before,
            }
            self.root_move_nodes.append(diagnostic)
            self.active_root_move = None
            if self.capture_trace:
                self.root_trace.append(diagnostic)
            if self._better(side, score, best_raw):
                best_raw = score
                best_move = move
                self.frames[0].best_raw = score
        return best_move, best_raw

    def best_move(self, board: Board, depth: int = 1) -> tuple[Move | None, int]:
        side = board.side_to_move
        legal = generate_legal_moves(board, side)
        if not legal:
            return None, evaluate_raw(board)
        best_move: Move | None = None
        best_raw = self._initial_best(side)
        for iteration in range(depth):
            nodes_before = self.nodes
            root_bound = best_raw
            if iteration > 0:
                root_bound = best_raw + (-50 if side == RED else 50)
            best_move, best_raw = self._root_iteration(
                board, legal, best_move, root_bound, iteration
            )
            self.iteration_nodes.append(self.nodes - nodes_before)
        return best_move, best_raw


def run_corpus(path: Path, depth: int,
               max_nodes: int | None = DEFAULT_MAX_NODES,
               case_id: str | None = None) -> tuple[int, int, list[tuple]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    agreement = 0
    cases = data["cases"]
    if case_id is not None:
        cases = [case for case in cases if case["id"] == case_id]
        if not cases:
            raise KeyError(case_id)
    for case in cases:
        board = board_from_record(case["board"])
        experiment = SelectorBoundExperiment(max_nodes=max_nodes)
        want = tuple(case["best_move"]) if case["best_move"] else None
        try:
            got, raw = experiment.best_move(board, depth)
            limited = False
        except SearchLimitReached:
            got, raw = None, evaluate_raw(board)
            limited = True
        agreement += not limited and got == want
        rows.append((
            case["id"], want, got, raw, experiment.nodes, limited,
            tuple(experiment.iteration_nodes),
            tuple(experiment.root_move_nodes),
            experiment.active_root_move,
        ))
    return agreement, len(rows), rows


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--max-depth", type=int, default=2, choices=range(1, 5),
        help="highest corpus depth to execute (default: 2)",
    )
    parser.add_argument(
        "--case", default=None,
        help="run only one fixture case id, for example random-000",
    )
    parser.add_argument(
        "--only-depth", type=int, choices=range(1, 5),
        help="run only this corpus depth instead of all depths up to max-depth",
    )
    parser.add_argument(
        "--max-nodes", type=int, default=DEFAULT_MAX_NODES,
        help="per-case experimental node limit (0 disables the limit)",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="print every case result including matched moves and node counts",
    )
    args = parser.parse_args()
    max_nodes = None if args.max_nodes == 0 else args.max_nodes

    fixture_dir = _REPO_ROOT / "tests" / "fixtures"
    random015 = json.loads(
        (fixture_dir / "rom_depth1_independent.json").read_text(
            encoding="utf-8"
        )
    )
    case = next(case for case in random015["cases"] if case["id"] == "random-015")
    board = board_from_record(case["board"])
    experiment = SelectorBoundExperiment()
    raw = experiment.score_root_move(board, (52, 49), 32762)
    print(f"random-015 (52,49): raw={raw}, expected=32742, nodes={experiment.nodes}")

    corpora = (
        ("depth1-golden", "rom_depth1_golden.json", 1),
        ("depth1-independent", "rom_depth1_independent.json", 1),
        ("depth2-independent", "rom_depth2_independent.json", 2),
        ("depth3-independent", "rom_depth3_independent.json", 3),
        ("depth4-independent", "rom_depth4_independent.json", 4),
    )
    for name, filename, depth in corpora:
        path = fixture_dir / filename
        if not path.exists():
            continue
        if args.only_depth is not None and depth != args.only_depth:
            continue
        if depth > args.max_depth:
            print(
                f"{name}: fixture ready; pass --max-depth {depth} to run "
                f"with the explicit per-case node limit"
            )
            continue
        agreement, total, rows = run_corpus(
            path, depth, max_nodes=max_nodes, case_id=args.case
        )
        print(f"{name}: {agreement}/{total}")
        for (case_id, want, got, score, nodes, limited,
             iteration_nodes, root_move_nodes, active_root_move) in rows:
            if limited:
                print(
                    f"  {case_id}: node-limit after {nodes} nodes; "
                    f"ROM={want}; completed-iterations={iteration_nodes}"
                )
                if args.verbose and root_move_nodes:
                    last = root_move_nodes[-1]
                    print(
                        f"    last-complete-root-move: iteration="
                        f"{last['iteration']} move={last['move']} "
                        f"nodes={last['nodes']} score={last['score_raw']}"
                    )
                if args.verbose and active_root_move is not None:
                    active_nodes = nodes - active_root_move["nodes_before"]
                    print(
                        f"    active-root-move: iteration="
                        f"{active_root_move['iteration']} "
                        f"move={active_root_move['move']} nodes={active_nodes}"
                    )
            elif got != want:
                print(
                    f"  {case_id}: ROM={want} selector-bound={got} "
                    f"raw={score} nodes={nodes}"
                )
            elif args.verbose:
                print(
                    f"  {case_id}: ok move={got} raw={score} nodes={nodes} "
                    f"iterations={iteration_nodes}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
