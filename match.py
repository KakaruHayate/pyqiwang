"""
match.py — 棋王 (1990s FC ROM AI) vs a modern Xiangqi engine.

Plays a full game between:

* **pyqiwang** — the reverse-engineered 棋王 AI, running the ROM's own
  ``$8597`` search inside a 6502 emulator (bit-exact with the original game).
* **modern_ai** — either Pikafish over UCI, or the bundled pure-Python
  alpha-beta engine.

Visualisation:

* live colour board in the terminal, and
* a self-contained HTML replay with a move slider, written at the end.

Usage::

    python match.py                             # ROM plays Red, default depths
    python match.py --rom-side black
    python match.py --rom-depth 3 --modern-depth 6
    python match.py --out replay.html
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
import time
from typing import Optional

from pyqiwang import QiWangEngine, Board, RED, BLACK
from pyqiwang._board import (
    PIECE_TYPES, PIECE_NAMES, PIECE_NAMES_BLACK,
    generate_legal_moves, is_in_check, BOARD_STRIDE,
)
from modern_ai import ModernEngine, PikafishEngine, find_pikafish


FILES = 'abcdefghi'


# ══════════════════════════════════════════════════════════════
#  Notation
# ══════════════════════════════════════════════════════════════

def sq(pos: int) -> str:
    """Board position -> algebraic square, e.g. 86 -> 'h2'."""
    return f"{FILES[pos // BOARD_STRIDE]}{pos % BOARD_STRIDE}"


def piece_name(board: Board, pos: int) -> str:
    val = board.cells[pos]
    if not val:
        return ''
    side = (val >> 5) & 1
    ptype = PIECE_TYPES[val & 0x0F]
    return (PIECE_NAMES if side == RED else PIECE_NAMES_BLACK)[ptype]


def describe(board: Board, frm: int, to: int) -> str:
    """Human-readable move, e.g. '炮 h2-e2' or '车 a0xa9'."""
    name = piece_name(board, frm)
    sep = 'x' if board.cells[to] else '-'
    captured = piece_name(board, to)
    text = f"{name} {sq(frm)}{sep}{sq(to)}"
    return f"{text} ({captured})" if captured else text


# ══════════════════════════════════════════════════════════════
#  Terminal rendering
# ══════════════════════════════════════════════════════════════

_ANSI_RED = '\033[91m'
_ANSI_BLUE = '\033[94m'
_ANSI_DIM = '\033[90m'
_ANSI_HL = '\033[43;30m'
_ANSI_OFF = '\033[0m'


def render_terminal(board: Board, last: Optional[tuple[int, int]] = None,
                    header: str = '') -> None:
    """Draw the board, Red at the bottom, with the last move highlighted."""
    lines = []
    if header:
        lines.append(header)
    lines.append('    ' + '  '.join(f' {f}' for f in FILES))
    for rank in range(9, -1, -1):
        row = f' {rank} '
        for file in range(9):
            pos = file * BOARD_STRIDE + rank
            val = board.cells[pos]
            if val:
                side = (val >> 5) & 1
                ch = piece_name(board, pos)
                colour = _ANSI_RED if side == RED else _ANSI_BLUE
            else:
                ch = '·'
                colour = _ANSI_DIM
            if last and pos in last:
                row += f'{_ANSI_HL}{ch}{_ANSI_OFF} '
            else:
                row += f'{colour}{ch}{_ANSI_OFF} '
            if file < 8:
                row += ' '
        row += f' {rank}'
        lines.append(row)
        if rank == 5:
            lines.append(f'    {_ANSI_DIM}—— 楚河    漢界 ——{_ANSI_OFF}')
    lines.append('    ' + '  '.join(f' {f}' for f in FILES))
    print('\n'.join(lines))


# ══════════════════════════════════════════════════════════════
#  HTML replay
# ══════════════════════════════════════════════════════════════

_HTML = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>棋王 ROM AI vs %(modern)s</title>
<style>
 body{margin:0;background:#1d1f21;color:#e8e6e3;
      font-family:"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
 .wrap{max-width:980px;margin:0 auto;padding:24px}
 h1{font-size:20px;font-weight:600;margin:0 0 4px}
 .sub{color:#9aa0a6;font-size:13px;margin-bottom:20px}
 .main{display:flex;gap:24px;flex-wrap:wrap}
 canvas{background:#f0d9a7;border-radius:6px}
 .side{flex:1;min-width:280px}
 .ctl{display:flex;gap:8px;align-items:center;margin:14px 0}
 button{background:#3a3d41;color:#e8e6e3;border:0;border-radius:5px;
        padding:7px 13px;cursor:pointer;font-size:14px}
 button:hover{background:#4a4e53}
 input[type=range]{flex:1}
 .status{font-size:14px;margin:8px 0 14px;min-height:22px}
 .badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:12px}
 .rom{background:#7b2d2d;color:#ffd9d9}.mod{background:#24506b;color:#cfe8ff}
 table{width:100%%;border-collapse:collapse;font-size:13px}
 th,td{text-align:left;padding:4px 8px;border-bottom:1px solid #33363a}
 th{color:#9aa0a6;font-weight:500}
 tr.on{background:#2f3337}tr{cursor:pointer}
 .r{color:#ff8080}.b{color:#8fc4ff}
 .scroll{max-height:420px;overflow:auto}
</style></head><body><div class="wrap">
<h1>棋王 ROM AI &nbsp;vs&nbsp; %(modern)s</h1>
<div class="sub">%(subtitle)s</div>
<div class="main">
 <div>
  <canvas id="cv" width="450" height="500"></canvas>
  <div class="ctl">
   <button onclick="go(0)">⏮</button><button onclick="step(-1)">◀</button>
   <button id="pp" onclick="play()">▶ 播放</button>
   <button onclick="step(1)">▶</button><button onclick="go(MOVES.length)">⏭</button>
  </div>
  <input type="range" id="sl" min="0" max="%(nmoves)d" value="0"
         oninput="go(+this.value)" style="width:100%%">
 </div>
 <div class="side">
  <div class="status" id="st"></div>
  <div class="scroll"><table><thead><tr><th>#</th><th>方</th><th>引擎</th>
  <th>走法</th><th>评分</th><th>用时</th></tr></thead>
  <tbody id="tb"></tbody></table></div>
 </div>
</div></div>
<script>
const MOVES=%(moves)s, START=%(start)s, RESULT=%(result)s;
const CN={1:'\\u5e05',2:'\\u4ed5',3:'\\u76f8',4:'\\u8f66',5:'\\u9a6c',6:'\\u70ae',7:'\\u5175'};
const CNB={1:'\\u5c06',2:'\\u58eb',3:'\\u8c61',4:'\\u8eca',5:'\\u99ac',6:'\\u7832',7:'\\u5352'};
const M=30, CELL=48, cv=document.getElementById('cv'), cx=cv.getContext('2d');
let idx=0, timer=null;

function boardAt(n){
  let b=JSON.parse(JSON.stringify(START));
  for(let i=0;i<n;i++){const m=MOVES[i]; b[m.to]=b[m.frm]; delete b[m.frm];}
  return b;
}
function xy(pos){return [M+Math.floor(pos/12)*CELL, M+(9-(pos%%12))*CELL];}

function draw(){
  const b=boardAt(idx);
  cx.fillStyle='#f0d9a7';cx.fillRect(0,0,cv.width,cv.height);
  cx.strokeStyle='#7a5c33';cx.lineWidth=1;
  for(let r=0;r<10;r++){cx.beginPath();cx.moveTo(M,M+r*CELL);
    cx.lineTo(M+8*CELL,M+r*CELL);cx.stroke();}
  for(let f=0;f<9;f++){
    if(f===0||f===8){cx.beginPath();cx.moveTo(M+f*CELL,M);
      cx.lineTo(M+f*CELL,M+9*CELL);cx.stroke();}
    else{cx.beginPath();cx.moveTo(M+f*CELL,M);cx.lineTo(M+f*CELL,M+4*CELL);cx.stroke();
      cx.beginPath();cx.moveTo(M+f*CELL,M+5*CELL);cx.lineTo(M+f*CELL,M+9*CELL);cx.stroke();}}
  cx.beginPath();cx.moveTo(M+3*CELL,M);cx.lineTo(M+5*CELL,M+2*CELL);
  cx.moveTo(M+5*CELL,M);cx.lineTo(M+3*CELL,M+2*CELL);
  cx.moveTo(M+3*CELL,M+7*CELL);cx.lineTo(M+5*CELL,M+9*CELL);
  cx.moveTo(M+5*CELL,M+7*CELL);cx.lineTo(M+3*CELL,M+9*CELL);cx.stroke();
  cx.fillStyle='#8a6a3d';cx.font='16px serif';cx.textAlign='center';
  cx.fillText('\\u695a\\u6cb3          \\u6f22\\u754c', M+4*CELL, M+4.6*CELL);

  if(idx>0){const m=MOVES[idx-1];
    for(const p of [m.frm,m.to]){const [x,y]=xy(p);
      cx.fillStyle='rgba(255,200,0,.45)';cx.beginPath();
      cx.arc(x,y,CELL*0.44,0,7);cx.fill();}}

  for(const k in b){const [t,s]=b[k], [x,y]=xy(+k);
    cx.beginPath();cx.arc(x,y,CELL*0.40,0,7);
    cx.fillStyle=s===0?'#fff4e0':'#3b3b3b';cx.fill();
    cx.lineWidth=2;cx.strokeStyle=s===0?'#c0392b':'#1a1a1a';cx.stroke();
    cx.fillStyle=s===0?'#c0392b':'#7fb3ff';
    cx.font='bold 24px "PingFang SC","Microsoft YaHei",serif';
    cx.textBaseline='middle';cx.fillText(s===0?CN[t]:CNB[t],x,y+1);}

  document.getElementById('sl').value=idx;
  const st=document.getElementById('st');
  if(idx===0) st.textContent='\\u521d\\u59cb\\u5c40\\u9762';
  else{const m=MOVES[idx-1];
    st.innerHTML=`<span class="badge ${m.eng==='rom'?'rom':'mod'}">${m.engname}</span> `+
      `<b>${m.text}</b> &nbsp;<span style="color:#9aa0a6">${m.score} · ${m.t}s</span>`;}
  if(idx===MOVES.length&&RESULT) st.innerHTML+=`<br><b>${RESULT}</b>`;
  document.querySelectorAll('#tb tr').forEach((r,i)=>
    r.className=(i===idx-1)?'on':'');
  const cur=document.querySelector('#tb tr.on'); if(cur) cur.scrollIntoView({block:'nearest'});
}
function go(n){idx=Math.max(0,Math.min(MOVES.length,n));draw();}
function step(d){go(idx+d);}
function play(){
  const btn=document.getElementById('pp');
  if(timer){clearInterval(timer);timer=null;btn.textContent='\\u25b6 \\u64ad\\u653e';return;}
  btn.textContent='\\u23f8 \\u6682\\u505c';
  timer=setInterval(()=>{if(idx>=MOVES.length){clearInterval(timer);timer=null;
    btn.textContent='\\u25b6 \\u64ad\\u653e';}else step(1);},750);
}
const tb=document.getElementById('tb');
MOVES.forEach((m,i)=>{const tr=document.createElement('tr');
  tr.onclick=()=>go(i+1);
  tr.innerHTML=`<td>${i+1}</td><td class="${m.side==='R'?'r':'b'}">`+
    `${m.side==='R'?'\\u7ea2':'\\u9ed1'}</td><td>${m.engname}</td>`+
    `<td>${m.text}</td><td>${m.score}</td><td>${m.t}</td>`;
  tb.appendChild(tr);});
document.onkeydown=e=>{if(e.key==='ArrowLeft')step(-1);
  if(e.key==='ArrowRight')step(1);};
draw();
</script></body></html>
"""


