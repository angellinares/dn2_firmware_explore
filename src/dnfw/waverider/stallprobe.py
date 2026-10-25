"""A diagnostic DSP stream: what does the SHARC+ in the instrument charge for an instruction pair?

    section7_stall(stock) -> stock DN2 1.11's section 7, plus the idle-time stub
        (`dsp.section7_idle_only`), plus stall.asm, its state block and its data.
    asm() -> stall.asm's text, before its jump targets are resolved.

Batch A of the Waverider load plan saved about 4.5 points of a frame on the instrument in its
plain-reader part (load plan #2), and digikit's cycle model, which prices the stalls the
SHARC+ Programming Reference lists, sees 0.4 (2026-10-25). So the chip charges for something
the manual's tables leave out. This probe times it on the chip.

Each test runs in the idle task: a DO loop of PASSES passes over a body, timed with EMUCLK,
TRIALS times in a row, every run of the suite. The probe keeps each test's least and most
cycles over every trial. Two kinds of test:

- **pairs.** A body is 8 copies of an instruction pair. Each pair has a control with the
  same instructions, where the second does not read what the first wrote. The difference,
  over 8 x PASSES pairs, is the stall of one pair. `nop` gives the loop's own cost.
- **readers.** The sample loop of reader_miph2.asm before batch A (fmdepth2, Waverider 0.3.6)
  and after it (batcha1, 0.3.7), verbatim, over SAMPLES samples of two guarded rows in DDR,
  as the instrument plays them. The two compute the same samples bit for bit, so the
  emulator check compares their outputs.

The suite runs on the first call of the idle task, then once every RUN_EVERY calls until
RUNS_TOTAL runs. Interrupts stay on: one that lands inside a trial only raises that trial,
so the least of all trials is the cost. Every other call publishes one more half of the
words PUBTAB names, every 64th call, through reply word 2, as accelprobe does:
TAG << 16 | HALF, TAG = the half's index + 1 (`tools/dn2stall.py`).
"""

from __future__ import annotations

import json
import pathlib
import random
import struct

from dnfw.image import bootstream, sharc_object
from dnfw.waverider import dsp

STALL_DM = 0x2E4400                    # stall.asm, below the 32 KB DM cache's first byte (dsp.DM_CACHE_32K)
STALL_SW = STALL_DM // 2               # 0x172200
STALL_END = dsp.DM_CACHE_32K
STATE_DM = 0x2DF000                    # dsp.IDLE_PAD_END: right after the idle stub
STATE_BYTES = 0x800
SAVE_DM = STATE_DM                     # R0-R15, I0-I4
TICK_DM = STATE_DM + 0x60
PUBI_DM = STATE_DM + 0x64
RUNS_DM = STATE_DM + 0x68              # suite runs done (published)
NHALVES_DM = STATE_DM + 0x6C
T0_DM = STATE_DM + 0x70                # a trial's start, EMUCLK
PARAM_DM = STATE_DM + 0x80             # the readers' parameter block (I4): word 2 is the increment
RESULTS_DM = STATE_DM + 0x100          # least, most: two words a test
PUBTAB_DM = STATE_DM + 0x300
MAX_PUB = 0x80
SCRATCH_DM = STATE_DM + 0x500          # the pairs' words: -15, 0.5f, a store target
OUT_OLD_DM = STATE_DM + 0x600          # the readers' outputs, SAMPLES words each
OUT_NEW_DM = STATE_DM + 0x680
# the readers' absolute words, at their Waverider addresses (no Waverider in this stream)
GAIN_DM, FLAG_DM, FFW_DM = 0x2DE6C0, 0x2DE6C4, 0x2E3204
ROWS_DDR = dsp.DDR_REGION[0]           # rows a and b, guarded (dnfw.waverider.mip.row_points)
REPLY_WORD2 = (0x2C49D8, 0x2C59D8)

