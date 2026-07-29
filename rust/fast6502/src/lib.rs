use std::ptr;

const FLAG_C: u8 = 0x01;
const FLAG_Z: u8 = 0x02;
const FLAG_I: u8 = 0x04;
const FLAG_D: u8 = 0x08;
const FLAG_B: u8 = 0x10;
const FLAG_U: u8 = 0x20;
const FLAG_V: u8 = 0x40;
const FLAG_N: u8 = 0x80;

#[repr(C)]
pub struct Machine {
    prg: Box<[u8; 0x10000]>,
    ram: Box<[u8; 0x800]>,
    a: u8,
    x: u8,
    y: u8,
    sp: u8,
    pc: u16,
    p: u8,
    cycles: u64,
    prg_bank: u8,
    reg4100: u8,
    ppustatus_toggle: bool,
    open_bus: u8,
    pad1: u8,
    pad1_shift: u8,
    pad_strobe: u8,
}

impl Machine {
    fn new(prg: &[u8]) -> Option<Self> {
        if prg.len() != 0x10000 {
            return None;
        }
        let mut prg_data = Box::new([0; 0x10000]);
        prg_data.copy_from_slice(prg);
        Some(Self {
            prg: prg_data,
            ram: Box::new([0; 0x800]),
            a: 0,
            x: 0,
            y: 0,
            sp: 0xfd,
            pc: 0,
            p: FLAG_U | FLAG_I,
            cycles: 0,
            prg_bank: 1,
            reg4100: 0,
            ppustatus_toggle: false,
            open_bus: 0,
            pad1: 0,
            pad1_shift: 0,
            pad_strobe: 0,
        })
    }

    #[inline(always)]
    fn read(&mut self, addr: u16) -> u8 {
        let value = match addr {
            0x0000..=0x1fff => self.ram[(addr as usize) & 0x7ff],
            0x2000..=0x3fff => {
                if addr & 7 == 2 {
                    self.ppustatus_toggle = !self.ppustatus_toggle;
                    if self.ppustatus_toggle {
                        0x80
                    } else {
                        0
                    }
                } else {
                    0
                }
            }
            0x4016 => {
                if self.pad_strobe & 1 != 0 {
                    self.pad1 & 1
                } else {
                    let value = self.pad1_shift & 1;
                    self.pad1_shift = (self.pad1_shift >> 1) | 0x80;
                    value
                }
            }
            0x4000..=0x7fff => self.open_bus,
            _ => self.prg[self.prg_bank as usize * 0x8000 + addr as usize - 0x8000],
        };
        self.open_bus = value;
        value
    }

    #[inline(always)]
    fn write(&mut self, addr: u16, value: u8) {
        match addr {
            0x0000..=0x1fff => self.ram[(addr as usize) & 0x7ff] = value,
            0x4016 => {
                if self.pad_strobe & 1 != 0 && value & 1 == 0 {
                    self.pad1_shift = self.pad1;
                }
                self.pad_strobe = value;
            }
            0x4102 => {
                self.reg4100 = value;
                self.prg_bank = (value >> 2) & 1;
            }
            _ => {}
        }
    }

    #[inline(always)]
    fn read16(&mut self, addr: u16) -> u16 {
        let lo = self.read(addr) as u16;
        let hi = self.read(addr.wrapping_add(1)) as u16;
        lo | (hi << 8)
    }

    #[inline(always)]
    fn read16_bug(&mut self, addr: u16) -> u16 {
        let lo = self.read(addr) as u16;
        let hi_addr = (addr & 0xff00) | (addr.wrapping_add(1) & 0x00ff);
        lo | ((self.read(hi_addr) as u16) << 8)
    }

    #[inline(always)]
    fn push(&mut self, value: u8) {
        self.write(0x0100 + self.sp as u16, value);
        self.sp = self.sp.wrapping_sub(1);
    }

    #[inline(always)]
    fn pop(&mut self) -> u8 {
        self.sp = self.sp.wrapping_add(1);
        self.read(0x0100 + self.sp as u16)
    }

