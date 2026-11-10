"""LFO4: the four steps become one build, and the engine pulls from the table.

    python scripts/build_lfo4_bridge.py

Steps 1-3 each proved one thing and were separate images. This is the first
build where they are the same firmware:

| from | what it brings |
|---|---|
| step 0 | the startup loader and the `CODE` chunk that carries our C |
| steps 1-2 | the extension table, its carry through `memcpy` / `memset`, and save / load through the reserved p-lock ids |
| step 3 | a fourth LFO in both evaluators, reading a **per-track** row |
| here | `csrc/lfo4/bridge.c` -- the tick pulls each track's row from the table |

**The tick pulls; nothing pushes.** `a4_top` and `b_top` already run once per
track with the index in hand, so each now calls `lfo4_refresh(track)`, which
returns that track's row address after making it current. It copies only when
the track's sound changed or `ext_generation` moved, so the common case is two
loads and two compares.

The two stubs must preserve `d0`/`d1`/`a0`/`a1` across that call: they sit
inside evaluator code that never expected one. `%a5` (A's track index) is
callee-saved by the compiler's own convention, so it survives.
"""

from __future__ import annotations

import json
import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

import build_lfo4_tick as v6a                             # noqa: E402
import build_lfo4_tick7 as tick7                          # noqa: E402
from build_lfo4_ext import CODE_VA, SITES                 # noqa: E402
from dnfw.cli.files import read_image                      # noqa: E402
from dnfw.container.section import compress                # noqa: E402
from dnfw.firmware import build as fwbuild                 # noqa: E402
from dnfw.firmware.load import load                        # noqa: E402
from dnfw.patch import area, cbuild, loader                # noqa: E402

STOCK = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
MAIN_OS, BASE = 3, 0x40000400
SRC = ROOT / "csrc"
OUT = ROOT / "out/lfo4-bridge"
SYX = ROOT / "00_Resources/02_Builds/lfo4-bridge_DN2_1.11.syx"

# `setter.c` is here because `hooks.S` is shared and its `lfo4_set_stub`
# refers to it. This build does not patch that site, so `--gc-sections`
# drops both -- but the link needs the symbol to exist.
SOURCES = ("init.c", "ext.c", "carry.c", "store.c", "bridge.c", "setter.c", "hooks.S")
ENTRIES = ["lfo4_init", "ext_get", "ext_set", "ext_drop", "lfo4_refresh", "lfo4_sound_of",
           "lfo4_row_for_block", "lfo4_on_frame", "lfo4_wake", "lfo4_now", "lfo4_held", "lfo4_awake",
           "lfo4_runs", "lfo4_wakes", "lfo4_owner_raw", "lfo4_seen_generation", "lfo4_refreshes",
           "ext_generation", "lfo4_fx", "lfo4_fx_generation", "lfo4_sleep",
           "lfo4_send_guard", "lfo4_guard_holds", "lfo4_guard_carried",
           *(s[2] for s in SITES)]

# Each stub asks the C for its row instead of computing one from a fixed table.
# `lfo4_refresh` returns the row address; the loop wants that address minus the
# displacement its body reads through.
PULL = """    lea     -16(%sp),%sp
    movem.l %d0-%d1/%a0-%a1,(%sp)
    move.l  {mask},%sp@-
    move.l  {index},%sp@-
    jsr     {refresh:#010x}
    addq.l  #8,%sp
    movea.l %d0,%a4
    lea     %a4@(-{bias}),%a4
    movem.l (%sp),%d0-%d1/%a0-%a1
    lea     16(%sp),%sp"""