def write_html(path: str, start: Board, moves: list[dict],
               modern_name: str, subtitle: str, result: str) -> None:
    start_map = {}
    for side in (RED, BLACK):
        for idx in range(16):
            pos = start.pieces[side][idx]
            if pos >= 0:
                start_map[str(pos)] = [PIECE_TYPES[idx], side]
    page = _HTML % {
        'modern': html.escape(modern_name),
        'subtitle': html.escape(subtitle),
        'nmoves': len(moves),
        'moves': json.dumps(moves, ensure_ascii=False),
        'start': json.dumps(start_map),
        'result': json.dumps(result, ensure_ascii=False),
    }
    with open(path, 'w', encoding='utf-8') as f:
        f.write(page)


# ══════════════════════════════════════════════════════════════
#  Match driver
# ══════════════════════════════════════════════════════════════

def play_match(rom_depth: int = 2, modern_depth: int = 5,
               modern_time: float = 5.0, rom_side: int = RED,
               max_moves: int = 200, out: str = 'replay.html',
               use_pikafish: bool = True, quiet: bool = False,
               rom_book: bool = True) -> dict:
    rom = QiWangEngine(depth=rom_depth, book=rom_book)

    modern = None
    if use_pikafish and find_pikafish():
        try:
            modern = PikafishEngine(depth=max(modern_depth, 10))
        except Exception as exc:
            print(f"Pikafish unavailable ({exc}); using the built-in engine.")
    if modern is None:
        modern = ModernEngine(depth=modern_depth, time_limit=modern_time)

    rom_name = f"棋王 ROM (depth {rom_depth})"
    modern_name = modern.name

    print("=" * 62)
    print(f"  {'红' if rom_side == RED else '黑'}  {rom_name}")
    print(f"  {'黑' if rom_side == RED else '红'}  {modern_name}")
    print("=" * 62)

    board = Board()
    start = board.clone()
    moves: list[dict] = []
    result = ''
    reason = ''

    # Simple repetition guard: identical position seen 3 times = draw.
    seen: dict[tuple, int] = {}

    for ply in range(max_moves):
        side = board.side_to_move
        legal = generate_legal_moves(board, side)
        if not legal:
            loser = '红' if side == RED else '黑'
            winner = '黑' if side == RED else '红'
            reason = '将死' if is_in_check(board, side) else '困毙'
            result = f"{winner}方胜（{loser}方{reason}，第 {ply} 手）"
            break

        is_rom = (side == rom_side)
        engine = rom if is_rom else modern
        label = rom_name if is_rom else modern_name

        t0 = time.time()
        from_book = False
        if is_rom:
            from_book = rom_book and rom._book_applies(board)
            move = rom.get_best_move(board)
            score = rom.evaluate(board)
        else:
            move = modern.search(board, side)
            score = modern.last_score
        elapsed = time.time() - t0

        if move is None or move not in legal:
            winner = '黑' if side == RED else '红'
            bad = 'returned an illegal move' if move else 'resigned'
            result = f"{winner}方胜（对方{bad}，第 {ply} 手）"
            break

        text = describe(board, *move)
        moves.append({
            'frm': move[0], 'to': move[1],
            'side': 'R' if side == RED else 'B',
            'eng': 'rom' if is_rom else 'modern',
            'engname': (rom_name + ' 谱') if from_book else
                       (rom_name if is_rom else modern_name),
            'text': text, 'score': score, 't': round(elapsed, 1),
        })

        if not quiet:
            tag = '\033[91m红\033[0m' if side == RED else '\033[94m黑\033[0m'
            src = '  [开局谱]' if from_book else ''
            print(f"\n第 {ply + 1:3d} 手  {tag}  {label}{src}")
            print(f"        {text}   score={score}  {elapsed:.1f}s")
            render_terminal(board.clone(), last=move)

        board.make_move(*move)

        key = (tuple(board.pieces[RED]), tuple(board.pieces[BLACK]),
               board.side_to_move)
        seen[key] = seen.get(key, 0) + 1
        if seen[key] >= 3:
            result = f"和棋（三次重复局面，第 {ply + 1} 手）"
            break
    else:
        result = f"和棋（达到 {max_moves} 手上限）"

    print("\n" + "=" * 62)
    print(f"  结果: {result}")
    print(f"  总手数: {len(moves)}")
    print("=" * 62)

    subtitle = (f"{rom_name} 执{'红' if rom_side == RED else '黑'} · "
                f"{modern_name} 执{'黑' if rom_side == RED else '红'} · "
                f"共 {len(moves)} 手")
    write_html(out, start, moves, modern_name, subtitle, result)
    print(f"  复盘已写入: {os.path.abspath(out)}")

    if isinstance(modern, PikafishEngine):
        modern.close()

    return {'result': result, 'moves': moves, 'plies': len(moves)}