    #[inline(always)]
    fn push16(&mut self, value: u16) {
        self.push((value >> 8) as u8);
        self.push(value as u8);
    }

    #[inline(always)]
    fn pop16(&mut self) -> u16 {
        let lo = self.pop() as u16;
        let hi = self.pop() as u16;
        lo | (hi << 8)
    }

    #[inline(always)]
    fn set_flag(&mut self, flag: u8, condition: bool) {
        if condition {
            self.p |= flag;
        } else {
            self.p &= !flag;
        }
    }

    #[inline(always)]
    fn set_zn(&mut self, value: u8) {
        self.set_flag(FLAG_Z, value == 0);
        self.set_flag(FLAG_N, value & 0x80 != 0);
    }

    #[inline(always)]
    fn imm(&mut self) -> u16 {
        let addr = self.pc;
        self.pc = self.pc.wrapping_add(1);
        addr
    }

    #[inline(always)]
    fn zp(&mut self) -> u16 {
        let pc = self.pc;
        let addr = self.read(pc) as u16;
        self.pc = self.pc.wrapping_add(1);
        addr
    }

    #[inline(always)]
    fn zpx(&mut self) -> u16 {
        let pc = self.pc;
        let addr = self.read(pc).wrapping_add(self.x) as u16;
        self.pc = self.pc.wrapping_add(1);
        addr
    }

    #[inline(always)]
    fn zpy(&mut self) -> u16 {
        let pc = self.pc;
        let addr = self.read(pc).wrapping_add(self.y) as u16;
        self.pc = self.pc.wrapping_add(1);
        addr
    }

    #[inline(always)]
    fn abs(&mut self) -> u16 {
        let pc = self.pc;
        let addr = self.read16(pc);
        self.pc = self.pc.wrapping_add(2);
        addr
    }

    #[inline(always)]
    fn abx(&mut self) -> u16 {
        self.abs().wrapping_add(self.x as u16)
    }

    #[inline(always)]
    fn aby(&mut self) -> u16 {
        self.abs().wrapping_add(self.y as u16)
    }

    #[inline(always)]
    fn ind(&mut self) -> u16 {
        let pointer = self.abs();
        self.read16_bug(pointer)
    }

    #[inline(always)]
    fn izx(&mut self) -> u16 {
        let pc = self.pc;
        let pointer = self.read(pc).wrapping_add(self.x);
        self.pc = self.pc.wrapping_add(1);
        let lo = self.read(pointer as u16) as u16;
        let hi = self.read(pointer.wrapping_add(1) as u16) as u16;
        lo | (hi << 8)
    }

    #[inline(always)]
    fn izy(&mut self) -> u16 {
        let pc = self.pc;
        let pointer = self.read(pc);
        self.pc = self.pc.wrapping_add(1);
        let lo = self.read(pointer as u16) as u16;
        let hi = self.read(pointer.wrapping_add(1) as u16) as u16;
        (lo | (hi << 8)).wrapping_add(self.y as u16)
    }

    #[inline(always)]
    fn rel(&mut self) -> u16 {
        let pc = self.pc;
        let offset = self.read(pc) as i8;
        self.pc = self.pc.wrapping_add(1);
        self.pc.wrapping_add_signed(offset as i16)
    }

    #[inline(always)]
    fn adc(&mut self, value: u8) {
        let carry = if self.p & FLAG_C != 0 { 1 } else { 0 };
        let result = self.a as u16 + value as u16 + carry;
        self.set_flag(FLAG_C, result > 0xff);
        self.set_flag(
            FLAG_V,
            (!(self.a ^ value) & (self.a ^ result as u8) & 0x80) != 0,
        );
        self.a = result as u8;
        self.set_zn(self.a);
    }

    #[inline(always)]
    fn cmp(&mut self, register: u8, value: u8) {
        self.set_flag(FLAG_C, register >= value);
        self.set_zn(register.wrapping_sub(value));
    }

    #[inline(always)]
    fn asl(&mut self, value: u8) -> u8 {
        self.set_flag(FLAG_C, value & 0x80 != 0);
        let result = value.wrapping_shl(1);
        self.set_zn(result);
        result
    }

