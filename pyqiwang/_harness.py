"""
rom_harness.py — 《棋王》ROM 仿真 harness
加载 ROM、模拟 Mapper 133 总线、调用 ROM 内子程序获取 ground truth。

用法示例:
    from rom_harness import RomHarness
    h = RomHarness()
    h.reset_init()          # 跑 ROM 自身初始化
    ...
"""
import os
from pyqiwang._mos6502 import MOS6502, CPUError

ROM_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        '棋王(繁)[小天才](CN)[TAB](0.75Mb).nes')

# 哨兵返回地址：call_subroutine 压栈 SENTINEL-1，RTS 回到 SENTINEL 时停止
SENTINEL = 0x0001


class Mapper133Bus:
    """Sachen SA-72008 (Mapper 133) 总线模型。

    - $0000-$1FFF: 2KB RAM（镜像）
    - $2000-$3FFF: PPU 寄存器（哑实现；$2002 交替返回 VBlank 位防死循环）
    - $4000-$40FF: APU/IO（哑实现）
    - $4100-$41FF: Mapper 寄存器（写入低 3 位：bit2=PRG bank, bit0-1=CHR）
    - $8000-$FFFF: PRG ROM
    PRG 映射策略可配置（先按 REPORT.md 的 16KB 模型，如与 $FF2C 实测不符再调）。
    """

    def __init__(self, prg):
        assert len(prg) == 0x10000, f"PRG 应为 64KB, got {len(prg)}"
        self.prg = prg
        self.ram = bytearray(0x800)
        self.reg4100 = 0
        self.prg_bank = 1          # 32KB bank: 0=棋谱数据, 1=程序代码（上电默认）
        self.ppustatus_toggle = False
        # 调试钩子: addr -> callback(addr, value, is_write)
        self.write_hooks = {}
        self.read_hooks = {}
        self.open_bus = 0
        # 手柄 ($4016): 8位状态 A,B,Select,Start,Up,Down,Left,Right
        self.pad1 = 0
        self._pad1_shift = 0
        self._pad_strobe = 0

    def read(self, addr):
        if addr < 0x2000:
            v = self.ram[addr & 0x7FF]
        elif addr < 0x4000:
            if (addr & 7) == 2:  # PPUSTATUS: 交替置 VBlank 位，打破等待循环
                self.ppustatus_toggle = not self.ppustatus_toggle
                v = 0x80 if self.ppustatus_toggle else 0x00
            else:
                v = 0
        elif addr == 0x4016:
            if self._pad_strobe & 1:
                v = self.pad1 & 1
            else:
                v = self._pad1_shift & 1
                self._pad1_shift = (self._pad1_shift >> 1) | 0x80
        elif addr < 0x8000:
            v = self.open_bus
        else:
            v = self.prg[self.prg_bank * 0x8000 + (addr - 0x8000)]
        hook = self.read_hooks.get(addr)
        if hook:
            hook(addr, v, False)
        self.open_bus = v
        return v

    def write(self, addr, val):
        hook = self.write_hooks.get(addr)
        if hook:
            hook(addr, val, True)
        if addr < 0x2000:
            self.ram[addr & 0x7FF] = val
        elif addr == 0x4016:
            if (self._pad_strobe & 1) and not (val & 1):
                self._pad1_shift = self.pad1
            self._pad_strobe = val
        elif addr == 0x4102:
            # Mapper 133/TXC: 仅 $4102 的数据写入决定 bank
            # (实测 $FF2C 切换序列: $4101=0, $4102=bankval, $4103=0,
            #  $4100=0, $4103=$FF —— 其余均为锁存/选通操作)
            # $FF4D 表: 27 26 25 24 | 03 02 01 00 → bit2 = PRG 32KB bank
            self.reg4100 = val
            self.prg_bank = (val >> 2) & 1
        # 其余（PPU/APU/ROM 区）忽略写入