def main() -> None:
    p = argparse.ArgumentParser(
        description='棋王 ROM AI vs a modern Xiangqi engine')
    p.add_argument('--rom-depth', type=int, default=2,
                   help='棋王 ROM search depth (2=初级 3=中级 4=高级)')
    p.add_argument('--modern-depth', type=int, default=5,
                   help='modern engine search depth')
    p.add_argument('--modern-time', type=float, default=5.0,
                   help='modern engine seconds per move (built-in engine)')
    p.add_argument('--rom-side', choices=['red', 'black'], default='red',
                   help='which side the ROM AI plays')
    p.add_argument('--moves', type=int, default=200, help='max plies')
    p.add_argument('--out', default='replay.html', help='HTML replay path')
    p.add_argument('--no-pikafish', action='store_true',
                   help='always use the built-in engine')
    p.add_argument('--no-book', action='store_true',
                   help="disable the ROM's opening book")
    p.add_argument('--quiet', action='store_true',
                   help='do not draw the board each move')
    a = p.parse_args()

    if sys.platform == 'win32':
        os.system('')  # enable ANSI colour in the Windows console
        # The console defaults to a legacy codepage, which mangles the
        # Chinese piece glyphs; force UTF-8 on the streams we write to.
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding='utf-8', errors='replace')
            except (AttributeError, OSError):
                pass

    play_match(rom_depth=a.rom_depth, modern_depth=a.modern_depth,
               modern_time=a.modern_time,
               rom_side=RED if a.rom_side == 'red' else BLACK,
               max_moves=a.moves, out=a.out,
               use_pikafish=not a.no_pikafish, quiet=a.quiet,
               rom_book=not a.no_book)


if __name__ == '__main__':
    main()