PASSES, TRIALS, SAMPLES = 64, 8, 32
RUN_EVERY, RUNS_TOTAL = 0x40000, 16    # about 32 ms of idle calls apart on the instrument
BITS = 11                              # a 2048-sample row, as Growlaren's
ROW_BYTES = 2 ** (BITS + 1) + 6
INC = round(2 ** 32 * 440 / 48000)     # 440 Hz at 2048 samples a cycle
PHASE0 = 0x12345678
FF = 0.25                              # the frame fraction between rows a and b
GAIN = 0.8
LEAST0 = 0x7FFFFFFF

CODE = pathlib.Path(__file__).with_name("stall_code.json")
SOURCE = pathlib.Path(__file__).resolve().parents[3] / "csrc" / "waverider" / "sharc" / "stall.asm"


def _f32bits(x: float) -> int:
    return struct.unpack("<I", struct.pack("<f", x))[0]


# (name, the pair, the control): the control's second instruction reads nothing the first wrote.
# The pairs come from the old reader's loop (fmdepth2), where a value loaded or computed feeds
# the next instruction, plus the PRM's own cases as a check of the method.
PAIRS = (
    ("ld_add", ("R0 = DM(2, I4);", "R9 = R9 + R0;"), ("R0 = DM(2, I4);", "R9 = R9 + R1;")),
    ("abs_fmul", (f"R1 = DM({GAIN_DM:#x});", "F0 = F1 * F3;"), (f"R1 = DM({GAIN_DM:#x});", "F0 = F2 * F3;")),
    ("abs_pass", (f"R1 = DM({FLAG_DM:#x});", "R1 = PASS R1;"), (f"R1 = DM({FLAG_DM:#x});", "R2 = PASS R2;")),
    ("idx_fmul", ("R1 = DM(I1, M5);", "F0 = F1 * F3;"), ("R1 = DM(I1, M5);", "F0 = F2 * F3;")),
    ("ld_floatby", ("R8 = DM(I0, M5);", "F4 = FLOAT R4 BY R8;"), ("R7 = DM(I0, M5);", "F4 = FLOAT R4 BY R8;")),
    ("imm_floatby", ("R8 = -15;", "F4 = FLOAT R4 BY R8;"), ("R7 = -15;", "F4 = FLOAT R4 BY R8;")),
    ("fadd_fadd", ("F0 = F5 - F6;", "F1 = F0 + F0;"), ("F0 = F5 - F6;", "F1 = F3 + F3;")),
    ("fadd_fmul", ("F0 = F5 + F2;", "F1 = F0 * F4;"), ("F0 = F5 + F2;", "F1 = F3 * F4;")),
    ("fmul_fadd", ("F0 = F5 * F4;", "F1 = F0 + F2;"), ("F0 = F5 * F4;", "F1 = F3 + F2;")),
    ("fadd_store", ("F0 = F5 + F6;", "DM(I2, M5) = F0;"), ("F0 = F5 + F6;", "DM(I2, M5) = F1;")),
    ("pass_ifne", ("R3 = PASS R3;", "IF NE F0 = F5 + F2;"), ("R3 = PASS R3;", "F0 = F5 + F2;")),
    ("f0_single", ("F0 = FLOAT R0 BY R8;", "F1 = FLOAT R1 BY R8;"), ("F2 = FLOAT R0 BY R8;", "F1 = FLOAT R1 BY R8;")),
    ("fix_fix", ("R0 = R1 + R2;", "R3 = R0 + R4;"), ("R0 = R1 + R2;", "R3 = R5 + R4;")),
    ("ddr_swse", ("R4 = DM(I3, M5) (SWSE);", "NOP;"), ("R4 = DM(I0, M5);", "NOP;")),
    ("ddr_use", ("R4 = DM(I3, M5) (SWSE);", "R9 = R9 + R4;"), ("R4 = DM(I3, M5) (SWSE);", "R9 = R9 + R1;")),
)