class RomHarness:
    def __init__(self, rom_path=ROM_PATH):
        with open(rom_path, 'rb') as f:
            rom = f.read()
        assert rom[:4] == b'NES\x1a', "非法 iNES 文件"
        prg_banks = rom[4]
        prg = rom[16:16 + prg_banks * 0x4000]
        assert len(prg) == 0x10000, f"期望 64KB PRG, got {len(prg)}"
        self.bus = Mapper133Bus(prg)
        self.cpu = MOS6502(self.bus)
        self.instr_count = 0

    # ---------- 低层执行 ----------
    def run_until(self, stop_pcs, max_instructions=50_000_000,
                  nmi_every=0, pc_hooks=None):
        """执行直到 PC 落在 stop_pcs 集合中。返回停止时的 PC。

        nmi_every: >0 时每 N 条指令触发一次 NMI（模拟 60Hz 帧中断，
                   解除 $E550 之类等待 $B4 bit7 的帧同步循环）。
        pc_hooks: {pc: callback()} — PC 命中时调用（用于抓 $E49E 走法执行等）。
        """
        if isinstance(stop_pcs, int):
            stop_pcs = {stop_pcs}
        cpu = self.cpu
        n = 0
        while n < max_instructions:
            if cpu.pc in stop_pcs:
                return cpu.pc
            if pc_hooks and cpu.pc in pc_hooks:
                pc_hooks[cpu.pc]()
            cpu.step()
            n += 1
            self.instr_count += 1
            if nmi_every and n % nmi_every == 0:
                cpu.nmi()
        raise TimeoutError(
            f"运行 {max_instructions} 条指令后仍未到达停止点 "
            f"(当前 PC=${cpu.pc:04X})")

    def call_subroutine(self, addr, a=None, x=None, y=None,
                        max_instructions=200_000_000, nmi_every=0):
        """以 JSR 语义调用 ROM 子程序，RTS 返回哨兵地址时停止。

        nmi_every: >0 时周期性触发 NMI（子程序内部有帧同步等待时需要）。
        """
        cpu = self.cpu
        if a is not None: cpu.a = a & 0xFF
        if x is not None: cpu.x = x & 0xFF
        if y is not None: cpu.y = y & 0xFF
        cpu.push16((SENTINEL - 1) & 0xFFFF)
        cpu.pc = addr
        self.run_until(SENTINEL, max_instructions, nmi_every=nmi_every)

    # ---------- 内存便捷访问 ----------
    def rd(self, addr):
        return self.bus.read(addr)

    def wr(self, addr, val):
        self.bus.write(addr, val)

    def dump(self, start, length):
        return bytes(self.bus.read(start + i) for i in range(length))

    def snapshot_ram(self):
        return bytes(self.bus.ram)

    def restore_ram(self, snap):
        self.bus.ram[:] = snap

    # ---------- 高层游戏接口 ----------
    def boot(self):
        """RESET → 跑 ROM 初始化到主循环入口 $D019，RAM 处于干净状态。"""
        self.cpu.reset()
        self.run_until(0xD019, max_instructions=5_000_000)

    def init_board(self):
        """调用 ROM 自身的摆棋子程序 $E0BC（写棋盘 $00-$83 + 棋子表 $94-$B3）。"""
        self.call_subroutine(0xE0BC)

    def new_game(self, side_to_move=0x10, book=False):
        """初始化一局对局的 AI 相关状态（跳过所有画面/声音流程）。

        side_to_move: $10=红方, $20=黑方（写入 $C7 的 side 位）
        book: True 则启用棋谱（$B6=$80, 指针=$8000），False 禁用
        """
        self.init_board()
        self.wr(0xC7, side_to_move)
        self.wr(0xBA, 0x02)                    # 棋谱使用标志（$D151: LDA #$02 STA $BA）
        self.wr(0xB5, 0x00)
        self.wr(0xB6, 0x80 if book else 0x00)  # 棋谱指针高字节, bit7=激活
        self.wr(0xB9, 0x00)
        self.bus.write(0x0388, 0)              # 回合数
        # 清空搜索工作区 $0400-$07FF
        for a in range(0x0400, 0x0800):
            self.bus.ram[a] = 0
        # 完整性校验字节: $8597 开头检查 $0436^$0454^$D015^$D017 == 0
        # ($D015=$55, $D017=$68 为 ROM 常量; 标题画面流程会设置这两个 RAM
        #  字节。校验失败 → 不搜索直接返回候选[0]，疑似防盗版自灭机制)
        self.wr(0x0436, self.rd(0xD015) ^ self.rd(0xD017))
        self.wr(0x0454, 0x00)

    def get_ai_move(self, depth):
        """调用 $8597 搜索，返回 (from_pos, to_pos)；无走法时返回 None。"""
        self.call_subroutine(0x8597, a=depth)
        frm = self.rd(0xC0)
        to = self.rd(0xC1)
        if frm >= 0x84:  # $FF = 无走法
            return None
        return frm, to

    def exec_move(self, frm, to):
        """调用 ROM 的走法执行 $E49E。返回 True=成功（carry 清零）。

        注: $E49E 内部调用画面/计时子程序，其中有等待 NMI 置位的
        帧同步循环，故周期性触发 NMI。
        """
        self.wr(0xC0, frm)
        self.wr(0xC1, to)
        self.call_subroutine(0xE49E, nmi_every=5000)
        from pyqiwang._mos6502 import FLAG_C
        return not self.cpu.get_flag(FLAG_C)

    def read_board(self):
        """读出零页棋盘数组 $00-$83。"""
        return bytes(self.bus.ram[0:0x84])

    def read_pieces(self):
        """读出双方棋子位置表: (red[16], black[16])。"""
        return (list(self.bus.ram[0x94:0xA4]), list(self.bus.ram[0xA4:0xB4]))

    # ---------- 反汇编（调试/探索用） ----------
    def disasm(self, addr, count=32):
        lines = []
        pc = addr
        for _ in range(count):
            line, size = disasm_one(self.bus, pc)
            lines.append(line)
            pc = (pc + size) & 0xFFFF
        return '\n'.join(lines)


