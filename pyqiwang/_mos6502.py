"""
mos6502.py — 纯 Python 6502 CPU 解释器
为《棋王》ROM 算法复原项目提供 ground truth 仿真。

特性:
- 151 条官方指令全实现（周期数近似即可，本项目不需要精确时序）
- 64KB 总线，读/写钩子（watchpoint 用于追踪 $0370 棋谱编码写入）
- 未知 opcode 抛异常（ROM 是正规编译代码，不应出现非法指令）
"""

# 状态标志位
FLAG_C = 0x01  # Carry
FLAG_Z = 0x02  # Zero
FLAG_I = 0x04  # Interrupt disable
FLAG_D = 0x08  # Decimal (NES 上无效，但标志位仍可设置)
FLAG_B = 0x10  # Break
FLAG_U = 0x20  # Unused (总是1)
FLAG_V = 0x40  # Overflow
FLAG_N = 0x80  # Negative


class CPUError(Exception):
    pass


class MOS6502:
    def __init__(self, bus):
        """bus 需实现 read(addr)->int 和 write(addr, value)。"""
        self.bus = bus
        self.a = 0
        self.x = 0
        self.y = 0
        self.sp = 0xFD
        self.pc = 0
        self.p = FLAG_U | FLAG_I
        self.cycles = 0
        self.halted = False

    # ---------- 总线访问 ----------
    def read(self, addr):
        return self.bus.read(addr & 0xFFFF)

    def write(self, addr, val):
        self.bus.write(addr & 0xFFFF, val & 0xFF)

    def read16(self, addr):
        return self.read(addr) | (self.read(addr + 1) << 8)

    def read16_bug(self, addr):
        """JMP ($xxFF) 页边界 bug。"""
        lo = self.read(addr)
        hi_addr = (addr & 0xFF00) | ((addr + 1) & 0x00FF)
        return lo | (self.read(hi_addr) << 8)

    # ---------- 栈 ----------
    def push(self, val):
        self.write(0x0100 + self.sp, val)
        self.sp = (self.sp - 1) & 0xFF

    def pop(self):
        self.sp = (self.sp + 1) & 0xFF
        return self.read(0x0100 + self.sp)

    def push16(self, val):
        self.push((val >> 8) & 0xFF)
        self.push(val & 0xFF)

    def pop16(self):
        lo = self.pop()
        hi = self.pop()
        return lo | (hi << 8)

    # ---------- 标志位 ----------
    def set_flag(self, flag, cond):
        if cond:
            self.p |= flag
        else:
            self.p &= ~flag & 0xFF

    def get_flag(self, flag):
        return (self.p & flag) != 0

    def set_zn(self, val):
        self.set_flag(FLAG_Z, val == 0)
        self.set_flag(FLAG_N, val & 0x80)

    # ---------- 复位/中断 ----------
    def reset(self):
        self.pc = self.read16(0xFFFC)
        self.sp = 0xFD
        self.p = FLAG_U | FLAG_I
        self.a = self.x = self.y = 0
        self.halted = False

    def nmi(self):
        self.push16(self.pc)
        self.push((self.p & ~FLAG_B) | FLAG_U)
        self.set_flag(FLAG_I, True)
        self.pc = self.read16(0xFFFA)

    def irq(self):
        if not self.get_flag(FLAG_I):
            self.push16(self.pc)
            self.push((self.p & ~FLAG_B) | FLAG_U)
            self.set_flag(FLAG_I, True)
            self.pc = self.read16(0xFFFE)

    # ---------- 寻址模式（返回操作数地址；acc/imp 特殊） ----------
    def _imm(self):
        addr = self.pc
        self.pc += 1
        return addr

    def _zp(self):
        addr = self.read(self.pc)
        self.pc += 1
        return addr

    def _zpx(self):
        addr = (self.read(self.pc) + self.x) & 0xFF
        self.pc += 1
        return addr

    def _zpy(self):
        addr = (self.read(self.pc) + self.y) & 0xFF
        self.pc += 1
        return addr

    def _abs(self):
        addr = self.read16(self.pc)
        self.pc += 2
        return addr

    def _abx(self):
        addr = (self.read16(self.pc) + self.x) & 0xFFFF
        self.pc += 2
        return addr

    def _aby(self):
        addr = (self.read16(self.pc) + self.y) & 0xFFFF
        self.pc += 2
        return addr

    def _ind(self):
        ptr = self.read16(self.pc)
        self.pc += 2
        return self.read16_bug(ptr)

    def _izx(self):
        zp = (self.read(self.pc) + self.x) & 0xFF
        self.pc += 1
        return self.read(zp) | (self.read((zp + 1) & 0xFF) << 8)

    def _izy(self):
        zp = self.read(self.pc)
        self.pc += 1
        base = self.read(zp) | (self.read((zp + 1) & 0xFF) << 8)
        return (base + self.y) & 0xFFFF

    def _rel(self):
        off = self.read(self.pc)
        self.pc += 1
        if off & 0x80:
            off -= 0x100
        return (self.pc + off) & 0xFFFF

    # ---------- ALU 操作 ----------
    def _adc(self, val):
        c = 1 if self.get_flag(FLAG_C) else 0
        r = self.a + val + c
        self.set_flag(FLAG_C, r > 0xFF)
        self.set_flag(FLAG_V, (~(self.a ^ val) & (self.a ^ r)) & 0x80)
        self.a = r & 0xFF
        self.set_zn(self.a)

    def _sbc(self, val):
        self._adc(val ^ 0xFF)

    def _cmp_op(self, reg, val):
        r = (reg - val) & 0xFF
        self.set_flag(FLAG_C, reg >= val)
        self.set_zn(r)

    def _asl_val(self, val):
        self.set_flag(FLAG_C, val & 0x80)
        r = (val << 1) & 0xFF
        self.set_zn(r)
        return r

    def _lsr_val(self, val):
        self.set_flag(FLAG_C, val & 0x01)
        r = val >> 1
        self.set_zn(r)
        return r

    def _rol_val(self, val):
        c = 1 if self.get_flag(FLAG_C) else 0
        self.set_flag(FLAG_C, val & 0x80)
        r = ((val << 1) | c) & 0xFF
        self.set_zn(r)
        return r

    def _ror_val(self, val):
        c = 0x80 if self.get_flag(FLAG_C) else 0
        self.set_flag(FLAG_C, val & 0x01)
        r = (val >> 1) | c
        self.set_zn(r)
        return r

    def _branch(self, cond, target):
        if cond:
            self.pc = target
            self.cycles += 1

    # ---------- 主执行 ----------
    def step(self):
        """执行一条指令，返回消耗周期（近似）。"""
        op = self.read(self.pc)
        self.pc = (self.pc + 1) & 0xFFFF
        self.cycles += 2  # 基础周期（近似值，本项目不依赖精确时序）

        # === 按 opcode 分派 ===
        # LDA
        if op == 0xA9: self.a = self.read(self._imm()); self.set_zn(self.a)
        elif op == 0xA5: self.a = self.read(self._zp()); self.set_zn(self.a)
        elif op == 0xB5: self.a = self.read(self._zpx()); self.set_zn(self.a)
        elif op == 0xAD: self.a = self.read(self._abs()); self.set_zn(self.a)
        elif op == 0xBD: self.a = self.read(self._abx()); self.set_zn(self.a)
        elif op == 0xB9: self.a = self.read(self._aby()); self.set_zn(self.a)
        elif op == 0xA1: self.a = self.read(self._izx()); self.set_zn(self.a)
        elif op == 0xB1: self.a = self.read(self._izy()); self.set_zn(self.a)
        # LDX
        elif op == 0xA2: self.x = self.read(self._imm()); self.set_zn(self.x)
        elif op == 0xA6: self.x = self.read(self._zp()); self.set_zn(self.x)
        elif op == 0xB6: self.x = self.read(self._zpy()); self.set_zn(self.x)
        elif op == 0xAE: self.x = self.read(self._abs()); self.set_zn(self.x)
        elif op == 0xBE: self.x = self.read(self._aby()); self.set_zn(self.x)
        # LDY
        elif op == 0xA0: self.y = self.read(self._imm()); self.set_zn(self.y)
        elif op == 0xA4: self.y = self.read(self._zp()); self.set_zn(self.y)
        elif op == 0xB4: self.y = self.read(self._zpx()); self.set_zn(self.y)
        elif op == 0xAC: self.y = self.read(self._abs()); self.set_zn(self.y)
        elif op == 0xBC: self.y = self.read(self._abx()); self.set_zn(self.y)
        # STA
        elif op == 0x85: self.write(self._zp(), self.a)
        elif op == 0x95: self.write(self._zpx(), self.a)
        elif op == 0x8D: self.write(self._abs(), self.a)
        elif op == 0x9D: self.write(self._abx(), self.a)
        elif op == 0x99: self.write(self._aby(), self.a)
        elif op == 0x81: self.write(self._izx(), self.a)
        elif op == 0x91: self.write(self._izy(), self.a)
        # STX
        elif op == 0x86: self.write(self._zp(), self.x)
        elif op == 0x96: self.write(self._zpy(), self.x)
        elif op == 0x8E: self.write(self._abs(), self.x)
        # STY
        elif op == 0x84: self.write(self._zp(), self.y)
        elif op == 0x94: self.write(self._zpx(), self.y)
        elif op == 0x8C: self.write(self._abs(), self.y)
        # 寄存器传送
        elif op == 0xAA: self.x = self.a; self.set_zn(self.x)              # TAX
        elif op == 0xA8: self.y = self.a; self.set_zn(self.y)              # TAY
        elif op == 0x8A: self.a = self.x; self.set_zn(self.a)              # TXA
        elif op == 0x98: self.a = self.y; self.set_zn(self.a)              # TYA
        elif op == 0xBA: self.x = self.sp; self.set_zn(self.x)             # TSX
        elif op == 0x9A: self.sp = self.x                                   # TXS
        # 栈
        elif op == 0x48: self.push(self.a)                                  # PHA
        elif op == 0x68: self.a = self.pop(); self.set_zn(self.a)          # PLA
        elif op == 0x08: self.push(self.p | FLAG_B | FLAG_U)               # PHP
        elif op == 0x28: self.p = (self.pop() | FLAG_U) & ~FLAG_B          # PLP
        # ADC
        elif op == 0x69: self._adc(self.read(self._imm()))
        elif op == 0x65: self._adc(self.read(self._zp()))
        elif op == 0x75: self._adc(self.read(self._zpx()))
        elif op == 0x6D: self._adc(self.read(self._abs()))
        elif op == 0x7D: self._adc(self.read(self._abx()))
        elif op == 0x79: self._adc(self.read(self._aby()))
        elif op == 0x61: self._adc(self.read(self._izx()))
        elif op == 0x71: self._adc(self.read(self._izy()))
        # SBC
        elif op == 0xE9: self._sbc(self.read(self._imm()))
        elif op == 0xE5: self._sbc(self.read(self._zp()))
        elif op == 0xF5: self._sbc(self.read(self._zpx()))
        elif op == 0xED: self._sbc(self.read(self._abs()))
        elif op == 0xFD: self._sbc(self.read(self._abx()))
        elif op == 0xF9: self._sbc(self.read(self._aby()))
        elif op == 0xE1: self._sbc(self.read(self._izx()))
        elif op == 0xF1: self._sbc(self.read(self._izy()))
        # AND
        elif op == 0x29: self.a &= self.read(self._imm()); self.set_zn(self.a)
        elif op == 0x25: self.a &= self.read(self._zp()); self.set_zn(self.a)
        elif op == 0x35: self.a &= self.read(self._zpx()); self.set_zn(self.a)
        elif op == 0x2D: self.a &= self.read(self._abs()); self.set_zn(self.a)
        elif op == 0x3D: self.a &= self.read(self._abx()); self.set_zn(self.a)
        elif op == 0x39: self.a &= self.read(self._aby()); self.set_zn(self.a)
        elif op == 0x21: self.a &= self.read(self._izx()); self.set_zn(self.a)
        elif op == 0x31: self.a &= self.read(self._izy()); self.set_zn(self.a)
        # ORA
        elif op == 0x09: self.a |= self.read(self._imm()); self.set_zn(self.a)
        elif op == 0x05: self.a |= self.read(self._zp()); self.set_zn(self.a)
        elif op == 0x15: self.a |= self.read(self._zpx()); self.set_zn(self.a)
        elif op == 0x0D: self.a |= self.read(self._abs()); self.set_zn(self.a)
        elif op == 0x1D: self.a |= self.read(self._abx()); self.set_zn(self.a)
        elif op == 0x19: self.a |= self.read(self._aby()); self.set_zn(self.a)
        elif op == 0x01: self.a |= self.read(self._izx()); self.set_zn(self.a)
        elif op == 0x11: self.a |= self.read(self._izy()); self.set_zn(self.a)
        # EOR
        elif op == 0x49: self.a ^= self.read(self._imm()); self.set_zn(self.a)
        elif op == 0x45: self.a ^= self.read(self._zp()); self.set_zn(self.a)
        elif op == 0x55: self.a ^= self.read(self._zpx()); self.set_zn(self.a)
        elif op == 0x4D: self.a ^= self.read(self._abs()); self.set_zn(self.a)
        elif op == 0x5D: self.a ^= self.read(self._abx()); self.set_zn(self.a)
        elif op == 0x59: self.a ^= self.read(self._aby()); self.set_zn(self.a)
        elif op == 0x41: self.a ^= self.read(self._izx()); self.set_zn(self.a)
        elif op == 0x51: self.a ^= self.read(self._izy()); self.set_zn(self.a)
        # CMP
        elif op == 0xC9: self._cmp_op(self.a, self.read(self._imm()))
        elif op == 0xC5: self._cmp_op(self.a, self.read(self._zp()))
        elif op == 0xD5: self._cmp_op(self.a, self.read(self._zpx()))
        elif op == 0xCD: self._cmp_op(self.a, self.read(self._abs()))
        elif op == 0xDD: self._cmp_op(self.a, self.read(self._abx()))
        elif op == 0xD9: self._cmp_op(self.a, self.read(self._aby()))
        elif op == 0xC1: self._cmp_op(self.a, self.read(self._izx()))
        elif op == 0xD1: self._cmp_op(self.a, self.read(self._izy()))
        # CPX / CPY
        elif op == 0xE0: self._cmp_op(self.x, self.read(self._imm()))
        elif op == 0xE4: self._cmp_op(self.x, self.read(self._zp()))
        elif op == 0xEC: self._cmp_op(self.x, self.read(self._abs()))
        elif op == 0xC0: self._cmp_op(self.y, self.read(self._imm()))
        elif op == 0xC4: self._cmp_op(self.y, self.read(self._zp()))
        elif op == 0xCC: self._cmp_op(self.y, self.read(self._abs()))
        # BIT
        elif op == 0x24:
            v = self.read(self._zp())
            self.set_flag(FLAG_Z, (self.a & v) == 0)
            self.set_flag(FLAG_N, v & 0x80)
            self.set_flag(FLAG_V, v & 0x40)
        elif op == 0x2C:
            v = self.read(self._abs())
            self.set_flag(FLAG_Z, (self.a & v) == 0)
            self.set_flag(FLAG_N, v & 0x80)
            self.set_flag(FLAG_V, v & 0x40)
        # INC / DEC (内存)
        elif op == 0xE6: a = self._zp(); v = (self.read(a) + 1) & 0xFF; self.write(a, v); self.set_zn(v)
        elif op == 0xF6: a = self._zpx(); v = (self.read(a) + 1) & 0xFF; self.write(a, v); self.set_zn(v)
        elif op == 0xEE: a = self._abs(); v = (self.read(a) + 1) & 0xFF; self.write(a, v); self.set_zn(v)
        elif op == 0xFE: a = self._abx(); v = (self.read(a) + 1) & 0xFF; self.write(a, v); self.set_zn(v)
        elif op == 0xC6: a = self._zp(); v = (self.read(a) - 1) & 0xFF; self.write(a, v); self.set_zn(v)
        elif op == 0xD6: a = self._zpx(); v = (self.read(a) - 1) & 0xFF; self.write(a, v); self.set_zn(v)
        elif op == 0xCE: a = self._abs(); v = (self.read(a) - 1) & 0xFF; self.write(a, v); self.set_zn(v)
        elif op == 0xDE: a = self._abx(); v = (self.read(a) - 1) & 0xFF; self.write(a, v); self.set_zn(v)
        # INX/INY/DEX/DEY
        elif op == 0xE8: self.x = (self.x + 1) & 0xFF; self.set_zn(self.x)
        elif op == 0xC8: self.y = (self.y + 1) & 0xFF; self.set_zn(self.y)
        elif op == 0xCA: self.x = (self.x - 1) & 0xFF; self.set_zn(self.x)
        elif op == 0x88: self.y = (self.y - 1) & 0xFF; self.set_zn(self.y)
        # 移位 (累加器)
        elif op == 0x0A: self.a = self._asl_val(self.a)
        elif op == 0x4A: self.a = self._lsr_val(self.a)
        elif op == 0x2A: self.a = self._rol_val(self.a)
        elif op == 0x6A: self.a = self._ror_val(self.a)
        # 移位 (内存)
        elif op == 0x06: a = self._zp(); self.write(a, self._asl_val(self.read(a)))
        elif op == 0x16: a = self._zpx(); self.write(a, self._asl_val(self.read(a)))
        elif op == 0x0E: a = self._abs(); self.write(a, self._asl_val(self.read(a)))
        elif op == 0x1E: a = self._abx(); self.write(a, self._asl_val(self.read(a)))
        elif op == 0x46: a = self._zp(); self.write(a, self._lsr_val(self.read(a)))
        elif op == 0x56: a = self._zpx(); self.write(a, self._lsr_val(self.read(a)))
        elif op == 0x4E: a = self._abs(); self.write(a, self._lsr_val(self.read(a)))
        elif op == 0x5E: a = self._abx(); self.write(a, self._lsr_val(self.read(a)))
        elif op == 0x26: a = self._zp(); self.write(a, self._rol_val(self.read(a)))
        elif op == 0x36: a = self._zpx(); self.write(a, self._rol_val(self.read(a)))
        elif op == 0x2E: a = self._abs(); self.write(a, self._rol_val(self.read(a)))
        elif op == 0x3E: a = self._abx(); self.write(a, self._rol_val(self.read(a)))
        elif op == 0x66: a = self._zp(); self.write(a, self._ror_val(self.read(a)))
        elif op == 0x76: a = self._zpx(); self.write(a, self._ror_val(self.read(a)))
        elif op == 0x6E: a = self._abs(); self.write(a, self._ror_val(self.read(a)))
        elif op == 0x7E: a = self._abx(); self.write(a, self._ror_val(self.read(a)))
        # 跳转
        elif op == 0x4C: self.pc = self._abs()                               # JMP abs
        elif op == 0x6C: self.pc = self._ind()                               # JMP (ind)
        elif op == 0x20:                                                      # JSR
            target = self._abs()
            self.push16((self.pc - 1) & 0xFFFF)
            self.pc = target
        elif op == 0x60: self.pc = (self.pop16() + 1) & 0xFFFF               # RTS
        elif op == 0x40:                                                      # RTI
            self.p = (self.pop() | FLAG_U) & ~FLAG_B
            self.pc = self.pop16()
        elif op == 0x00:                                                      # BRK
            self.pc = (self.pc + 1) & 0xFFFF
            self.push16(self.pc)
            self.push(self.p | FLAG_B | FLAG_U)
            self.set_flag(FLAG_I, True)
            self.pc = self.read16(0xFFFE)
        # 分支
        elif op == 0x10: t = self._rel(); self._branch(not self.get_flag(FLAG_N), t)  # BPL
        elif op == 0x30: t = self._rel(); self._branch(self.get_flag(FLAG_N), t)      # BMI
        elif op == 0x50: t = self._rel(); self._branch(not self.get_flag(FLAG_V), t)  # BVC
        elif op == 0x70: t = self._rel(); self._branch(self.get_flag(FLAG_V), t)      # BVS
        elif op == 0x90: t = self._rel(); self._branch(not self.get_flag(FLAG_C), t)  # BCC
        elif op == 0xB0: t = self._rel(); self._branch(self.get_flag(FLAG_C), t)      # BCS
        elif op == 0xD0: t = self._rel(); self._branch(not self.get_flag(FLAG_Z), t)  # BNE
        elif op == 0xF0: t = self._rel(); self._branch(self.get_flag(FLAG_Z), t)      # BEQ
        # 标志位操作
        elif op == 0x18: self.set_flag(FLAG_C, False)   # CLC
        elif op == 0x38: self.set_flag(FLAG_C, True)    # SEC
        elif op == 0x58: self.set_flag(FLAG_I, False)   # CLI
        elif op == 0x78: self.set_flag(FLAG_I, True)    # SEI
        elif op == 0xB8: self.set_flag(FLAG_V, False)   # CLV
        elif op == 0xD8: self.set_flag(FLAG_D, False)   # CLD
        elif op == 0xF8: self.set_flag(FLAG_D, True)    # SED
        # NOP
        elif op == 0xEA: pass
        else:
            raise CPUError(
                f"未实现的 opcode ${op:02X} @ PC=${(self.pc - 1) & 0xFFFF:04X}")

        return self.cycles