def cave_source(table_va: int, refresh: int, for_block: int = 0) -> str:
    """tick7's stubs, with both parameter loads replaced by a call to the C.

    **Evaluator A passes a pointer, not an index.** `%a5` was named "the track
    index" in a comment nobody measured; it is zeroed at the evaluator's entry
    and only advanced by `outer`, which does not run on this path, so it was 0
    on every track and LFO4 read one fixed row for months. `%sp@(56)` is the
    mirror block pointer the stock code uses for LFO1-3 -- `outer` advances it
    by 202 per track and `a4_bottom` restores `%a4` from it -- and it sits 16
    pointer the stock code uses for LFO1-3, and the displaced instruction was
    `lea %a4@(-34),%a4` -- so **`%a4` already holds it** when the stub runs.
    Ghidra's decompilation of `0x40137726` confirms it: `local_18 = param_1 +
    0x22` advances 202 per track, and `iVar12 = local_18 - 0x22` is the very
    instruction replaced here. A register, not a stack slot, so no frame layout
    can be got wrong -- which two earlier attempts both did.
    """
    source = v6a.cave_source(table_va)
    # stock `%sp@(88)` is the enable mask. The cave is entered by `jsr`, so it
    # sits 4 bytes lower, and 16 lower again once the stub saves registers:
    # 88 + 4 + 16 = 108. Two earlier attempts used +16 and forgot the `jsr`.
    # **Pass the stack pointer, not a guessed slot.** Three different
    # displacements have now been guessed at this frame and all three were
    # wrong; the last read a constant zero on all sixteen tracks while the
    # signals beside it carried correctly. So hand the C the frame pointer
    # itself and let it walk the frame over successive telemetry bursts --
    # one flash maps what four could not.
    sites = ((68, "%a4", "%sp", for_block or refresh),
             (34, "%d0", "#0", refresh))
    for bias, index, mask, callee in sites:
        line = f"    lea     {table_va - bias:#010x},%a4"
        if source.count(line) != 1:
            raise SystemExit(f"expected one {line.strip()!r} in the stubs, found {source.count(line)}")
        source = source.replace(line, PULL.format(index=index, mask=mask, refresh=callee, bias=bias))
    return source