    #[inline(always)]
    fn lsr(&mut self, value: u8) -> u8 {
        self.set_flag(FLAG_C, value & 1 != 0);
        let result = value >> 1;
        self.set_zn(result);
        result
    }

    #[inline(always)]
    fn rol(&mut self, value: u8) -> u8 {
        let carry = if self.p & FLAG_C != 0 { 1 } else { 0 };
        self.set_flag(FLAG_C, value & 0x80 != 0);
        let result = value.wrapping_shl(1) | carry;
        self.set_zn(result);
        result
    }

    #[inline(always)]
    fn ror(&mut self, value: u8) -> u8 {
        let carry = if self.p & FLAG_C != 0 { 0x80 } else { 0 };
        self.set_flag(FLAG_C, value & 1 != 0);
        let result = (value >> 1) | carry;
        self.set_zn(result);
        result
    }

    #[inline(always)]
    fn reset(&mut self) {
        self.pc = self.read16(0xfffc);
        self.sp = 0xfd;
        self.p = FLAG_U | FLAG_I;
        self.a = 0;
        self.x = 0;
        self.y = 0;
    }

    #[inline(always)]
    fn nmi(&mut self) {
        self.push16(self.pc);
        self.push((self.p & !FLAG_B) | FLAG_U);
        self.p |= FLAG_I;
        self.pc = self.read16(0xfffa);
    }

    #[inline(always)]
    fn branch(&mut self, condition: bool, target: u16) {
        if condition {
            self.pc = target;
            self.cycles += 1;
        }
    }

    #[inline(always)]
    fn load_a(&mut self, addr: u16) {
        self.a = self.read(addr);
        self.set_zn(self.a);
    }
    #[inline(always)]
    fn load_x(&mut self, addr: u16) {
        self.x = self.read(addr);
        self.set_zn(self.x);
    }
    #[inline(always)]
    fn load_y(&mut self, addr: u16) {
        self.y = self.read(addr);
        self.set_zn(self.y);
    }

