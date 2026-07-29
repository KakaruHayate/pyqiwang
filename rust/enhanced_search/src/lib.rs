use std::collections::HashMap;
use std::slice;
use std::time::{Duration, Instant};

const RED: u8 = 0;
const BLACK: u8 = 1;
const KING: u8 = 1;
const ADVISOR: u8 = 2;
const ELEPHANT: u8 = 3;
const ROOK: u8 = 4;
const KNIGHT: u8 = 5;
const CANNON: u8 = 6;
const PAWN: u8 = 7;
const MATE: i32 = 30_000;
const INF: i32 = 32_000;
const EXACT: u8 = 0;
const LOWER: u8 = 1;
const UPPER: u8 = 2;

const TYPES: [u8; 16] = [
    KING, ROOK, ROOK, CANNON, CANNON, KNIGHT, KNIGHT, ADVISOR, ADVISOR, ELEPHANT, ELEPHANT, PAWN,
    PAWN, PAWN, PAWN, PAWN,
];
const MATERIAL: [i32; 8] = [0, 10_000, 100, 100, 500, 250, 250, 50];

#[derive(Clone, Copy)]
struct Move {
    from: u8,
    to: u8,
}
#[derive(Clone, Copy)]
struct Undo {
    mv: Move,
    moving: u8,
    captured: u8,
    captured_pos: u8,
}
#[derive(Clone, Copy)]
struct Entry {
    depth: i16,
    score: i32,
    flag: u8,
    mv: u16,
}

#[derive(Clone)]
struct Board {
    cells: [u8; 132],
    pieces: [[u8; 16]; 2],
}