# reader_miph2.asm's sample loop, the loop label to the last instruction (which ends the DO
# loop): before batch A (main at e4d6a8e, the fmdepth2 build) and after it (#265, batcha1).
READER_OLD = """\
      R0 = LSHIFT R9 BY R13;
      R0 = LSHIFT R0 BY 1;
      R1 = R12 + R0;
      R0 = R11 + R0;
      I0 = R1;
      I1 = R0;
      R0 = R9 AND R14;
      F10 = FLOAT R0 BY R15;
      R4 = DM(I0, M6) (SWSE);
      R5 = DM(I0, M6) (SWSE);
      R6 = DM(I0, M6) (SWSE);
      R7 = DM(I0, M6) (SWSE);
      R0 = DM(I1, M6) (SWSE);
      R1 = DM(I1, M6) (SWSE);
      R2 = DM(I1, M6) (SWSE);
      R3 = DM(I1, M6) (SWSE);
      F4 = FLOAT R4 BY R8;
      F5 = FLOAT R5 BY R8;
      F6 = FLOAT R6 BY R8;
      F7 = FLOAT R7 BY R8;
      F0 = FLOAT R0 BY R8;
      F1 = FLOAT R1 BY R8;
      F2 = FLOAT R2 BY R8;
      F3 = FLOAT R3 BY R8;
      R8 = DM(0x2e3204);
      F0 = F0 - F4;
      F1 = F1 - F5;
      F2 = F2 - F6;
      F3 = F3 - F7;
      F0 = F8 * F0;
      F1 = F8 * F1;
      F2 = F8 * F2;
      F3 = F8 * F3;
      F4 = F4 + F0;
      F5 = F5 + F1;
      F6 = F6 + F2;
      F7 = F7 + F3;
      F0 = F5 - F6;
      F1 = F7 - F4;
      F2 = F4 - F5;
      F3 = F6 - F5;
      F8 = F0 + F0;
      F2 = F2 + F2;
      F3 = F3 + F3;
      F7 = F7 - F5;
      F0 = F8 + F0;
      F3 = F3 + F3;
      F6 = F6 - F4;
      F0 = F0 + F1;
      F2 = F2 + F3;
      F4 = F10 + F10;
      F2 = F2 - F7;
      R8 = -15;
      F0 = F0 * F4;
      F0 = F0 + F2;
      F0 = F0 * F4;
      F0 = F0 + F6;
.NOCOMPRESS;
      F0 = F0 * F10;
      F0 = F0 + F5;
      R1 = DM(0x2de6c0);
      F0 = F1 * F0;
      R1 = DM(0x2de6c4);
      R1 = PASS R1;
      R2 = DM(0, I2);
      IF NE F0 = F0 + F2;
      DM(I2, M6) = F0;
      R0 = DM(2, I4);
@LAST@      R9 = R9 + R0;
"""

READER_NEW = """\
      R0 = LSHIFT R9 BY R13;
      R0 = LSHIFT R0 BY 1;
      R1 = R12 + R0;
      R0 = R11 + R0;
      I0 = R1;
      I1 = R0;
      R0 = R9 AND R14;
      F10 = FLOAT R0 BY R15;
      R0 = DM(2, I4);
      R4 = DM(I0, M6) (SWSE);
      R5 = DM(I0, M6) (SWSE);
      R6 = DM(I0, M6) (SWSE);
      R7 = DM(I0, M6) (SWSE);
      R9 = R9 + R0;
      R0 = DM(I1, M6) (SWSE);
      R1 = DM(I1, M6) (SWSE);
      R2 = DM(I1, M6) (SWSE);
      R3 = DM(I1, M6) (SWSE);
      F4 = FLOAT R4;
      F5 = FLOAT R5;
      F6 = FLOAT R6;
      F7 = FLOAT R7;
      F1 = FLOAT R1;
      F2 = FLOAT R2;
      F3 = FLOAT R3;
      F0 = FLOAT R0;
      F0 = F0 - F4;
      F1 = F1 - F5;
      F2 = F2 - F6;
      F3 = F3 - F7;
      F0 = F8 * F0;
      F1 = F8 * F1;
      F2 = F8 * F2;
      F3 = F8 * F3;
      F4 = F4 + F0;
      F5 = F5 + F1;
      F6 = F6 + F2;
      F7 = F7 + F3;
      F0 = F5 - F6;
      F2 = F4 - F5;
      F3 = F6 - F5;
      F1 = F0 + F0;
      F2 = F2 + F2;
      F3 = F3 + F3;
      F0 = F1 + F0;
      F1 = F7 - F4;
      F7 = F7 - F5;
      F3 = F3 + F3;
      F6 = F6 - F4;
      F0 = F0 + F1;
      F2 = F2 + F3;
      F4 = F10 + F10;
      F2 = F2 - F7;
.NOCOMPRESS;
      F0 = F0 * F4;
      R1 = DM(0x2e3204);
      F0 = F0 + F2;
      R3 = DM(0x2de6c4);
      F0 = F0 * F4;
      R2 = DM(0, I2);
      F0 = F0 + F6;
      F0 = F0 * F10;
      F0 = F0 + F5;
      F0 = F1 * F0;
      R3 = PASS R3;
      IF NE F0 = F0 + F2;
@LAST@      DM(I2, M6) = F0;
"""