    #[inline(always)]
    fn step(&mut self) -> Result<(), u8> {
        let op_pc = self.pc;
        let op = self.read(self.pc);
        self.pc = self.pc.wrapping_add(1);
        self.cycles += 2;
        match op {
            0xa9 => {
                let a = self.imm();
                self.load_a(a);
            }
            0xa5 => {
                let a = self.zp();
                self.load_a(a);
            }
            0xb5 => {
                let a = self.zpx();
                self.load_a(a);
            }
            0xad => {
                let a = self.abs();
                self.load_a(a);
            }
            0xbd => {
                let a = self.abx();
                self.load_a(a);
            }
            0xb9 => {
                let a = self.aby();
                self.load_a(a);
            }
            0xa1 => {
                let a = self.izx();
                self.load_a(a);
            }
            0xb1 => {
                let a = self.izy();
                self.load_a(a);
            }
            0xa2 => {
                let a = self.imm();
                self.load_x(a);
            }
            0xa6 => {
                let a = self.zp();
                self.load_x(a);
            }
            0xb6 => {
                let a = self.zpy();
                self.load_x(a);
            }
            0xae => {
                let a = self.abs();
                self.load_x(a);
            }
            0xbe => {
                let a = self.aby();
                self.load_x(a);
            }
            0xa0 => {
                let a = self.imm();
                self.load_y(a);
            }
            0xa4 => {
                let a = self.zp();
                self.load_y(a);
            }
            0xb4 => {
                let a = self.zpx();
                self.load_y(a);
            }
            0xac => {
                let a = self.abs();
                self.load_y(a);
            }
            0xbc => {
                let a = self.abx();
                self.load_y(a);
            }
            0x85 => {
                let a = self.zp();
                self.write(a, self.a);
            }
            0x95 => {
                let a = self.zpx();
                self.write(a, self.a);
            }
            0x8d => {
                let a = self.abs();
                self.write(a, self.a);
            }
            0x9d => {
                let a = self.abx();
                self.write(a, self.a);
            }
            0x99 => {
                let a = self.aby();
                self.write(a, self.a);
            }
            0x81 => {
                let a = self.izx();
                self.write(a, self.a);
            }
            0x91 => {
                let a = self.izy();
                self.write(a, self.a);
            }
            0x86 => {
                let a = self.zp();
                self.write(a, self.x);
            }
            0x96 => {
                let a = self.zpy();
                self.write(a, self.x);
            }
            0x8e => {
                let a = self.abs();
                self.write(a, self.x);
            }
            0x84 => {
                let a = self.zp();
                self.write(a, self.y);
            }
            0x94 => {
                let a = self.zpx();
                self.write(a, self.y);
            }
            0x8c => {
                let a = self.abs();
                self.write(a, self.y);
            }
            0xaa => {
                self.x = self.a;
                self.set_zn(self.x);
            }
            0xa8 => {
                self.y = self.a;
                self.set_zn(self.y);
            }
            0x8a => {
                self.a = self.x;
                self.set_zn(self.a);
            }
            0x98 => {
                self.a = self.y;
                self.set_zn(self.a);
            }
            0xba => {
                self.x = self.sp;
                self.set_zn(self.x);
            }
            0x9a => self.sp = self.x,
            0x48 => self.push(self.a),
            0x68 => {
                self.a = self.pop();
                self.set_zn(self.a);
            }
            0x08 => self.push(self.p | FLAG_B | FLAG_U),
            0x28 => self.p = (self.pop() | FLAG_U) & !FLAG_B,
            0x69 | 0x65 | 0x75 | 0x6d | 0x7d | 0x79 | 0x61 | 0x71 => {
                let a = match op {
                    0x69 => self.imm(),
                    0x65 => self.zp(),
                    0x75 => self.zpx(),
                    0x6d => self.abs(),
                    0x7d => self.abx(),
                    0x79 => self.aby(),
                    0x61 => self.izx(),
                    _ => self.izy(),
                };
                let v = self.read(a);
                self.adc(v);
            }
            0xe9 | 0xe5 | 0xf5 | 0xed | 0xfd | 0xf9 | 0xe1 | 0xf1 => {
                let a = match op {
                    0xe9 => self.imm(),
                    0xe5 => self.zp(),
                    0xf5 => self.zpx(),
                    0xed => self.abs(),
                    0xfd => self.abx(),
                    0xf9 => self.aby(),
                    0xe1 => self.izx(),
                    _ => self.izy(),
                };
                let v = self.read(a) ^ 0xff;
                self.adc(v);
            }
            0x29 | 0x25 | 0x35 | 0x2d | 0x3d | 0x39 | 0x21 | 0x31 => {
                let a = match op {
                    0x29 => self.imm(),
                    0x25 => self.zp(),
                    0x35 => self.zpx(),
                    0x2d => self.abs(),
                    0x3d => self.abx(),
                    0x39 => self.aby(),
                    0x21 => self.izx(),
                    _ => self.izy(),
                };
                self.a &= self.read(a);
                self.set_zn(self.a);
            }
            0x09 | 0x05 | 0x15 | 0x0d | 0x1d | 0x19 | 0x01 | 0x11 => {
                let a = match op {
                    0x09 => self.imm(),
                    0x05 => self.zp(),
                    0x15 => self.zpx(),
                    0x0d => self.abs(),
                    0x1d => self.abx(),
                    0x19 => self.aby(),
                    0x01 => self.izx(),
                    _ => self.izy(),
                };
                self.a |= self.read(a);
                self.set_zn(self.a);
            }
            0x49 | 0x45 | 0x55 | 0x4d | 0x5d | 0x59 | 0x41 | 0x51 => {
                let a = match op {
                    0x49 => self.imm(),
                    0x45 => self.zp(),
                    0x55 => self.zpx(),
                    0x4d => self.abs(),
                    0x5d => self.abx(),
                    0x59 => self.aby(),
                    0x41 => self.izx(),
                    _ => self.izy(),
                };
                self.a ^= self.read(a);
                self.set_zn(self.a);
            }
            0xc9 | 0xc5 | 0xd5 | 0xcd | 0xdd | 0xd9 | 0xc1 | 0xd1 => {
                let a = match op {
                    0xc9 => self.imm(),
                    0xc5 => self.zp(),
                    0xd5 => self.zpx(),
                    0xcd => self.abs(),
                    0xdd => self.abx(),
                    0xd9 => self.aby(),
                    0xc1 => self.izx(),
                    _ => self.izy(),
                };
                let v = self.read(a);
                self.cmp(self.a, v);
            }
            0xe0 | 0xe4 | 0xec => {
                let a = match op {
                    0xe0 => self.imm(),
                    0xe4 => self.zp(),
                    _ => self.abs(),
                };
                let v = self.read(a);
                self.cmp(self.x, v);
            }
            0xc0 | 0xc4 | 0xcc => {
                let a = match op {
                    0xc0 => self.imm(),
                    0xc4 => self.zp(),
                    _ => self.abs(),
                };
                let v = self.read(a);
                self.cmp(self.y, v);
            }
            0x24 | 0x2c => {
                let a = if op == 0x24 { self.zp() } else { self.abs() };
                let v = self.read(a);
                self.set_flag(FLAG_Z, self.a & v == 0);
                self.set_flag(FLAG_N, v & 0x80 != 0);
                self.set_flag(FLAG_V, v & 0x40 != 0);
            }
            0xe6 | 0xf6 | 0xee | 0xfe => {
                let a = match op {
                    0xe6 => self.zp(),
                    0xf6 => self.zpx(),
                    0xee => self.abs(),
                    _ => self.abx(),
                };
                let v = self.read(a).wrapping_add(1);
                self.write(a, v);
                self.set_zn(v);
            }
            0xc6 | 0xd6 | 0xce | 0xde => {
                let a = match op {
                    0xc6 => self.zp(),
                    0xd6 => self.zpx(),
                    0xce => self.abs(),
                    _ => self.abx(),
                };
                let v = self.read(a).wrapping_sub(1);
                self.write(a, v);
                self.set_zn(v);
            }
            0xe8 => {
                self.x = self.x.wrapping_add(1);
                self.set_zn(self.x);
            }
            0xc8 => {
                self.y = self.y.wrapping_add(1);
                self.set_zn(self.y);
            }
            0xca => {
                self.x = self.x.wrapping_sub(1);
                self.set_zn(self.x);
            }
            0x88 => {
                self.y = self.y.wrapping_sub(1);
                self.set_zn(self.y);
            }
            0x0a => self.a = self.asl(self.a),
            0x4a => self.a = self.lsr(self.a),
            0x2a => self.a = self.rol(self.a),
            0x6a => self.a = self.ror(self.a),
            0x06 | 0x16 | 0x0e | 0x1e => {
                let a = match op {
                    0x06 => self.zp(),
                    0x16 => self.zpx(),
                    0x0e => self.abs(),
                    _ => self.abx(),
                };
                let old = self.read(a);
                let v = self.asl(old);
                self.write(a, v);
            }
            0x46 | 0x56 | 0x4e | 0x5e => {
                let a = match op {
                    0x46 => self.zp(),
                    0x56 => self.zpx(),
                    0x4e => self.abs(),
                    _ => self.abx(),
                };
                let old = self.read(a);
                let v = self.lsr(old);
                self.write(a, v);
            }
            0x26 | 0x36 | 0x2e | 0x3e => {
                let a = match op {
                    0x26 => self.zp(),
                    0x36 => self.zpx(),
                    0x2e => self.abs(),
                    _ => self.abx(),
                };
                let old = self.read(a);
                let v = self.rol(old);
                self.write(a, v);
            }
            0x66 | 0x76 | 0x6e | 0x7e => {
                let a = match op {
                    0x66 => self.zp(),
                    0x76 => self.zpx(),
                    0x6e => self.abs(),
                    _ => self.abx(),
                };
                let old = self.read(a);
                let v = self.ror(old);
                self.write(a, v);
            }
            0x4c => self.pc = self.abs(),
            0x6c => self.pc = self.ind(),
            0x20 => {
                let target = self.abs();
                self.push16(self.pc.wrapping_sub(1));
                self.pc = target;
            }
            0x60 => self.pc = self.pop16().wrapping_add(1),
            0x40 => {
                self.p = (self.pop() | FLAG_U) & !FLAG_B;
                self.pc = self.pop16();
            }
            0x00 => {
                self.pc = self.pc.wrapping_add(1);
                self.push16(self.pc);
                self.push(self.p | FLAG_B | FLAG_U);
                self.p |= FLAG_I;
                self.pc = self.read16(0xfffe);
            }
            0x10 | 0x30 | 0x50 | 0x70 | 0x90 | 0xb0 | 0xd0 | 0xf0 => {
                let t = self.rel();
                let condition = match op {
                    0x10 => self.p & FLAG_N == 0,
                    0x30 => self.p & FLAG_N != 0,
                    0x50 => self.p & FLAG_V == 0,
                    0x70 => self.p & FLAG_V != 0,
                    0x90 => self.p & FLAG_C == 0,
                    0xb0 => self.p & FLAG_C != 0,
                    0xd0 => self.p & FLAG_Z == 0,
                    _ => self.p & FLAG_Z != 0,
                };
                self.branch(condition, t);
            }
            0x18 => self.p &= !FLAG_C,
            0x38 => self.p |= FLAG_C,
            0x58 => self.p &= !FLAG_I,
            0x78 => self.p |= FLAG_I,
            0xb8 => self.p &= !FLAG_V,
            0xd8 => self.p &= !FLAG_D,
            0xf8 => self.p |= FLAG_D,
            0xea => {}
            _ => {
                self.pc = op_pc;
                return Err(op);
            }
        }
        Ok(())
    }
}