# ============================================================
# 6502 反汇编器（探索 ROM 用）
# ============================================================
_MODES = {
    'imp': 1, 'acc': 1, 'imm': 2, 'zp': 2, 'zpx': 2, 'zpy': 2,
    'abs': 3, 'abx': 3, 'aby': 3, 'ind': 3, 'izx': 2, 'izy': 2, 'rel': 2,
}

_OPTABLE = {}
def _op(code, name, mode):
    _OPTABLE[code] = (name, mode)

for c, n, m in [
    (0xA9,'LDA','imm'),(0xA5,'LDA','zp'),(0xB5,'LDA','zpx'),(0xAD,'LDA','abs'),
    (0xBD,'LDA','abx'),(0xB9,'LDA','aby'),(0xA1,'LDA','izx'),(0xB1,'LDA','izy'),
    (0xA2,'LDX','imm'),(0xA6,'LDX','zp'),(0xB6,'LDX','zpy'),(0xAE,'LDX','abs'),(0xBE,'LDX','aby'),
    (0xA0,'LDY','imm'),(0xA4,'LDY','zp'),(0xB4,'LDY','zpx'),(0xAC,'LDY','abs'),(0xBC,'LDY','abx'),
    (0x85,'STA','zp'),(0x95,'STA','zpx'),(0x8D,'STA','abs'),(0x9D,'STA','abx'),
    (0x99,'STA','aby'),(0x81,'STA','izx'),(0x91,'STA','izy'),
    (0x86,'STX','zp'),(0x96,'STX','zpy'),(0x8E,'STX','abs'),
    (0x84,'STY','zp'),(0x94,'STY','zpx'),(0x8C,'STY','abs'),
    (0xAA,'TAX','imp'),(0xA8,'TAY','imp'),(0x8A,'TXA','imp'),(0x98,'TYA','imp'),
    (0xBA,'TSX','imp'),(0x9A,'TXS','imp'),
    (0x48,'PHA','imp'),(0x68,'PLA','imp'),(0x08,'PHP','imp'),(0x28,'PLP','imp'),
    (0x69,'ADC','imm'),(0x65,'ADC','zp'),(0x75,'ADC','zpx'),(0x6D,'ADC','abs'),
    (0x7D,'ADC','abx'),(0x79,'ADC','aby'),(0x61,'ADC','izx'),(0x71,'ADC','izy'),
    (0xE9,'SBC','imm'),(0xE5,'SBC','zp'),(0xF5,'SBC','zpx'),(0xED,'SBC','abs'),
    (0xFD,'SBC','abx'),(0xF9,'SBC','aby'),(0xE1,'SBC','izx'),(0xF1,'SBC','izy'),
    (0x29,'AND','imm'),(0x25,'AND','zp'),(0x35,'AND','zpx'),(0x2D,'AND','abs'),
    (0x3D,'AND','abx'),(0x39,'AND','aby'),(0x21,'AND','izx'),(0x31,'AND','izy'),
    (0x09,'ORA','imm'),(0x05,'ORA','zp'),(0x15,'ORA','zpx'),(0x0D,'ORA','abs'),
    (0x1D,'ORA','abx'),(0x19,'ORA','aby'),(0x01,'ORA','izx'),(0x11,'ORA','izy'),
    (0x49,'EOR','imm'),(0x45,'EOR','zp'),(0x55,'EOR','zpx'),(0x4D,'EOR','abs'),
    (0x5D,'EOR','abx'),(0x59,'EOR','aby'),(0x41,'EOR','izx'),(0x51,'EOR','izy'),
    (0xC9,'CMP','imm'),(0xC5,'CMP','zp'),(0xD5,'CMP','zpx'),(0xCD,'CMP','abs'),
    (0xDD,'CMP','abx'),(0xD9,'CMP','aby'),(0xC1,'CMP','izx'),(0xD1,'CMP','izy'),
    (0xE0,'CPX','imm'),(0xE4,'CPX','zp'),(0xEC,'CPX','abs'),
    (0xC0,'CPY','imm'),(0xC4,'CPY','zp'),(0xCC,'CPY','abs'),
    (0x24,'BIT','zp'),(0x2C,'BIT','abs'),
    (0xE6,'INC','zp'),(0xF6,'INC','zpx'),(0xEE,'INC','abs'),(0xFE,'INC','abx'),
    (0xC6,'DEC','zp'),(0xD6,'DEC','zpx'),(0xCE,'DEC','abs'),(0xDE,'DEC','abx'),
    (0xE8,'INX','imp'),(0xC8,'INY','imp'),(0xCA,'DEX','imp'),(0x88,'DEY','imp'),
    (0x0A,'ASL','acc'),(0x06,'ASL','zp'),(0x16,'ASL','zpx'),(0x0E,'ASL','abs'),(0x1E,'ASL','abx'),
    (0x4A,'LSR','acc'),(0x46,'LSR','zp'),(0x56,'LSR','zpx'),(0x4E,'LSR','abs'),(0x5E,'LSR','abx'),
    (0x2A,'ROL','acc'),(0x26,'ROL','zp'),(0x36,'ROL','zpx'),(0x2E,'ROL','abs'),(0x3E,'ROL','abx'),
    (0x6A,'ROR','acc'),(0x66,'ROR','zp'),(0x76,'ROR','zpx'),(0x6E,'ROR','abs'),(0x7E,'ROR','abx'),
    (0x4C,'JMP','abs'),(0x6C,'JMP','ind'),(0x20,'JSR','abs'),
    (0x60,'RTS','imp'),(0x40,'RTI','imp'),(0x00,'BRK','imp'),
    (0x10,'BPL','rel'),(0x30,'BMI','rel'),(0x50,'BVC','rel'),(0x70,'BVS','rel'),
    (0x90,'BCC','rel'),(0xB0,'BCS','rel'),(0xD0,'BNE','rel'),(0xF0,'BEQ','rel'),
    (0x18,'CLC','imp'),(0x38,'SEC','imp'),(0x58,'CLI','imp'),(0x78,'SEI','imp'),
    (0xB8,'CLV','imp'),(0xD8,'CLD','imp'),(0xF8,'SED','imp'),(0xEA,'NOP','imp'),
]:
    _op(c, n, m)