# (name, the body, R8 before the loop, the word at FFW_DM, the output buffer)
READERS = (("reader_old", READER_OLD, -15 & 0xFFFFFFFF, _f32bits(FF), OUT_OLD_DM),
           ("reader_new", READER_NEW, _f32bits(FF), _f32bits(GAIN * 2.0 ** -15), OUT_NEW_DM))


def tests() -> list[str]:
    """Every timed test, in RESULTS order."""
    out = ["nop"]
    for name, _, _ in PAIRS:
        out += [name, f"{name}.ctl"]
    return out + [r[0] for r in READERS]


def _trial(label: str, slot: int, setup: list[str], body: str, passes: int) -> list[str]:
    """TRIALS timed runs of BODY (whose last instruction line starts with @LAST@)."""
    least, most = RESULTS_DM + 8 * slot, RESULTS_DM + 8 * slot + 4
    body = body.replace("@LAST@", f"{label}_e.:\n")
    return [f"// {label}",
            f"      R0 = {TRIALS};",
            f"      LCNTR = R0, DO {label}_t. UNTIL LCE;",
            *setup,
            "      R0 = EMUCLK;",
            f"      DM({T0_DM:#x}) = R0;",
            f"      R0 = {passes};",
            f"      LCNTR = R0, DO {label}_e. UNTIL LCE;",
            body.rstrip("\n"),
            ".NOCOMPRESS;",
            "      R0 = EMUCLK;",
            f"      R1 = DM({T0_DM:#x});",
            "      R0 = R0 - R1;",
            f"      R1 = DM({least:#x});",
            "      R1 = MIN(R1, R0);",
            f"      DM({least:#x}) = R1;",
            f"      R1 = DM({most:#x});",
            "      R1 = MAX(R1, R0);",
            f"{label}_t.:",
            f"      DM({most:#x}) = R1;"]


PAIR_SETUP = [f"      R{k} = {_f32bits(0.5):#x};" for k in range(8)] + [
    "      R3 = 1;",                                   # pass_ifne: NE holds
    "      R8 = -15;",
    "      R9 = R9 - R9;",
    f"      I0 = {SCRATCH_DM:#x};",                     # -15
    f"      I1 = {SCRATCH_DM + 4:#x};",                 # 0.5f
    f"      I2 = {SCRATCH_DM + 8:#x};",                 # a store target
    f"      I3 = {ROWS_DDR:#x};",
    f"      I4 = {PARAM_DM:#x};"]


def _pair_body(pair: tuple[str, str]) -> str:
    lines = [f"      {pair[0]}\n      {pair[1]}\n" for _ in range(8)]
    lines[-1] = f"      {pair[0]}\n@LAST@      {pair[1]}\n"
    return "".join(lines)