#[no_mangle]
pub unsafe extern "C" fn qiwang_machine_new(prg: *const u8, len: usize) -> *mut Machine {
    if prg.is_null() {
        return ptr::null_mut();
    }
    let bytes = std::slice::from_raw_parts(prg, len);
    Machine::new(bytes).map_or(ptr::null_mut(), |machine| Box::into_raw(Box::new(machine)))
}

#[no_mangle]
pub unsafe extern "C" fn qiwang_machine_free(machine: *mut Machine) {
    if !machine.is_null() {
        drop(Box::from_raw(machine));
    }
}

#[no_mangle]
pub unsafe extern "C" fn qiwang_machine_reset(machine: *mut Machine) -> i32 {
    let Some(machine) = machine.as_mut() else {
        return -1;
    };
    machine.reset();
    0
}

#[no_mangle]
pub unsafe extern "C" fn qiwang_machine_nmi(machine: *mut Machine) -> i32 {
    let Some(machine) = machine.as_mut() else {
        return -1;
    };
    machine.nmi();
    0
}

#[no_mangle]
pub unsafe extern "C" fn qiwang_machine_step(machine: *mut Machine) -> i32 {
    let Some(machine) = machine.as_mut() else {
        return -1;
    };
    match machine.step() {
        Ok(()) => 0,
        Err(op) => op as i32 + 1,
    }
}

