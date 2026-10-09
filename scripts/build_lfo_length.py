"""Build `lfolength`, the LFO ONE/HALF fix: trig modes ONE and HALF run one cycle / half
a cycle from the start phase, and hold the value they reached.

It folds in `lfohold` (2026-10-08, now superseded): the stop-table stores NOP'd, in both
evaluators (the published `lfohold` covered A only).

    python scripts/build_lfo_length.py [--out PATH]

The reading is `docs/lfo-trig-modes.md`. Stock 1.11 runs LFOs through two evaluators
with the same logic: **A** (`0x40137726`, audio tracks; phase 0..1,382,400,000 a cycle,
state block `0x4463fc18`) and **B** (`0x401373dc`, the MIDI tracks' LFOs; 0..21,600,000,
block `0x4463f498`). Each stops HALF (mode 4) on crossing the cycle's middle and ONE
(mode 3) on crossing its end, wherever the trig put the phase (SPH). So a later start
phase runs shorter.

**The fix shifts the phase's origin, for ONE and HALF only.** On a trig the phase starts
at 0 and the SPH cell's high byte is latched in the LFO record's free byte `+119`; the
waveform is read at phase + the latched point, wrapped into one cycle. Every stock test,
the cycle's wrap included, then counts from the start, in both speed directions. In any
other mode, and for waveforms past stock's 0..5 (lfowaves' new ones give SPH other
meanings: steps, width, repeats, a wavetable position), the latch is cleared at a trig
(TRIG keeps stock's phase = SPH point exactly),
and a latch left by a mode change mid-run is folded into the phase once, so the waveform
doesn't jump. RND (waveform 6) never reaches either hook: SPH is its SLEW.

Four hooks, each a `jmp` into the chunk (the displaced instructions replayed there):

| hook | site | what it displaced |
|---|---|---|
| A, the trig | `0x40137966` (10 B) | `movel %sp@(68),%d2 ; movel #1382400000,%d0` |
| A, the waveform | `0x401379ec` (6 B) | `movel #1667999861,%d0` |
| B, the trig | `0x4013755c` (10 B) | `mvsw %a4@(44),%d0 ; movel #21600000,%d2` |
| B, the waveform | `0x401375e4` (6 B) | `moveq #6,%d0 ; cmpl %d3,%d0 ; beqs` (RND) |

The latch byte: nothing in either evaluator, their resets (`0x401372f4`, `0x40137348`) or
block B's flag setter (`0x401373b8`, which writes `+118`) touches `+119`, and the only
code that moves whole records (the evaluator's 40-byte copies through `0x40134490`)
carries it with the phase. The SPH cell's low byte is zero (SPH 0..127 << 9), so its
high byte is the whole value.
"""

from __future__ import annotations

import argparse
import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw.cli.files import read_image                     # noqa: E402
from dnfw.container.section import compress               # noqa: E402
from dnfw.firmware import build as fwbuild                # noqa: E402
from dnfw.firmware.load import load                       # noqa: E402
from dnfw.mods import platform                            # noqa: E402
from dnfw.patch.assemble import assemble, available       # noqa: E402

BASE = 0x40000400
MAIN_OS = 3
CODE_VA = 0x467F8000          # below LFO4's region (0x46800000), past waverider's route (0x467e8000)
STOCK = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
OUT = ROOT / "00_Resources/02_Builds/lfolength_DN2_1.11.syx"

A_CYCLE, B_CYCLE = 1382400000, 21600000