def suite() -> list[str]:
    out, slot = [".NOCOMPRESS;"], 0
    out += [*PAIR_SETUP, *_trial("st_nop", slot, [], "      NOP;\n" * 15 + "@LAST@      NOP;\n", PASSES)]
    for name, pair, ctl in PAIRS:
        for label, body in ((name, pair), (f"{name}_ctl", ctl)):
            slot += 1
            out += [*PAIR_SETUP, *_trial(f"st_{label}", slot, [], _pair_body(body), PASSES)]
    for name, body, r8, ffw, outbuf in READERS:
        slot += 1
        out += [f"      R0 = {ffw:#x};", f"      DM({FFW_DM:#x}) = R0;"]
        setup = [f"      R8 = {r8:#x};", f"      R9 = {PHASE0:#x};",
                 f"      R11 = {ROWS_DDR + ROW_BYTES:#x};", f"      R12 = {ROWS_DDR:#x};",
                 f"      R13 = {-(32 - BITS)};", f"      R14 = {(1 << (32 - BITS)) - 1:#x};",
                 f"      R15 = {-(33 - BITS)};", f"      I2 = {outbuf:#x};", f"      I4 = {PARAM_DM:#x};"]
        out += _trial(f"st_{name}", slot, setup, ".COMPRESS;\n" + body, SAMPLES)
    return out


REGS = [f"R{k}" for k in range(16)] + [f"I{k}" for k in range(5)]


def asm() -> str:
    """stall.asm's text, its branch targets as `JUMP 0x0; // -> label.` for
    scripts/sharc_resolve_jumps.py to fill in."""
    save = [f"      DM({SAVE_DM + 4 * k:#x}) = {r};" for k, r in enumerate(REGS)]
    restore = [f"      {r} = DM({SAVE_DM + 4 * k:#x});" for k, r in enumerate(REGS)]
    head = f"""\
// stall.asm -- what does the SHARC+ in the instrument charge for an instruction pair?
//
// GENERATED by dnfw.waverider.stallprobe.asm() (its docstring is the description), then its
// jump targets resolved by scripts/sharc_resolve_jumps.py: edit the generator, not this file.
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never linked
// in). A diagnostic, never a mod: scripts/build_stallprobe.py builds it, tools/dn2stall.py
// reads it.
//
// The idle loop's back edge jumps here; this goes on to idle_load.asm (wr_idle). It uses
// R0-R15 and I0-I4, saved to its state block and restored before wr_idle; ASTAT is free.
// PLACEMENT IS FIXED: PM sw {STALL_SW:#x} (L1 block 1, byte {STALL_DM:#x}).

.SECTION/PM seg_pmco;

.GLOBAL wr_stall.;
wr_stall.:
"""
    body = [*save,
            f"      R0 = DM({TICK_DM:#x});",
            "      R1 = 1;",
            "      R0 = R1 + R0;",
            f"      DM({TICK_DM:#x}) = R0;",
            f"      R2 = DM({RUNS_DM:#x});",
            f"      R3 = {RUNS_TOTAL};",
            "      COMP(R2, R3);",
            "      IF GE JUMP 0x0;                  // -> wr_stall_pub.",
            f"      R3 = {RUN_EVERY - 1:#x};",
            "      R3 = R0 AND R3;",
            "      COMP(R3, R1);",
            "      IF NE JUMP 0x0;                  // -> wr_stall_pub.",
            "      R2 = R1 + R2;",
            f"      DM({RUNS_DM:#x}) = R2;",
            *suite(),
            ".COMPRESS;",
            "      JUMP 0x0;                        // -> wr_stall_out.",
            "",
            ".GLOBAL wr_stall_pub.;",
            "wr_stall_pub.:",
            f"      R0 = DM({TICK_DM:#x});",
            "      R1 = 63;",
            "      R0 = R0 AND R1;",
            "      IF NE JUMP 0x0;                  // -> wr_stall_out.",
            f"      R0 = DM({PUBI_DM:#x});            // k",
            "      R1 = LSHIFT R0 BY -1;",
            "      R1 = LSHIFT R1 BY 2;",
            f"      R2 = {PUBTAB_DM:#x};",
            "      R1 = R2 + R1;",
            "      I0 = R1;",
            "      R2 = DM(0, I0);                  // the word's address",
            "      I0 = R2;",
            "      R2 = DM(0, I0);                  // the word",
            "      R3 = 1;",
            "      R3 = R0 AND R3;",
            "      IF EQ JUMP 0x0;                  // -> wr_stall_low.",
            "      R2 = LSHIFT R2 BY -16;           // k odd: the high half",
            "",
            ".GLOBAL wr_stall_low.;",
            "wr_stall_low.:",
            "      R3 = 0xffff;",
            "      R2 = R2 AND R3;                  // HALF",
            "      R3 = 1;",
            "      R4 = R3 + R0;                    // TAG = k + 1",
            "      R2 = LSHIFT R2 BY 16;",
            "      R2 = R2 OR R4;                   // halves swapped: the ColdFire reads TAG << 16 | HALF",
            f"      DM({REPLY_WORD2[0]:#x}) = R2;            // reply word 2, both pages",
            f"      DM({REPLY_WORD2[1]:#x}) = R2;",
            f"      R3 = DM({NHALVES_DM:#x});",
            "      COMP(R4, R3);",
            "      IF LT JUMP 0x0;                  // -> wr_stall_next.",
            "      R4 = R4 - R4;",
            "",
            ".GLOBAL wr_stall_next.;",
            "wr_stall_next.:",
            f"      DM({PUBI_DM:#x}) = R4;",
            "",
            ".GLOBAL wr_stall_out.;",
            "wr_stall_out.:",
            *restore,
            "      JUMP 0x0;                        // -> wr_idle."]
    return head + "\n".join(body) + "\n"


