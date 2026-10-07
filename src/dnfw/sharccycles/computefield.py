"""A SHARC+ compute field -> what the pipeline's data-forwarding rules need.

The layout is the Programming Reference's (chapter 18; the same fields digikit's
sharc_core.compute decodes): a 23-bit field, bit 22 the multifunction selector,
bits 21:20 the unit (0 ALU, 1 multiplier, 2 shifter), 19:12 the opcode, 11:8 Rn,
7:4 Rx, 3:0 Ry. The 12-bit short compute of Type 2c has a 4-bit opcode, Rn, Rx.

Float-ness follows the opcode tables: ALU opcodes 0x80 and above (and the
double-precision 0x11..0x1f) run in the floating-point path, FIX and TRUNC
included; the multiplier's 0x30..0x33 are its float multiplies; the shifter is
fixed-point. A compare writes no register.
"""

from __future__ import annotations

from dataclasses import dataclass

ALU, MUL, SHIFT, MULTIFN, MRMOVE, OTHER = "alu", "mul", "shift", "multifn", "mrmove", "other"

_ALU_NO_DEST = frozenset({0x0A, 0x0B, 0x8A, 0x13})          # COMP, COMPU, float COMP, double COMP
_SHIFT_NO_DEST = frozenset({0xCC})                          # BTST
_SHORT_FLOAT = frozenset({0x8, 0x9, 0xA, 0xB, 0xF})
_SHORT_NO_DEST = frozenset({0x3, 0xB})


@dataclass(frozen=True)
class Compute:
    unit: str
    float_op: bool
    dests: tuple[int, ...]           # register-file numbers 0..15 written
    srcs: tuple[int, ...]            # register-file numbers 0..15 read
    single_operand: bool = False     # one source (PASS, ABS, NEG, FLOAT Rx, ...)


def decode(field: int) -> Compute | None:
    """FIELD, the 23-bit compute of a 48- or 32-bit form -> Compute; None for the
    empty compute (0, a form without one)."""
    if field == 0:
        return None
    if field >> 17 == 0b100000:
        rn = (field >> 8) & 0xF
        to_mr = (field >> 16) & 1 == 0
        return Compute(MRMOVE, False, () if to_mr else (rn,), (rn,) if to_mr else ())
    if (field >> 22) & 1:
        rm, ra = (field >> 12) & 0xF, (field >> 8) & 0xF
        srcs = ((field >> 6) & 3, 4 + ((field >> 4) & 3), 8 + ((field >> 2) & 3), 12 + (field & 3))
        return Compute(MULTIFN, True, (rm, ra), srcs)
    unit = (field >> 20) & 3
    opcode = (field >> 12) & 0xFF
    rn, rx, ry = (field >> 8) & 0xF, (field >> 4) & 0xF, field & 0xF
    if unit == 0:
        if (opcode >> 4) in (0x7, 0xF):                    # dual add/subtract: Rn and Rs
            return Compute(ALU, (opcode >> 4) == 0xF, (rn, opcode & 0xF), (rx, ry))
        float_op = opcode >= 0x80 or 0x11 <= opcode <= 0x1F
        single = opcode in (0x21, 0x22, 0x29, 0x2A, 0x30, 0x43, 0xA1, 0xA2, 0xA5, 0xAD,
                            0xB0, 0xC1, 0xC4, 0xC5, 0xC9, 0xCA, 0xCD)
        dests = () if opcode in _ALU_NO_DEST else (rn,)
        return Compute(ALU, float_op, dests, (rx,) if single else (rx, ry), single)
    if unit == 1:
        return Compute(MUL, 0x30 <= opcode <= 0x33, (rn,), (rx, ry))
    if unit == 2:
        # Rn = op Rx BY Ry; the field-deposit and OR forms also read Rn
        srcs = (rx, ry, rn) if opcode in (0x20, 0x70, 0x7C) else (rx, ry)
        return Compute(SHIFT, False, () if opcode in _SHIFT_NO_DEST else (rn,), srcs)
    return Compute(OTHER, False, (rn,), (rx, ry))


def decode_short(field: int) -> Compute:
    """The 12-bit Type 2c compute: `Rn = Rn op Rx` (opcode 11:8, Rn 7:4, Rx 3:0)."""
    opcode, rn, rx = (field >> 8) & 0xF, (field >> 4) & 0xF, field & 0xF
    unit = MUL if opcode in (0x7, 0xF) else ALU
    dests = () if opcode in _SHORT_NO_DEST else (rn,)
    single = opcode in (0x2, 0x4, 0x5, 0x6, 0xA)
    return Compute(unit, opcode in _SHORT_FLOAT, dests, (rx,) if single else (rn, rx), single)