impl Board {
    fn side_at(&self, pos: i32) -> Option<u8> {
        if !(0..132).contains(&pos) {
            return None;
        }
        let v = self.cells[pos as usize];
        if v == 0 {
            None
        } else {
            Some((v >> 5) & 1)
        }
    }
    fn valid(pos: i32) -> bool {
        pos >= 0 && pos / 12 <= 8 && pos % 12 <= 9
    }
    fn make(&mut self, mv: Move) -> Undo {
        let moving = self.cells[mv.from as usize];
        let captured = self.cells[mv.to as usize];
        let mut captured_pos = 0xff;
        if captured != 0 {
            let side = ((captured >> 5) & 1) as usize;
            let idx = (captured & 15) as usize;
            captured_pos = self.pieces[side][idx];
            self.pieces[side][idx] = 0xff;
        }
        self.cells[mv.to as usize] = moving;
        self.cells[mv.from as usize] = 0;
        self.pieces[((moving >> 5) & 1) as usize][(moving & 15) as usize] = mv.to;
        Undo {
            mv,
            moving,
            captured,
            captured_pos,
        }
    }
    fn unmake(&mut self, undo: Undo) {
        self.cells[undo.mv.from as usize] = undo.moving;
        self.cells[undo.mv.to as usize] = undo.captured;
        self.pieces[((undo.moving >> 5) & 1) as usize][(undo.moving & 15) as usize] = undo.mv.from;
        if undo.captured != 0 {
            self.pieces[((undo.captured >> 5) & 1) as usize][(undo.captured & 15) as usize] =
                undo.captured_pos;
        }
    }
    fn moves(&self, side: u8, captures_only: bool) -> Vec<Move> {
        let mut out = Vec::with_capacity(64);
        for idx in 0..16 {
            let p = self.pieces[side as usize][idx];
            if p == 0xff {
                continue;
            }
            let pos = p as i32;
            let piece = TYPES[idx];
            let mut push = |to: i32| {
                if !Board::valid(to) || self.side_at(to) == Some(side) {
                    return;
                }
                if !captures_only || self.cells[to as usize] != 0 {
                    out.push(Move {
                        from: p,
                        to: to as u8,
                    });
                }
            };
            match piece {
                KING => {
                    for d in [-1, 1, -12, 12] {
                        let to = pos + d;
                        if Board::valid(to) {
                            let f = to / 12;
                            let r = to % 12;
                            let palace =
                                f >= 3 && f <= 5 && if side == RED { r <= 2 } else { r >= 7 };
                            if palace {
                                push(to);
                            }
                        }
                    }
                }
                ADVISOR => {
                    for d in [-13, 11, -11, 13] {
                        let to = pos + d;
                        if Board::valid(to) {
                            let f = to / 12;
                            let r = to % 12;
                            let palace =
                                f >= 3 && f <= 5 && if side == RED { r <= 2 } else { r >= 7 };
                            if palace {
                                push(to);
                            }
                        }
                    }
                }
                ELEPHANT => {
                    for (d, leg) in [(-26, -13), (22, 11), (-22, -11), (26, 13)] {
                        let to = pos + d;
                        if Board::valid(to) && self.cells[(pos + leg) as usize] == 0 {
                            let r = to % 12;
                            if (side == RED && r <= 4) || (side == BLACK && r >= 5) {
                                push(to);
                            }
                        }
                    }
                }
                KNIGHT => {
                    for (d, leg) in [
                        (-14, -1),
                        (10, -1),
                        (-10, 1),
                        (14, 1),
                        (-25, -12),
                        (-23, -12),
                        (23, 12),
                        (25, 12),
                    ] {
                        let to = pos + d;
                        if Board::valid(to) && self.cells[(pos + leg) as usize] == 0 {
                            push(to);
                        }
                    }
                }
                ROOK | CANNON => {
                    for d in [-1, 1, -12, 12] {
                        let mut to = pos + d;
                        let mut screen = false;
                        while Board::valid(to) {
                            let occupied = self.cells[to as usize] != 0;
                            if piece == ROOK {
                                if occupied {
                                    if self.side_at(to) != Some(side) {
                                        push(to);
                                    }
                                    break;
                                } else if !captures_only {
                                    push(to);
                                }
                            } else if !screen {
                                if occupied {
                                    screen = true;
                                } else if !captures_only {
                                    push(to);
                                }
                            } else if occupied {
                                if self.side_at(to) != Some(side) {
                                    push(to);
                                }
                                break;
                            }
                            to += d;
                        }
                    }
                }
                PAWN => {
                    let fwd = if side == RED { 1 } else { -1 };
                    push(pos + fwd);
                    let r = pos % 12;
                    if (side == RED && r >= 5) || (side == BLACK && r <= 4) {
                        push(pos - 12);
                        push(pos + 12);
                    }
                }
                _ => {}
            }
        }
        out
    }
    fn attacked(&self, target: u8, by: u8) -> bool {
        for mv in self.moves(by, false) {
            if mv.to == target {
                return true;
            }
        }
        false
    }
    fn in_check(&self, side: u8) -> bool {
        let king = self.pieces[side as usize][0];
        if king == 0xff {
            return true;
        }
        if self.attacked(king, 1 - side) {
            return true;
        }
        let other = self.pieces[(1 - side) as usize][0];
        if other != 0xff && king / 12 == other / 12 {
            let (lo, hi) = if king < other {
                (king, other)
            } else {
                (other, king)
            };
            let mut p = lo + 1;
            while p < hi {
                if self.cells[p as usize] != 0 {
                    return false;
                }
                p += 1;
            }
            return true;
        }
        false
    }
    fn evaluate(&self, side: u8) -> i32 {
        let mut score = 0;
        for s in 0..=1 {
            let sign = if s == side { 1 } else { -1 };
            for i in 0..16 {
                let p = self.pieces[s as usize][i];
                if p == 0xff {
                    continue;
                }
                let pt = TYPES[i] as usize;
                let file = (p / 12) as i32;
                let rank = (p % 12) as i32;
                let forward = if s == RED { rank } else { 9 - rank };
                let mut v = MATERIAL[pt];
                if pt == PAWN as usize {
                    v += forward * 5;
                    if forward >= 5 {
                        v += 18 + (4 - (file - 4).abs()) * 2;
                    }
                } else if pt == KNIGHT as usize || pt == CANNON as usize || pt == ROOK as usize {
                    v += 4 - (file - 4).abs();
                }
                score += sign * v;
            }
        }
        score
    }
    fn hash(&self, side: u8) -> u64 {
        let mut h = 1469598103934665603u64;
        for &v in &self.cells {
            h ^= v as u64;
            h = h.wrapping_mul(1099511628211);
        }
        h ^ side as u64
    }
}