def published() -> list[tuple[str, int]]:
    """(name, DM byte address) of every word stall.asm publishes, in PUBTAB order."""
    out = [("runs", RUNS_DM)]
    for k, name in enumerate(tests()):
        out += [(f"{name}.least", RESULTS_DM + 8 * k), (f"{name}.most", RESULTS_DM + 8 * k + 4)]
    if len(out) > MAX_PUB:
        raise dsp.DspError(f"{len(out)} published words, PUBTAB holds {MAX_PUB}")
    return out


def state() -> bytes:
    """The state block at boot: the parameter block's increment, every test's least at
    LEAST0, PUBTAB, NHALVES and the pairs' scratch words; the rest 0."""
    out = bytearray(STATE_BYTES)
    pub = published()
    struct.pack_into("<I", out, NHALVES_DM - STATE_DM, 2 * len(pub))
    struct.pack_into("<I", out, PARAM_DM - STATE_DM + 8, INC)
    for k in range(len(tests())):
        struct.pack_into("<I", out, RESULTS_DM - STATE_DM + 8 * k, LEAST0)
    for k, (_, at) in enumerate(pub):
        struct.pack_into("<I", out, PUBTAB_DM - STATE_DM + 4 * k, at)
    struct.pack_into("<Ii", out, SCRATCH_DM - STATE_DM, -15 & 0xFFFFFFFF, 0)
    struct.pack_into("<f", out, SCRATCH_DM - STATE_DM + 4, 0.5)
    return bytes(out)


def rows() -> bytes:
    """Rows a and b, guarded: [the frame's last sample, the frame, its first two], int16 of a
    fixed pseudo-random sequence."""
    rng = random.Random(2026_10_25)
    out = b""
    for _ in range(2):
        frame = [rng.randint(-30000, 30000) for _ in range(2 ** BITS)]
        out += struct.pack(f"<{len(frame) + 3}h", frame[-1], *frame, frame[0], frame[1])
    return out


def objects() -> dict[str, bytes]:
    """The committed stall.asm and the idle back edge's JUMP to it."""
    spec = json.loads(CODE.read_text(encoding="utf-8"))
    return {name: sharc_object.load_bytes(bytes.fromhex(spec[name]["object_parcels_be"]))
            for name in ("stall", "stall_jump")}