SOURCE = f"""
    .text
| -- evaluator A (audio tracks): d4 = TRIG MODE, d3 = waveform, a2 = the LFO's state
| (fields +80 ..), %sp@(68) = the SPH cell sign-extended
lfa_trig:
    movel   %sp@(68),%d2            | replayed
    movel   #{A_CYCLE},%d0          | replayed
    moveq   #3,%d1
    cmpl    %d1,%d4
    blts    1f
    moveq   #4,%d1
    cmpl    %d1,%d4
    bgts    1f
    moveq   #5,%d1
    cmpl    %d1,%d3
    bgts    1f                      | not a stock waveform 0..5 (lfowaves' 7+: SPH isn't a phase there)
    movel   %d2,%d1                 | ONE / HALF: latch the cell's high byte ...
    asrl    #8,%d1
    moveb   %d1,%a2@(119)
    clrl    %d2                     | ... and start the phase at 0
    jmp     0x4013797e
1:  clrb    %a2@(119)               | any other mode: no latch, stock's start
    jmp     0x40137970

| d2 = the phase about to be read (stored at +80 already), d0/d1 free
lfa_wave:
    moveb   %a2@(119),%d0
    extbl   %d0
    beqs    9f
    swap    %d0
    clrw    %d0                     | (a negative byte's sign bits would otherwise ride in)
    lsll    #8,%d0                  | the cell << 16, as stock's trig multiply takes it
    movel   #{A_CYCLE},%d1
    macl    %d1,%d0,%acc0
    movclrl %acc0,%d0               | the latched point, -1/2 .. +1/2 cycle
    tstl    %d0                     | the sum stays within one cycle either way: phase + point
    bmis    1f                      | reaches 2.76e9 on the instrument, past a signed long
    subl    %d1,%d0                 | point >= 0: add (point - cycle), in -cycle .. 0
1:  addl    %d0,%d2
    bpls    2f
    addl    %d1,%d2                 | below 0: a cycle back
2:  moveq   #3,%d0
    cmpl    %d0,%d4
    blts    3f
    moveq   #4,%d0
    cmpl    %d0,%d4
    bles    9f                      | ONE / HALF: read there, the stored phase stays relative
3:  movel   %d2,%a2@(80)            | another mode now: fold the latch in once
    clrb    %a2@(119)
9:  movel   #1667999861,%d0         | replayed
    jmp     0x401379f2

| -- evaluator B (MIDI tracks): d4 = TRIG MODE, a2 = the LFO's state, a4 = its parameters
lfb_trig:
    mvsw    %a4@(44),%d0            | replayed: the SPH cell
    movel   #{B_CYCLE},%d2          | replayed
    moveq   #3,%d1
    cmpl    %d1,%d4
    blts    1f
    moveq   #4,%d1
    cmpl    %d1,%d4
    bgts    1f
    moveq   #5,%d1
    cmpl    %d1,%d3
    bgts    1f
    movel   %d0,%d1
    asrl    #8,%d1
    moveb   %d1,%a2@(119)
    clrl    %d2
    jmp     0x40137574
1:  clrb    %a2@(119)
    jmp     0x40137566

| replaces `moveq #6,%d0 ; cmpl %d3,%d0 ; beqs` (RND), just before the `lea` of the
| waveform table that lfowaves repoints. d2 = the phase about to be read (before B's x 50);
| d1 is live and kept; d0 must be 6 again on return (stock then sets only its low byte, 50)
lfb_wave:
    moveq   #6,%d0                  | replayed: RND goes its own way
    cmpl    %d3,%d0
    beqs    8f
    movel   %d1,%sp@-
    moveb   %a2@(119),%d0
    extbl   %d0
    beqs    9f
    swap    %d0
    clrw    %d0                     | (a negative byte's sign bits would otherwise ride in)
    lsll    #8,%d0
    movel   #{B_CYCLE},%d1
    macl    %d1,%d0,%acc0
    movclrl %acc0,%d0
    tstl    %d0                     | the sum stays within one cycle either way: phase + point
    bmis    1f                      | reaches 2.76e9 on the instrument, past a signed long
    subl    %d1,%d0                 | point >= 0: add (point - cycle), in -cycle .. 0
1:  addl    %d0,%d2
    bpls    2f
    addl    %d1,%d2                 | below 0: a cycle back
2:  moveq   #3,%d0
    cmpl    %d0,%d4
    blts    3f
    moveq   #4,%d0
    cmpl    %d0,%d4
    bles    9f
3:  movel   %d2,%a2@(80)
    clrb    %a2@(119)
9:  movel   %sp@+,%d1
    moveq   #6,%d0
    jmp     0x401375ea              | on to stock's `moveb #50,%d0 ; lea table,%a1`
8:  jmp     0x4013761a              | RND: stock's branch target
"""

LABELS = ("lfa_trig", "lfa_wave", "lfb_trig", "lfb_wave")

# The hold: each stop-table store NOP'd, so ONE / HALF keep the value they reached instead
# of jumping to a fixed one per waveform (lfohold's finding; B's stores found 2026-10-09).
# (site, stock bytes, new bytes, what): each asserted with a neighbouring instruction, never
# a table's address, which lfowaves repoints.
HOLD = (
    (0x401378E8, bytes.fromhex("41f03c00" "25500054"), bytes.fromhex("41f03c00" "4e714e71"),
     "hold, A HALF: movel %a0@,%a2@(84) NOP'd"),
    (0x4013791C, bytes.fromhex("20713c00" "25480054"), bytes.fromhex("20713c00" "4e714e71"),
     "hold, A ONE: movel %a0,%a2@(84) NOP'd"),
    (0x401374E4, bytes.fromhex("2ab03c00" "16bc0001"), bytes.fromhex("4e714e71" "16bc0001"),
     "hold, B HALF: movel %a0@(0,%d3:l:4),%a5@ NOP'd"),
    (0x4013751A, bytes.fromhex("22313c00" "2a81"), bytes.fromhex("22313c00" "4e71"),
     "hold, B ONE: movel %d1,%a5@ NOP'd (both of ONE's tables join here)"),
)

# (site, the stock bytes the hook replaces, the label it jumps to)
HOOKS = (
    (0x40137966, bytes.fromhex("242f0044" "203c5265c000"), "lfa_trig"),
    (0x401379EC, bytes.fromhex("203c636ba875"), "lfa_wave"),
    (0x4013755C, bytes.fromhex("716c002c" "243c01499700"), "lfb_trig"),
    (0x401375E4, bytes.fromhex("7006b0836730"), "lfb_wave"),
)