struct Search {
    tt: HashMap<u64, Entry>,
    killers: [[u16; 2]; 64],
    history: [[[i32; 132]; 132]; 2],
    nodes: u64,
    qnodes: u64,
    hits: u64,
    cutoffs: u64,
    beta: u64,
    deadline: Option<Instant>,
    timeout: bool,
    tt_limit: usize,
}
impl Search {
    fn new(tt_limit: usize, ms: u64) -> Self {
        Self {
            tt: HashMap::with_capacity(tt_limit.min(1_000_000)),
            killers: [[0xffff; 2]; 64],
            history: [[[0; 132]; 132]; 2],
            nodes: 0,
            qnodes: 0,
            hits: 0,
            cutoffs: 0,
            beta: 0,
            deadline: if ms == 0 {
                None
            } else {
                Some(Instant::now() + Duration::from_millis(ms))
            },
            timeout: false,
            tt_limit,
        }
    }
    fn expired(&mut self) -> bool {
        if self.timeout {
            return true;
        }
        if let Some(d) = self.deadline {
            if Instant::now() >= d {
                self.timeout = true;
            }
        }
        self.timeout
    }
    fn code(m: Move) -> u16 {
        ((m.from as u16) << 8) | m.to as u16
    }
    fn order(&self, b: &Board, moves: &mut [Move], side: u8, ply: usize, tt: u16) {
        moves.sort_unstable_by_key(|m| {
            let c = Self::code(*m);
            let victim = b.cells[m.to as usize];
            let p = if c == tt {
                1 << 30
            } else if victim != 0 {
                (1 << 25) + MATERIAL[TYPES[(victim & 15) as usize] as usize] * 32
                    - MATERIAL[TYPES[(b.cells[m.from as usize] & 15) as usize] as usize]
            } else if self.killers[ply.min(63)].contains(&c) {
                1 << 22
            } else {
                self.history[side as usize][m.from as usize][m.to as usize]
            };
            -p
        });
    }
    fn q(&mut self, b: &mut Board, side: u8, mut alpha: i32, beta: i32, ply: i32) -> i32 {
        self.qnodes += 1;
        if (self.qnodes & 2047) == 0 && self.expired() {
            return alpha;
        }
        if b.pieces[side as usize][0] == 0xff {
            return -MATE + ply;
        }
        if b.pieces[(1 - side) as usize][0] == 0xff {
            return MATE - ply;
        }
        let checked = b.in_check(side);
        let stand = b.evaluate(side);
        if !checked {
            if stand >= beta {
                return stand;
            }
            if stand > alpha {
                alpha = stand;
            }
        }
        if ply >= 32 {
            return if checked { stand } else { alpha };
        }
        let mut moves = b.moves(side, !checked);
        self.order(b, &mut moves, side, ply as usize, 0xffff);
        let mut legal = 0;
        for mv in moves {
            let u = b.make(mv);
            if b.in_check(side) {
                b.unmake(u);
                continue;
            }
            legal += 1;
            let s = -self.q(b, 1 - side, -beta, -alpha, ply + 1);
            b.unmake(u);
            if self.timeout {
                return alpha;
            }
            if s >= beta {
                return s;
            }
            if s > alpha {
                alpha = s;
            }
        }
        if checked && legal == 0 {
            -MATE + ply
        } else {
            alpha
        }
    }
    fn pvs(
        &mut self,
        b: &mut Board,
        side: u8,
        depth: i32,
        mut alpha: i32,
        mut beta: i32,
        ply: i32,
    ) -> i32 {
        self.nodes += 1;
        if (self.nodes & 2047) == 0 && self.expired() {
            return alpha;
        }
        if b.pieces[side as usize][0] == 0xff {
            return -MATE + ply;
        }
        if b.pieces[(1 - side) as usize][0] == 0xff {
            return MATE - ply;
        }
        if depth <= 0 {
            return self.q(b, side, alpha, beta, ply);
        }
        let orig = alpha;
        let key = b.hash(side);
        let entry = self.tt.get(&key).copied();
        let tt = entry.map_or(0xffff, |e| e.mv);
        if let Some(e) = entry {
            if e.depth >= depth as i16 {
                self.hits += 1;
                if e.flag == EXACT {
                    return e.score;
                }
                if e.flag == LOWER {
                    alpha = alpha.max(e.score);
                } else {
                    beta = beta.min(e.score);
                }
                if alpha >= beta {
                    self.cutoffs += 1;
                    return e.score;
                }
            }
        }
        let mut moves = b.moves(side, false);
        self.order(b, &mut moves, side, ply as usize, tt);
        let mut best = -INF;
        let mut bestm = 0xffff;
        let mut legal = 0;
        for mv in moves {
            let captured = b.cells[mv.to as usize];
            let u = b.make(mv);
            if b.in_check(side) {
                b.unmake(u);
                continue;
            }
            legal += 1;
            let mut s;
            if legal == 1 {
                s = -self.pvs(b, 1 - side, depth - 1, -beta, -alpha, ply + 1);
            } else {
                s = -self.pvs(b, 1 - side, depth - 1, -alpha - 1, -alpha, ply + 1);
                if s > alpha && s < beta {
                    s = -self.pvs(b, 1 - side, depth - 1, -beta, -alpha, ply + 1);
                }
            }
            b.unmake(u);
            if self.timeout {
                return alpha;
            }
            if s > best {
                best = s;
                bestm = Self::code(mv);
            }
            if s > alpha {
                alpha = s;
            }
            if alpha >= beta {
                self.beta += 1;
                if captured == 0 {
                    let p = ply.min(63) as usize;
                    if self.killers[p][0] != bestm {
                        self.killers[p][1] = self.killers[p][0];
                        self.killers[p][0] = bestm;
                    }
                    self.history[side as usize][mv.from as usize][mv.to as usize] += depth * depth;
                }
                break;
            }
        }
        if legal == 0 {
            return -MATE + ply;
        }
        let flag = if best <= orig {
            UPPER
        } else if best >= beta {
            LOWER
        } else {
            EXACT
        };
        if self.tt.len() >= self.tt_limit {
            self.tt.clear();
        }
        self.tt.insert(
            key,
            Entry {
                depth: depth as i16,
                score: best,
                flag,
                mv: bestm,
            },
        );
        best
    }
    fn root(&mut self, b: &mut Board, side: u8, depth: i32, preferred: u16) -> (i32, u16) {
        let (mut alpha, beta) = (-INF, INF);
        let (mut best, mut bestm, mut legal) = (-INF, 0xffff, 0);
        let mut moves = b.moves(side, false);
        self.order(b, &mut moves, side, 0, preferred);
        for mv in moves {
            let u = b.make(mv);
            if b.in_check(side) {
                b.unmake(u);
                continue;
            }
            legal += 1;
            let mut s;
            if legal == 1 {
                s = -self.pvs(b, 1 - side, depth - 1, -beta, -alpha, 1);
            } else {
                s = -self.pvs(b, 1 - side, depth - 1, -alpha - 1, -alpha, 1);
                if s > alpha && s < beta {
                    s = -self.pvs(b, 1 - side, depth - 1, -beta, -alpha, 1);
                }
            }
            b.unmake(u);
            if self.timeout {
                break;
            }
            if s > best {
                best = s;
                bestm = Self::code(mv);
            }
            if s > alpha {
                alpha = s;
            }
        }
        if legal == 0 {
            (-MATE, 0xffff)
        } else {
            (best, bestm)
        }
    }
}