def section7_stall(stock: bytes) -> bytes:
    """Stock + the idle stub + stall.asm, its state and its data. The idle loop's back edge
    goes to stall.asm, which goes on to the idle stub."""
    base = dsp.section7_idle_only(stock)
    obj = objects()
    code = obj["stall"]
    if STALL_DM + len(code) > STALL_END:
        raise dsp.DspError(f"stall.asm is {len(code)} bytes: it passes {STALL_END:#x}")
    if len(obj["stall_jump"]) != len(dsp.IDLE_SITE_STOCK):
        raise dsp.DspError(f"the stall JUMP is {len(obj['stall_jump'])} bytes, not {len(dsp.IDLE_SITE_STOCK)}")
    words = struct.pack("<fI", GAIN, 0)               # GAIN_DM, FLAG_DM (0: osc 1, no add)
    added = [("stall.asm (wr_stall)", dsp.dm_to_load(STALL_DM), code),
             ("stall state", dsp.dm_to_load(STATE_DM), state()),
             ("stall gain and flag", dsp.dm_to_load(GAIN_DM), words),
             ("stall ff word", dsp.dm_to_load(FFW_DM), bytes(4)),
             ("stall rows (DDR)", ROWS_DDR, rows())]
    dsp._check_free(stock, added)
    taken = [(at, at + len(p)) for _, at, p in dsp.idle_spans()]
    for what, at, payload in added:
        if any(lo < at + len(payload) and at < hi for lo, hi in taken):
            raise dsp.DspError(f"{what} overlaps the idle stub")
    extra = b"".join(bootstream.block(at, payload) for _, at, payload in added)
    out = bytearray(bootstream.insert_before_final(base, extra))
    bootstream.write_span(out, dsp.l2_sw_to_load(dsp.IDLE_SITE_SW), obj["stall_jump"])
    return dsp._finish(out)


def decode(word: int) -> tuple[int, int]:
    """A reply word 2 as the ColdFire reads it (big-endian u32) -> (half index k, the half)."""
    return (word >> 16) - 1, word & 0xFFFF


def words(halves: dict[int, int]) -> dict[str, int]:
    """Half index -> half, as collected -> name -> the published word, for each word with
    both halves seen."""
    out = {}
    for k, (name, _) in enumerate(published()):
        lo, hi = halves.get(2 * k), halves.get(2 * k + 1)
        if lo is not None and hi is not None:
            out[name] = hi << 16 | lo
    return out


def report(w: dict[str, int]) -> list[str]:
    """Per pair: the stall of one pair, (least - the control's least) / (8 x PASSES); per
    reader: cycles a sample; and the two readers' difference."""
    lines = [f"  suite runs: {w.get('runs', '?')} of {RUNS_TOTAL}"]
    nop = w.get("nop.least")
    if nop is not None:
        lines.append(f"  nop: {nop:,} cycles for {16 * PASSES} NOPs ({nop / (16 * PASSES):.3f} a NOP, "
                     f"the loop and the clock reads included)")
    for name, _, _ in PAIRS:
        a, b = w.get(f"{name}.least"), w.get(f"{name}.ctl.least")
        if a is None or b is None:
            lines.append(f"  {name}: not all read")
            continue
        lines.append(f"  {name:12} {a:7,} against {b:7,}: {(a - b) / (8 * PASSES):+.2f} cycles a pair")
    per = {}
    for name, *_ in READERS:
        c = w.get(f"{name}.least")
        if c is not None:
            per[name] = c / SAMPLES
            lines.append(f"  {name}: {c:,} cycles, {c / SAMPLES:.1f} a sample "
                         f"(most {w.get(f'{name}.most', 0):,})")
    if len(per) == 2:
        d = per["reader_old"] - per["reader_new"]
        lines.append(f"  the old reader costs {d:+.1f} cycles a sample more than the new one "
                     f"({d * 16 * 2 * 32 / 666_667 * 100:+.2f} points of a frame on 16 voices x 2 oscillators)")
    return lines