#[no_mangle]
pub unsafe extern "C" fn qiwang_machine_run_until(
    machine: *mut Machine,
    stop_pc: u16,
    max_instructions: u64,
    nmi_every: u64,
    executed: *mut u64,
) -> i32 {
    let Some(machine) = machine.as_mut() else {
        return -1;
    };
    let mut count = 0;
    while count < max_instructions {
        if machine.pc == stop_pc {
            if !executed.is_null() {
                *executed = count;
            }
            return 0;
        }
        if let Err(op) = machine.step() {
            if !executed.is_null() {
                *executed = count;
            }
            return op as i32 + 1;
        }
        count += 1;
        if nmi_every != 0 && count % nmi_every == 0 {
            machine.nmi();
        }
    }
    if !executed.is_null() {
        *executed = count;
    }
    257
}

#[no_mangle]
pub unsafe extern "C" fn qiwang_machine_run_until_count_pc(
    machine: *mut Machine,
    stop_pc: u16,
    count_pc: u16,
    max_instructions: u64,
    nmi_every: u64,
    executed: *mut u64,
    pc_hits: *mut u64,
) -> i32 {
    let Some(machine) = machine.as_mut() else {
        return -1;
    };
    let mut count = 0;
    let mut hits = 0;
    while count < max_instructions {
        if machine.pc == stop_pc {
            if !executed.is_null() {
                *executed = count;
            }
            if !pc_hits.is_null() {
                *pc_hits = hits;
            }
            return 0;
        }
        if machine.pc == count_pc {
            hits += 1;
        }
        if let Err(op) = machine.step() {
            if !executed.is_null() {
                *executed = count;
            }
            if !pc_hits.is_null() {
                *pc_hits = hits;
            }
            return op as i32 + 1;
        }
        count += 1;
        if nmi_every != 0 && count % nmi_every == 0 {
            machine.nmi();
        }
    }
    if !executed.is_null() {
        *executed = count;
    }
    if !pc_hits.is_null() {
        *pc_hits = hits;
    }
    257
}