#[repr(C)]
pub struct SearchResult {
    pub move_code: u16,
    pub score: i32,
    pub depth: u32,
    pub nodes: u64,
    pub qnodes: u64,
    pub tt_hits: u64,
    pub tt_cutoffs: u64,
    pub beta_cutoffs: u64,
    pub tt_entries: u64,
    pub elapsed_ms: u64,
}

#[no_mangle]
pub unsafe extern "C" fn qiwang_enhanced_search(
    cells: *const u8,
    pieces: *const u8,
    side: u8,
    max_depth: u32,
    time_ms: u64,
    tt_size: u64,
    out: *mut SearchResult,
) -> i32 {
    if cells.is_null() || pieces.is_null() || out.is_null() {
        return -1;
    }
    let c = slice::from_raw_parts(cells, 132);
    let p = slice::from_raw_parts(pieces, 32);
    let mut board = Board {
        cells: [0; 132],
        pieces: [[0xff; 16]; 2],
    };
    board.cells.copy_from_slice(c);
    board.pieces[0].copy_from_slice(&p[..16]);
    board.pieces[1].copy_from_slice(&p[16..]);
    let start = Instant::now();
    let mut search = Search::new(tt_size as usize, time_ms);
    let mut best = 0xffff;
    let mut score = board.evaluate(side);
    let mut completed = 0;
    for d in 1..=max_depth {
        let (s, m) = search.root(&mut board, side, d as i32, best);
        if search.timeout {
            break;
        }
        score = s;
        best = m;
        completed = d;
        if score.abs() >= MATE - 128 {
            break;
        }
    }
    *out = SearchResult {
        move_code: best,
        score,
        depth: completed,
        nodes: search.nodes,
        qnodes: search.qnodes,
        tt_hits: search.hits,
        tt_cutoffs: search.cutoffs,
        beta_cutoffs: search.beta,
        tt_entries: search.tt.len() as u64,
        elapsed_ms: start.elapsed().as_millis() as u64,
    };
    0
}