# The code the hooks rely on, asserted, not written: the instructions each hook returns to
# and the tests that make d4 the TRIG MODE and send RND past both hooks.
CONTEXT = (
    (0x40137960, bytes.fromhex("7006b0836716"), "A: RND (6) skips the trig multiply"),
    (0x40137970, bytes.fromhex("48424242a4000800a1c26002"), "A: the multiply's tail, where stock resumes"),
    (0x4013797C, bytes.fromhex("42827e01"), "A: RND's clear, then the trig's continuation (0x4013797e)"),
    (0x401378BA, bytes.fromhex("7941"), "A: mvsw %d1,%d4 -- d4 is the TRIG MODE"),
    (0x401379BA, bytes.fromhex("25420050"), "A: the phase stored at +80 before the waveform"),
    (0x401379E6, bytes.fromhex("7006b0836720"), "A: RND (6) skips the waveform read"),
    (0x401379F2, bytes.fromhex("a4000800a1c2e58a"), "A: the waveform read, where stock resumes"),
    (0x40137556, bytes.fromhex("7406b4836716"), "B: RND (6) skips the trig multiply"),
    (0x40137566, bytes.fromhex("48404240a0020800a1c260024282"), "B: the multiply's tail, RND's clear"),
    (0x40137574, bytes.fromhex("7d6c0026"), "B: the trig's continuation"),
    (0x4013749E, bytes.fromhex("7947"), "B: mvsw %d7,%d4 -- d4 is the TRIG MODE"),
    (0x401375B8, bytes.fromhex("25420050"), "B: the phase stored at +80 before the waveform"),
    (0x401375EA, bytes.fromhex("103c0032"), "B: moveb #50,%d0, where the hook returns"),
    (0x4013761A, bytes.fromhex("4a8e"), "B: RND's branch target (tstl %fp)"),
    (0x401375F4, bytes.fromhex("22713c004c002800"), "B: the waveform read"),
)


def assemble_stubs(source: str, base: int) -> tuple[bytes, dict[str, int]]:
    """Assemble once and read each label's address off a trailing table."""
    table = "\n".join(f"    .long {name}" for name in LABELS)
    blob = assemble(source + "\n    .align 2\n" + table + "\n", base=base)
    width = 4 * len(LABELS)
    addrs = struct.unpack(">%dI" % len(LABELS), blob[-width:])
    return blob[:-width], dict(zip(LABELS, addrs))


def check(content: bytes, va: int, want: bytes, why: str) -> None:
    have = bytes(content[va - BASE:va - BASE + len(want)])
    if have != want:
        raise SystemExit(f"{va:#010x}: expected {want.hex()}, found {have.hex()} "
                         f"-- not the image this build was written against ({why})")


def compose(stock: bytes, log=print) -> dict:
    """Apply the build to a stock MAIN OS. -> {content, blob, labels}."""
    if not available():
        raise SystemExit("no m68k assembler found")
    content = bytearray(stock)
    log("part 1 -- the code this relies on, asserted")
    for va, want, why in CONTEXT:
        check(content, va, want, why)
        log(f"  {va:#010x}  {want.hex():<28}  {why}")
    log(f"part 2 -- the code, from {CODE_VA:#010x}")
    payload, at = assemble_stubs(SOURCE, CODE_VA)
    blob = payload + bytes(-len(payload) % 4)
    log(f"  {len(payload)} bytes: " + ", ".join(f"{k} {v:#010x}" for k, v in at.items()))
    log("part 3 -- the hold: the stop-table stores")
    for va, stock_bytes, new, what in HOLD:
        check(content, va, stock_bytes, what)
        content[va - BASE:va - BASE + len(new)] = new
        log(f"  {va:#010x}  {stock_bytes.hex()} -> {new.hex()}  {what}")
    log("part 4 -- the hooks")
    for va, stock_bytes, label in HOOKS:
        check(content, va, stock_bytes, label)
        new = bytes.fromhex("4ef9") + struct.pack(">I", at[label])
        new += bytes.fromhex("4e71") * ((len(stock_bytes) - len(new)) // 2)
        if len(new) != len(stock_bytes):
            raise SystemExit(f"hook at {va:#010x} does not fit {len(stock_bytes)} bytes")
        content[va - BASE:va - BASE + len(new)] = new
        log(f"  {va:#010x}  {stock_bytes.hex()} -> {new.hex()}  jmp {label}")
    return {"content": bytes(content), "blob": blob, "labels": at}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", type=pathlib.Path, default=OUT)
    a = p.parse_args()
    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    if section is None:
        raise SystemExit("image has no MAIN OS section")
    built = compose(section.unpack())
    chunk = platform.area.CodeChunk(CODE_VA, built["blob"]).pack()
    content = platform.join(built["content"], [(platform.area.CODE, chunk)])
    print("part 5 -- repack")
    if a.out.exists():
        raise SystemExit(f"{a.out} exists; builds are never overwritten")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    replacement = compress(section.id, section.dest, content)
    a.out.write_bytes(fwbuild.build(firmware, {MAIN_OS: replacement}))
    print(f"  wrote {a.out} ({a.out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
