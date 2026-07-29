"""Optional compiled 6502 runner used by :mod:`pyqiwang._harness`.

The extension is deliberately loaded through a small C ABI instead of binding
Python into the instruction loop.  A complete CPU/bus snapshot is copied into
Rust before a run and copied back afterwards.  The existing Python MOS6502 and
Mapper133Bus therefore remain the public/debug state and the compatibility
fallback for hooks and tracing.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path

_REGISTER_NAMES = (
    "a", "x", "y", "sp", "pc", "p", "cycles", "prg_bank", "open_bus",
    "reg4100", "ppustatus_toggle", "pad1", "_pad1_shift", "_pad_strobe",
)


class Fast6502Unavailable(RuntimeError):
    pass


class Fast6502ExecutionError(RuntimeError):
    pass


def _library_names() -> tuple[str, ...]:
    if os.name == "nt":
        return ("pyqiwang_fast6502.dll",)
    if os.uname().sysname == "Darwin":
        return ("libpyqiwang_fast6502.dylib",)
    return ("libpyqiwang_fast6502.so",)


def _library_candidates() -> list[Path]:
    package = Path(__file__).resolve().parent
    root = package.parent
    candidates: list[Path] = []
    configured = os.environ.get("PYQIWANG_FAST6502_LIBRARY")
    if configured:
        candidates.append(Path(configured))
    for name in _library_names():
        candidates.extend((
            package / name,
            package / "_native" / name,
            root / "rust" / "fast6502" / "target" / "release" / name,
        ))
    return candidates


def find_fast6502_library() -> Path | None:
    return next((path for path in _library_candidates() if path.is_file()), None)


class Fast6502Runner:
    """Run hook-free ROM regions in the compiled core."""

    def __init__(self, prg: bytes):
        path = find_fast6502_library()
        if path is None:
            raise Fast6502Unavailable(
                "compiled fast6502 library not found; build rust/fast6502 "
                "with `cargo build --release`"
            )
        self.path = path
        self._lib = ctypes.CDLL(str(path))
        self._configure_abi()
        data = (ctypes.c_uint8 * len(prg)).from_buffer_copy(prg)
        self._machine = self._lib.qiwang_machine_new(data, len(prg))
        if not self._machine:
            raise Fast6502Unavailable("compiled core rejected the 64KB PRG image")

    def _configure_abi(self) -> None:
        lib = self._lib
        pointer = ctypes.c_void_p
        lib.qiwang_machine_new.argtypes = (ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t)
        lib.qiwang_machine_new.restype = pointer
        lib.qiwang_machine_free.argtypes = (pointer,)
        lib.qiwang_machine_free.restype = None
        lib.qiwang_machine_step.argtypes = (pointer,)
        lib.qiwang_machine_step.restype = ctypes.c_int
        lib.qiwang_machine_run_until.argtypes = (
            pointer, ctypes.c_uint16, ctypes.c_uint64, ctypes.c_uint64,
            ctypes.POINTER(ctypes.c_uint64),
        )
        lib.qiwang_machine_run_until.restype = ctypes.c_int
        lib.qiwang_machine_copy_ram.argtypes = (
            pointer, ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t,
        )
        lib.qiwang_machine_copy_ram.restype = ctypes.c_size_t
        lib.qiwang_machine_set_ram.argtypes = (
            pointer, ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t,
        )
        lib.qiwang_machine_set_ram.restype = ctypes.c_size_t
        lib.qiwang_machine_get_register.argtypes = (pointer, ctypes.c_uint8)
        lib.qiwang_machine_get_register.restype = ctypes.c_uint64
        lib.qiwang_machine_set_register.argtypes = (pointer, ctypes.c_uint8, ctypes.c_uint64)
        lib.qiwang_machine_set_register.restype = None

    def close(self) -> None:
        machine = getattr(self, "_machine", None)
        if machine:
            self._lib.qiwang_machine_free(machine)
            self._machine = None

    def __del__(self):
        self.close()

    def _set_state(self, cpu, bus) -> None:
        ram = (ctypes.c_uint8 * 0x800).from_buffer_copy(bus.ram)
        copied = self._lib.qiwang_machine_set_ram(self._machine, ram, 0x800)
        if copied != 0x800:
            raise Fast6502ExecutionError("failed to copy RAM into compiled core")
        values = (
            cpu.a, cpu.x, cpu.y, cpu.sp, cpu.pc, cpu.p, cpu.cycles,
            bus.prg_bank, bus.open_bus, bus.reg4100, bus.ppustatus_toggle,
            bus.pad1, bus._pad1_shift, bus._pad_strobe,
        )
        for index, value in enumerate(values):
            self._lib.qiwang_machine_set_register(self._machine, index, int(value))

    def _get_state(self, cpu, bus) -> None:
        ram = (ctypes.c_uint8 * 0x800)()
        copied = self._lib.qiwang_machine_copy_ram(self._machine, ram, 0x800)
        if copied != 0x800:
            raise Fast6502ExecutionError("failed to copy RAM from compiled core")
        bus.ram[:] = bytes(ram)
        values = [
            self._lib.qiwang_machine_get_register(self._machine, index)
            for index in range(len(_REGISTER_NAMES))
        ]
        cpu.a, cpu.x, cpu.y, cpu.sp, cpu.pc, cpu.p = map(int, values[:6])
        cpu.cycles = int(values[6])
        bus.prg_bank = int(values[7])
        bus.open_bus = int(values[8])
        bus.reg4100 = int(values[9])
        bus.ppustatus_toggle = bool(values[10])
        bus.pad1 = int(values[11])
        bus._pad1_shift = int(values[12])
        bus._pad_strobe = int(values[13])

    def step(self, cpu, bus) -> None:
        self._set_state(cpu, bus)
        status = self._lib.qiwang_machine_step(self._machine)
        self._get_state(cpu, bus)
        if status != 0:
            opcode = status - 1
            raise Fast6502ExecutionError(
                f"compiled core encountered opcode ${opcode:02X} at "
                f"PC=${cpu.pc:04X}"
            )

    def run_until(self, cpu, bus, stop_pc: int, max_instructions: int,
                  nmi_every: int = 0) -> int:
        self._set_state(cpu, bus)
        executed = ctypes.c_uint64()
        status = self._lib.qiwang_machine_run_until(
            self._machine,
            stop_pc & 0xFFFF,
            max_instructions,
            nmi_every,
            ctypes.byref(executed),
        )
        self._get_state(cpu, bus)
        if status == 257:
            raise TimeoutError(
                f"compiled core ran {executed.value} instructions without "
                f"reaching ${stop_pc:04X} (PC=${cpu.pc:04X})"
            )
        if status != 0:
            opcode = status - 1
            raise Fast6502ExecutionError(
                f"compiled core encountered opcode ${opcode:02X} at "
                f"PC=${cpu.pc:04X}"
            )
        return int(executed.value)