# **An idle LFO4 costs the frame nothing (2026-09-27).** The owner's bisect put
# the save-while-playing stutter on lfo4 alone, and `scripts/emu_mod_cost.py`
# measured why: every track ran a fourth LFO iteration and a bridge call on
# every frame, LFO4 in use or not -- evaluator A 9,216 -> 13,696 instructions.
#
# Both evaluators count down from the top LFO, and the fourth is the first
# iteration. So when there is nothing for it to do, the top stub starts the
# loop where stock does -- three iterations, at LFO3's records -- and the
# fourth never runs:
#
# - **the table is empty** (`ext_live == 0`): no sound has an LFO4, so every
#   row would be the default row, whose DEST is 0. Nothing is called at all;
# - **this track's row has DEST 0**: the bridge still refreshes it (that is how
#   the stub learns DEST), but the iteration is skipped. DEST 0 is the LFOs'
#   no-destination sink, so the only thing a skipped iteration would have done
#   is write slot 0 and advance LFO4's own phase.
#
# With a destination set, nothing changes: the same call, the same four
# iterations. What an idle LFO4 loses is only its phase and fade advancing
# while it has nowhere to go, so a free-running LFO4 resumes from where it
# paused rather than from where it would have been.
#
# The skip leaves every register as stock's own entry would: `%a4` the mirror
# base, `%a2`/`%a3` (and B's `%a5`) one 40-byte record lower, and the counter 2,
# so `a4_bottom`'s "counter 2 -> back to the mirror" case never fires and its
# plain `lea %a4@(-16)` does exactly what stock's did.
# **The frame's cost with LFO4 in use (2026-11-05).** On the owner's project the fourth LFO
# took the audio interrupt from a 97 % peak to 118 %: late frames, lost notes, voices stuck at
# STOP. Evaluator A was 7,920 instructions a frame in stock, 9,302 with an entry and no
# destination (69 a voice in the call below) and 11,751 with LFO4 on every voice (153 more a
# voice). So this asks the C only when the voice's sound or the table has changed, and a voice
# with no note and no release left starts where stock does (`csrc/lfo4/bridge.c`). The evaluator
# keeps the voice in `%a5`. At this site d0, a0 and a1 are free (the stock code loads them
# next) and d1 holds the loop counter; `%d5` is the voice's bit of the frame's LFO trig mask.
A_TOP_IDLE = """a4_top:
    tst.l   {ext_live:#010x}
    beq     9f                      | no LFO4 anywhere
    move.l  %a5,%d0
    bne.s   1f
    addq.l  #1,{now:#010x}          | once a frame, on voice 0
    move.l  {generation:#010x},%d0
    cmp.l   {fx_gen:#010x},%d0
    bne.s   2f                      | the table changed: the C reads it again
    move.l  {masks:#010x},%d0       | the note masks of the frame the last interrupt built
    bne.s   2f
    tst.b   {now_low:#010x}         | every 256th frame
    bne.s   1f
2:  move.l  %d1,%sp@-
    move.l  {masks:#010x},%d0
    move.l  %d0,%sp@-
    jsr     {frame:#010x}
    addq.l  #4,%sp
    move.l  %sp@+,%d1
1:  tst.b   {fx:#010x}
    bne.s   5f                      | an FX destination somewhere: every voice, as fix2
    lea     {awake:#010x},%a0
    tst.b   %a0@(0,%a5:l)
    bne.s   5f
    tst.l   %d5
    beq     9f                      | asleep and no trig: the one test fix3 leaves (bridge.c)
5:  lea     {raw:#010x},%a1
    movea.l %a1@(0,%a5:l:4),%a1
    lea     {voices:#010x},%a0
    cmpa.l  %a0@(0,%a5:l:4),%a1
    bne.s   3f
    lea     {gens:#010x},%a1
    movea.l %a1@(0,%a5:l:4),%a1
    cmpa.l  {generation:#010x},%a1
    bne.s   3f
    addq.l  #1,{refreshes:#010x}
    move.l  %a5,%d0
    lsl.l   #4,%d0
    lea     {rows:#010x},%a1
    adda.l  %d0,%a1
    bra.s   4f
3:
{pull}
    lea     %a4@(68),%a1
    movea.l %sp@(56),%a4            | stock %sp@(52): the mirror block pointer
4:  mvs.b   %a1@(6),%d0             | the row's DEST (row + 6)
    beq.s   8f
    cmpi.l  #100,%d0
    bgt.s   6f                      | an FX destination: no note needed
    lea     {awake:#010x},%a0
    tst.b   %a0@(0,%a5:l)
    bne.s   6f
    tst.l   %d5
    beq.s   9f                      | asleep, and no trig
    move.l  %d1,%sp@-
    move.l  %a1,%sp@-
    move.l  %a5,%sp@-
    jsr     {wake:#010x}
    addq.l  #4,%sp
    movea.l %sp@+,%a1
    move.l  %sp@+,%d1
6:  addq.l  #1,{runs:#010x}
    lea     %a1@(-68),%a4
    lea     %a3@(116),%a3           | four iterations, the fourth LFO4
    rts
8:  lea     {awake:#010x},%a0       | no destination: an awake voice sleeps at once
    tst.b   %a0@(0,%a5:l)
    beq.s   9f
    move.l  %d1,%sp@-
    move.l  %a5,%sp@-
    jsr     {sleep:#010x}
    addq.l  #4,%sp
    move.l  %sp@+,%d1
9:  lea     %a4@(-34),%a4           | as stock
    lea     %a3@(76),%a3            | 116 - 40: LFO3's record, where stock starts
    lea     %a2@(-40),%a2
    moveq   #2,%d1                  | three iterations, as stock
    rts
"""

B_TOP_IDLE = """b_top:
    tst.l   {ext_live:#010x}
    beq.s   9f
{pull}
    tst.b   %a4@(40)                | the row's DEST (row + 6, a4 = row - 34)
    bne.s   7f
    movea.l %sp@(60),%a4            | stock %sp@(56): the real %a4
9:  lea     %a5@(-40),%a5           | LFO3's records, where stock starts
    lea     %a2@(-40),%a2
    moveq   #2,%d2                  | three iterations, as stock
7:  lea     %a5@(36),%a3
    addq.l  #4,%a5
    move.l  %d2,%sp@(52)
    move.l  %a0,%sp@(56)
    rts
"""