def disasm_one(bus, pc):
    """反汇编一条指令，返回 (文本, 长度)。"""
    op = bus.read(pc)
    if op not in _OPTABLE:
        return f"${pc:04X}: .byte ${op:02X}", 1
    name, mode = _OPTABLE[op]
    size = _MODES[mode]
    b = [bus.read(pc + i) for i in range(size)]
    hexs = ' '.join(f'{x:02X}' for x in b).ljust(9)
    if mode == 'imp':   arg = ''
    elif mode == 'acc': arg = 'A'
    elif mode == 'imm': arg = f'#${b[1]:02X}'
    elif mode == 'zp':  arg = f'${b[1]:02X}'
    elif mode == 'zpx': arg = f'${b[1]:02X},X'
    elif mode == 'zpy': arg = f'${b[1]:02X},Y'
    elif mode == 'abs': arg = f'${b[2]:02X}{b[1]:02X}'
    elif mode == 'abx': arg = f'${b[2]:02X}{b[1]:02X},X'
    elif mode == 'aby': arg = f'${b[2]:02X}{b[1]:02X},Y'
    elif mode == 'ind': arg = f'(${b[2]:02X}{b[1]:02X})'
    elif mode == 'izx': arg = f'(${b[1]:02X},X)'
    elif mode == 'izy': arg = f'(${b[1]:02X}),Y'
    elif mode == 'rel':
        off = b[1] - 0x100 if b[1] & 0x80 else b[1]
        arg = f'${(pc + 2 + off) & 0xFFFF:04X}'
    return f"${pc:04X}: {hexs} {name} {arg}".rstrip(), size


if __name__ == '__main__':
    h = RomHarness()
    print("RESET 向量:", hex(h.bus.prg[1 * 0x8000 + 0x7FFC] |
                           (h.bus.prg[1 * 0x8000 + 0x7FFD] << 8)))
    print("\n$FF2C (bank 切换子程序):")
    print(h.disasm(0xFF2C, 16))