#[no_mangle]
pub unsafe extern "C" fn qiwang_machine_read(machine: *mut Machine, addr: u16) -> u8 {
    machine.as_mut().map_or(0, |m| m.read(addr))
}

#[no_mangle]
pub unsafe extern "C" fn qiwang_machine_write(machine: *mut Machine, addr: u16, value: u8) {
    if let Some(machine) = machine.as_mut() {
        machine.write(addr, value);
    }
}

#[no_mangle]
pub unsafe extern "C" fn qiwang_machine_copy_ram(
    machine: *const Machine,
    output: *mut u8,
    len: usize,
) -> usize {
    let Some(machine) = machine.as_ref() else {
        return 0;
    };
    if output.is_null() {
        return 0;
    }
    let count = len.min(0x800);
    ptr::copy_nonoverlapping(machine.ram.as_ptr(), output, count);
    count
}

#[no_mangle]
pub unsafe extern "C" fn qiwang_machine_set_ram(
    machine: *mut Machine,
    input: *const u8,
    len: usize,
) -> usize {
    let Some(machine) = machine.as_mut() else {
        return 0;
    };
    if input.is_null() {
        return 0;
    }
    let count = len.min(0x800);
    ptr::copy_nonoverlapping(input, machine.ram.as_mut_ptr(), count);
    count
}

#[no_mangle]
pub unsafe extern "C" fn qiwang_machine_get_register(machine: *const Machine, index: u8) -> u64 {
    let Some(m) = machine.as_ref() else {
        return 0;
    };
    match index {
        0 => m.a as u64,
        1 => m.x as u64,
        2 => m.y as u64,
        3 => m.sp as u64,
        4 => m.pc as u64,
        5 => m.p as u64,
        6 => m.cycles,
        7 => m.prg_bank as u64,
        8 => m.open_bus as u64,
        9 => m.reg4100 as u64,
        10 => m.ppustatus_toggle as u64,
        11 => m.pad1 as u64,
        12 => m.pad1_shift as u64,
        13 => m.pad_strobe as u64,
        _ => 0,
    }
}

#[no_mangle]
pub unsafe extern "C" fn qiwang_machine_set_register(machine: *mut Machine, index: u8, value: u64) {
    let Some(m) = machine.as_mut() else {
        return;
    };
    match index {
        0 => m.a = value as u8,
        1 => m.x = value as u8,
        2 => m.y = value as u8,
        3 => m.sp = value as u8,
        4 => m.pc = value as u16,
        5 => m.p = value as u8,
        6 => m.cycles = value,
        7 => m.prg_bank = value as u8 & 1,
        8 => m.open_bus = value as u8,
        9 => m.reg4100 = value as u8,
        10 => m.ppustatus_toggle = value != 0,
        11 => m.pad1 = value as u8,
        12 => m.pad1_shift = value as u8,
        13 => m.pad_strobe = value as u8,
        _ => {}
    }
}