FRAME_NOTE_MASKS = 0x80005E82    # the frame's note-on mask, then its note-off mask (0x40027498)
VOICE_SOUND = 0x800052A8         # DN2_VOICE_SOUND


# `outer` displaces 28 bytes, and the hook pads them with eleven `nop`s that run
# on every track of every frame after the stub returns. On the ColdFire a
# `nop` is not free: it waits for the pipeline to drain. So the idle build
# branches over them: `jsr outer ; bra.s` to where the displaced block ended.
OUTER_HOOK, OUTER_END = 0x40137AFC, 0x40137B18


def skip_padding(content: bytearray) -> None:
    at = OUTER_HOOK + 6 - BASE
    pad = bytes(content[at:OUTER_END - BASE])
    if pad != b"Nq" * (len(pad) // 2) or len(pad) != 22:
        raise SystemExit(f"outer's padding is not eleven nops: {pad.hex()}")
    disp = OUTER_END - (OUTER_HOOK + 6 + 2)
    content[at:at + 2] = bytes([0x60, disp])
    print(f"  {OUTER_HOOK + 6:#010x}  eleven nops -> bra.s {OUTER_END:#010x}")


def idle_skip(source: str, code) -> str:
    """Replace `a4_top` and `b_top` with the versions that skip an idle LFO4."""
    import re

    a_top = dict(ext_live=code["ext_live"], now=code["lfo4_now"], now_low=code["lfo4_now"] + 3,
                 masks=FRAME_NOTE_MASKS, frame=code["lfo4_on_frame"], raw=code["lfo4_owner_raw"],
                 voices=VOICE_SOUND, gens=code["lfo4_seen_generation"],
                 generation=code["ext_generation"], refreshes=code["lfo4_refreshes"],
                 rows=code["lfo4_rows"], awake=code["lfo4_awake"], wake=code["lfo4_wake"],
                 runs=code["lfo4_runs"], fx=code["lfo4_fx"], fx_gen=code["lfo4_fx_generation"],
                 sleep=code["lfo4_sleep"])
    for label, body, bias, index, mask, callee, values in (
            ("a4_top", A_TOP_IDLE, 68, "%a4", "%sp", code["lfo4_row_for_block"], a_top),
            ("b_top", B_TOP_IDLE, 34, "%d0", "#0", code["lfo4_refresh"], dict(ext_live=code["ext_live"]))):
        pull = PULL.format(index=index, mask=mask, refresh=callee, bias=bias)
        pattern = re.compile(rf"^{label}:\n.*?^    rts\n", re.S | re.M)
        if len(pattern.findall(source)) != 1:
            raise SystemExit(f"expected one {label} stub to replace")
        source = pattern.sub(lambda _: body.format(pull=pull, **values), source)
    return source


def main(sources=SOURCES, entries=ENTRIES, out=OUT, syx=SYX, extra=(), chunks=None,
         defines=None, include=(), exports=(), idle=False) -> int:
    """Build it. `extra` are further site patches, each `f(content, code)`.

    The arguments exist so a build that is *this one plus a site* -- step 4's
    setter divert is the first -- composes instead of copying two hundred lines
    that would then drift apart.

    `chunks`, if given, is `f(stock) -> [(id, data)]`: further area chunks to
    append beside the C. Step 4b's relocated parameter table is one, and it is
    built from the stock image rather than compiled, which is why the hook
    takes the image and runs before the loader is installed.

    `include` adds header directories (a generated header, for one), and
    `exports` adds symbol prefixes to `symbols.json` beside `lfo4_` and `ext_`
    -- Waverider Milestone 0 is the first build to need both.

    `idle` builds the evaluator stubs that skip an idle LFO4 (`idle_skip`);
    the release sets it, and every diagnostic build before it did not.
    """
    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    stock = section.unpack()

    # The rows are a C array now, so the address comes *out* of the build
    # instead of being told to it -- and the cave goes back to holding nothing
    # but stubs, which is all a gap in someone else's code should ever hold.
    code = cbuild.build([(SRC / name) if "/" in name else (SRC / "lfo4" / name) for name in sources], base=CODE_VA,
                        include=[SRC / "include", SRC / "telemetry", *include],
                        entries=entries + ["lfo4_rows"],
                        defines=defines)
    table_va = code["lfo4_rows"]
    chunk = area.CodeChunk(CODE_VA, code.image, code.bss, code["lfo4_init"]).pack()
    content = loader.install(stock, [(area.CODE, chunk), *(chunks(stock) if chunks else ())])
    print(f"part 1 -- C: {len(code.image)} B at {CODE_VA:#010x}, {code.bss:,} B of state; "
          f"rows at {table_va:#010x}; the live container is read from "
          f"0x800052a0, not built in")

    print("part 2 -- the four C hook sites")
    for name, va, stub, replay, n in SITES:
        at = va - BASE
        if bytes(content[at:at + n]) != code.image[code[replay] - CODE_VA:code[replay] - CODE_VA + n]:
            raise SystemExit(f"{name}: the stub does not replay what it displaces")
        jump = b"\x4e\xf9" + struct.pack(">I", code[stub])
        content[at:at + n] = jump + b"\x4e\x71" * ((n - len(jump)) // 2)
        print(f"  {va:#010x}  {name}")

    print("part 3 -- the engine, from step 3")
    stub_va = v6a.CAVE
    v6a.require_zero(content, v6a.CAVE, v6a.CAVE_CAP, "cave region")
    stubs = cave_source(table_va, code["lfo4_refresh"], code["lfo4_row_for_block"])
    if idle:
        stubs = idle_skip(stubs, code)
    payload, offsets = v6a.assemble_stubs(stubs, stub_va)
    if len(payload) > v6a.CAVE_CAP:
        raise SystemExit(f"cave overflows: {len(payload)} > {v6a.CAVE_CAP}")
    content[stub_va - BASE:stub_va - BASE + len(payload)] = payload
    print(f"  rows {table_va:#010x} (in our BSS), stubs {len(payload)} B, "
          f"{v6a.CAVE_CAP - len(payload)} B of cave left")
    for va, was, new, why in v6a.edits(table_va):
        v6a.poke(content, va, was, new, why)
    for va, was, kind, label in v6a.hooks(table_va, offsets):
        op = b"\x4e\xb9" if kind == "jsr" else b"\x4e\xf9"
        new = op + v6a.be32(offsets[label])
        new += b"\x4e\x71" * ((len(was) - len(new)) // 2)
        v6a.poke(content, va, was, new, f"{kind} -> {label}")
    if idle:
        skip_padding(content)

    for patch in extra:
        patch(content, code)

    print("part 4 -- write")
    out.mkdir(parents=True, exist_ok=True)
    (out / "section_3_MAIN_OS.bin").write_bytes(bytes(content))
    wanted = ("lfo4_", "ext_", *exports)
    symbols = {k: v for k, v in code.symbols.items() if k.startswith(wanted)}
    symbols["lfo4_rows"] = table_va
    symbols["dnfw_boot"] = loader.build()["dnfw_boot"]
    (out / "symbols.json").write_text(
        json.dumps({k: f"0x{v:08x}" for k, v in sorted(symbols.items())}, indent=1) + "\n", newline="\n")
    # Which of those are code. The boot gate reports what never ran, and a
    # counter in that list is noise: `lfo4-table`'s first gate named 24
    # symbols as unexercised routines and 15 of them were variables, which
    # buries the ones that matter.
    routines = {k: v for k, v in code.routines().items() if k.startswith(wanted)}
    routines["dnfw_boot"] = symbols["dnfw_boot"]
    (out / "routines.json").write_text(
        json.dumps({k: f"0x{v:08x}" for k, v in sorted(routines.items())}, indent=1) + "\n", newline="\n")
    syx.parent.mkdir(parents=True, exist_ok=True)
    syx.write_bytes(fwbuild.build(firmware, {MAIN_OS: compress(section.id, section.dest, bytes(content))}))
    print(f"  {syx.name}, MAIN OS {len(content):,} B (+{len(content) - len(stock)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
