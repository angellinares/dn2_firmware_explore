"""A decoded SHARC+ instruction -> the static facts the stall rules need.

Input is digikit's decode (`type_name`, `fields`, `length_bytes`), passed in as
plain values so this module needs nothing of digikit. Field meanings follow
digikit's sharc_core forms: `g` = 1 selects DAG2 (I8..I15), `pmi` is a DAG2
index, `j` marks a delayed branch (DB), `b` a call, `cond` 31 is "true",
`idis` is XORed onto the source index to name a MODIFY's destination.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import computefield as cf

TRUE = 0x1F

# branch kinds
JUMP, CALL, RTS, RTI, DO, CJUMP, RFRAME = "jump", "call", "rts", "rti", "do", "cjump", "rframe"


@dataclass(frozen=True)
class Static:
    form: str
    length_sw: int                     # 1, 2 or 3 short words
    computes: tuple[cf.Compute, ...]
    dag_uses: tuple[int, ...]          # I registers (0..15) generating an address, or modified
    branch: str | None = None
    conditional: bool = False
    delayed: bool = False
    indirect: int | None = None        # the I register of an indirect branch
    ireg_imm: bool = False             # an I register loaded with an immediate (no stall)
    ireg_move: bool = False            # an I register written from a register (Ix = Rn)
    pm_data: bool = False              # a data access on the PM bus (Type 1's, or g = 1)


def _get(fields: dict, stem: str) -> int | None:
    """FIELDS' value for STEM, assembling split pieces (`pmi[2:2]`, `pmi[1:0]`)."""
    if stem in fields:
        return fields[stem]
    pieces = [(k, v) for k, v in fields.items() if k.startswith(stem + "[")]
    if not pieces:
        return None
    value = 0
    for key, v in pieces:
        lo = int(key[key.index("[") + 1:-1].split(":")[1])
        value |= v << lo
    return value


def _compute_field(fields: dict) -> int | None:
    hi, lo = fields.get("compute[22:16]"), fields.get("compute[15:0]")
    if hi is None or lo is None:
        return None
    return (hi << 16) | lo


def _bank(fields: dict) -> int:
    return 8 if fields.get("g") else 0


def _dag_uses(form: str, f: dict) -> tuple[int, ...]:
    g = _bank(f)
    if form in ("1a", "1b"):
        return (_get(f, "dmi"), 8 + _get(f, "pmi"))
    if form in ("3a", "3b", "3d", "4a", "4b", "4d", "6a_mem", "15a", "15b", "16a", "16b"):
        return (_get(f, "i") + g,)
    if form in ("3c", "10a_rel"):
        return (_get(f, "dmi"),)
    if form in ("7a", "7b", "7d", "19a", "19a_scaled", "19a_bitrev"):
        return (_get(f, "is") + g,)
    return ()


_G_SPACE = frozenset({"3a", "3b", "3d", "4a", "4b", "4d", "6a_mem", "15a", "15b", "16a", "16b"})
_UREG_I = range(0x10, 0x20)          # UREG codes of I0..I15


def classify(form: str, length_bytes: int, fields: dict) -> Static:
    f = fields
    computes: list[cf.Compute] = []
    if form == "2c":
        computes.append(cf.decode_short(_get(f, "compute")))
    else:
        field = _compute_field(f)
        if field is not None:
            c = cf.decode(field)
            if c is not None:
                computes.append(c)
    cond = _get(f, "cond")
    conditional = cond is not None and cond != TRUE
    delayed = bool(f.get("j"))
    branch = indirect = None
    if form.startswith("8a") or form.startswith("9a") or form.startswith("9b") or form == "10a_rel":
        branch = CALL if f.get("b") else JUMP
        if form in ("9a_abs", "9b_abs"):
            indirect = 8 + _get(f, "pmi")
        if form == "10a_rel":
            delayed = False
    elif form in ("11a", "11c"):
        branch = RTI if f.get("x") else RTS
    elif form in ("12a_imm", "12a_ureg", "13a"):
        branch, conditional, delayed = DO, False, False
    elif form in ("25a_direct", "25a_pcrel"):
        branch, conditional, delayed = CJUMP, False, True
    elif form in ("25a_rframe", "25c_rframe"):
        branch, conditional, delayed = RFRAME, False, False
    ireg_imm = (form in ("17a", "17b") and _get(f, "ureg") in _UREG_I)
    ireg_move = (form in ("5a_move", "5b_move") and _get(f, "dstureg") in _UREG_I)
    pm_data = form in ("1a", "1b") or (form in _G_SPACE and bool(f.get("g")))
    return Static(form, length_bytes // 2, tuple(computes), _dag_uses(form, f),
                  branch, conditional, delayed, indirect, ireg_imm, ireg_move, pm_data)
