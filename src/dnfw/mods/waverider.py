"""Waverider: a sixth machine, a wavetable oscillator with two baked tables.

**Not yet on the instrument.** Milestone 5 of `docs/waverider-feasibility.md`:
the first build with modified SHARC code. Everything here passed in the
emulators (ColdFire: digikit's; DSP: digikit's SHARC runner), nothing on silicon.

## What it is

MACHINE SEL offers **WAVERIDER** after SWARMER. A Waverider track is machine
type 5 in the sound and in the frame, and WaveTone everywhere else on the
ColdFire: its SYN pages are WaveTone's, and two of their knobs drive it --

- `WAV1` is the **frame position** (POS) across the table;
- `TBL1` is the **table** (SLOT): 0 a saw that darkens to a sine, 1 the
  overtone series, partial 1 to 16.

Pitch follows the trig note. The rest of WaveTone's page (osc 2, noise, PD,
the levels) is shown and saved but not rendered.

## How it applies

Two sections, both from committed data:

- **MAIN OS (3):** `waverider_code.json`, written by
  `scripts/gen_waverider_code.py` from `dnfw.waverider.coldfire` (the list,
  the names, the permission rows, the WaveTone clone). Every edit's stock
  bytes are checked first. Four clean in-image caves, nothing appended.
- **The DSP boot stream (7):** `dnfw.waverider.dsp.section7`, from the
  committed SHARC objects. It refuses a section 7 that is not stock.
- **Its own SYN pages (Milestone 7):** `dnfw.waverider.pages`, one platform `CODE`
  chunk in RAM (`dnfw.mods.platform`): a Waverider track shows two pages of its own,
  labelled TUNE / POS / TBL where they work and empty where they do not yet.
- **The hook bus (`dnfw.mods.bus`):** the mod adds one machine to the machine count,
  so the platform writes the six machine-type bounds; its slot lookup is a handler of
  `ev_param_slot`, and its MIDI CC and NRPN maps handlers of `ev_param_cc` and
  `ev_param_nrpn` (`docs/waverider-midi.md`); and its group getter hook records the instructions it replays, so
  lfo4's parameter bound lands in the copy. This is why it combines with fxmod and lfo4.

## A sound or project saved with a Waverider track

Saved as machine type 5 by the stock SAVE. This build keeps 5 on LOAD; stock
firmware (and any build without this mod) loads it as **FM Tone**, the stock
LOAD bound's own fallback (`0x400dd286`), with its parameters as they were.
"""

from __future__ import annotations

import json
import pathlib

from . import RAM, Extent, ModError, Result, bus, platform
from ..image import bootstream
from ..waverider import dsp

ID = "waverider"
NAME = "Waverider, a sixth machine"
SUMMARY = ("A wavetable machine, WAVERIDER in MACHINE SEL: WAV1 sweeps the frame, "
           "TBL1 picks one of two baked tables. First build with modified DSP code.")
DEVICE = 0x15                      # Digitone II
MAIN_OS, DSP_STREAM = 3, 7
BASE = 0x40000400
SPEC = json.loads((pathlib.Path(__file__).with_name("waverider_code.json")).read_text())


# The group getter's hook replays its two stock instructions unchanged (pages.wr_group).
DESTGROUP_SITE, DESTGROUP_DISPLACED = 0x400DBCE8, 10


def extents(firmware=None, area_length: int = 0, stream_length: int = 0) -> list[Extent]:
    out = [Extent(MAIN_OS, e["va"] - BASE, len(e["new"]) // 2, e["what"],
                  displaced=e["va"] == DESTGROUP_SITE) for e in SPEC["edits"]]
    out += platform.extents(area_length)
    stream = None
    if firmware is not None:
        section = firmware.container.find(DSP_STREAM)
        stream = section.unpack() if section is not None else None
    if stream is None or dsp.LOADMAP:
        # Nothing to map the sites into, or the load-map diagnostic build, which patches
        # more of the stream (waverider.loadmap): the whole boot stream.
        out.append(Extent(DSP_STREAM, 0, 836_956, "the DSP boot stream, rebuilt"))
        return out
    # The boot stream is rebuilt: Waverider's blocks go in before the final block, so the
    # final block and everything after it moves, and six runs of stock code are written
    # over (dsp.site_loads). Nothing else in section 7 changes, the transient bank among
    # it, so dnfw.mods.transients combines with this mod (owner, 2026-10-23).
    for what, load, length in dsp.site_loads():
        out += [Extent(DSP_STREAM, at, n, f"section 7: {what}")
                for at, n in bootstream.spans(stream, load, length) if at is not None]
    final = bootstream.walk(stream).final.offset
    # stream_length: section 7 as rebuilt, longer than stock by Waverider's blocks
    out.append(Extent(DSP_STREAM, final, max(stream_length, len(stream)) - final,
                      "section 7: Waverider's blocks, inserted before the final block, and "
                      "the final block after them"))
    return out


# The wave spans (`wr_spans`, dnfw.waverider.wave) are signed sample bytes, and any
# four in a row can read as an address above BSS: 2026-10-01, `46 d6 a7 12` inside
# them did, once the page code before them grew. They are data by construction, so
# every word place inside them is declared not to hold an address; the code around
# them is still checked.
#
# Three more places in the code, each disassembled in the applied chunk (2026-10-11); the
# places move whenever the code before them does, so a change to a chunk needs them
# checked again:
#  - two instructions read as one word: `notl %d3 ; andl %d3,%d2` (46 83 c4 83), and
#    `notl %d0 ; tstw %d0` (46 80 4a 40);
#  - `addil #0x469fe800,%d0` (06 80 46 9f e8 00): the pool's display spans at 0x46a00000
#    less WR_TABLES (4) tables of 1,536 bytes. `WR_POOL_SPANS[tbl - WR_TABLES]` folds the
#    subtraction into the base, so the value is an address, biased 0x1800 below the
#    declared range and past the checker's 64-byte slack. Nothing is read at it.
NOT_RAM = tuple(range(SPEC["layout"]["wr_spans"] & ~1, SPEC["layout"]["wr_spans_end"], 2))

# Word places that read as an address above BSS and are not one, each disassembled on
# 2026-10-16 (the label texts read again after the bus moved them 10 bytes down, 4 bytes up when SMT1/SMT2
# became SLW1/SLW2, 8 bytes up when TYPE lost Formant and Comb, 40 bytes down in 0.3.1 when SLW1/SLW2 got their own
# range entries, and 4 bytes down when TYPE gained Formant, 2026-10-17: the words read Nois, Fold and Form) (objdump -m m68k:cfv4e over the two CODE chunks). A change to the code moves
# them, so the check flags the new places again and they are read afresh.
NOT_RAM += (
    # 2026-10-18, MIDI CC: the assembly grew 730 bytes and the renderer moved 0x400 up; knob
    # travel: 92 bytes more. Read again in the applied chunk. 2026-10-30, 0.3.8: FSRC's labels moved
    # Nois and Fold 0x18 up (were 0x4670B2F8 and 0x4670B316)
    0x4670B310,              # "Noise Colour": the label text "Nois" (the uncached window's 0x4e...)
    0x4670B32E,              # "ave Fold": the label text "Fold"
    # "Formant" (TYPE's fourth value) starts at 0x4670B4A3 in 0.3.8, an odd place: no aligned word reads "Form"
    0x4670B94A,              # notl %d3 ; andl %d3,%d2
    0x4670BBDA,              # addil #0x469fe800,%d0: the pool spans' base 0x46a00000 less two
                             # 3072 B entries, indexed by the table number (2 and up), declared
    0x467F1B52, 0x467F27D4, 0x467F2D22,   # movel #0x467f46xx,(a0) ; clrl d(a0): read 2 bytes late
    0x467F326A, 0x467F3270, 0x467F327A, 0x467F3280, 0x467F32CC, 0x467F32DC,
                             # lea / movel of 0x467f46xx and 0x467f8e48: read 2 bytes late
    0x467F4006,              # notl %d0 ; tstw %d0
    0x467F4720, 0x467F472C, 0x467F4730, 0x467F4734,
                             # a table of 0x467f46xx pointers: read 2 bytes late
) + (
    0x4670C8E2, 0x4670CBCE, 0x467F3180)


def ram() -> list[Extent]:
    chunk, drive = SPEC["chunk"], SPEC["drive"]
    return [Extent(RAM, chunk["load"], len(bytes.fromhex(chunk["code"])),
                   "Waverider's SYN pages: code, descriptors, labels (M7)"),
            Extent(RAM, drive["load"], len(bytes.fromhex(drive["code"])),
                   "Waverider's +Drive chunk: the /waverider route, the table loader, the pool"),
            Extent(RAM, drive["spans"]["va"], drive["spans"]["bytes"],
                   "the pool tables' display spans (127 x 16 frames x 96 columns)"),
            Extent(RAM, SPEC["layout"]["set_ctx"], 4,
                   "the parameter setter's mark: the machine type of the track being set (MIDI)")]


def _main_os(original: bytes) -> bytes:
    if len(original) < SPEC["stock_length"]:
        raise ModError(f"MAIN OS is {len(original):,} B, shorter than "
                       f"{SPEC['stock_length']:,}: not Digitone II 1.11")
    for g in SPEC["guards"]:
        want = bytes.fromhex(g["bytes"])
        at = g["va"] - BASE
        if original[at:at + len(want)] != want:
            raise ModError(f"0x{g['va']:08x} ({g['what']}) is not stock; this mod is "
                           "for unmodified Digitone II 1.11")
    content = bytearray(original)
    for e in SPEC["edits"]:
        old, new = bytes.fromhex(e["stock"]), bytes.fromhex(e["new"])
        at = e["va"] - BASE
        if bytes(content[at:at + len(old)]) != old:
            raise ModError(f"0x{e['va']:08x} ({e['what']}) is not stock; this mod is for "
                           "unmodified Digitone II 1.11, or another mod already wrote there")
        content[at:at + len(new)] = new
    return bytes(content)


def apply(firmware) -> Result:
    cf = firmware.container.find(MAIN_OS)
    ds = firmware.container.find(DSP_STREAM)
    if cf is None or ds is None:
        raise ModError("image has no MAIN OS or no DSP boot stream")
    main_os, stream = cf.unpack(), ds.unpack()
    if main_os is None or stream is None:
        raise ModError("MAIN OS or the DSP boot stream did not depack")
    main_os, others = platform.split(main_os)
    try:
        section7 = dsp.section7(stream)
    except dsp.DspError as exc:
        raise ModError(f"the DSP boot stream: {exc}") from exc
    chunk, drive = SPEC["chunk"], SPEC["drive"]
    code = platform.area.CodeChunk(chunk["load"], bytes.fromhex(chunk["code"])).pack()
    dcode = platform.area.CodeChunk(drive["load"], bytes.fromhex(drive["code"])).pack()
    layout = SPEC["layout"]
    content = platform.join(_main_os(main_os), others + [
        (platform.area.CODE, code), (platform.area.CODE, dcode),
        platform.displace(DESTGROUP_SITE, DESTGROUP_DISPLACED, layout["wr_group_displaced"]),
        bus.subscribe(b"PSLT", layout["wr_slot_id"]),
        bus.subscribe(b"PCCI", layout["wr_cc_id"]),
        bus.subscribe(b"PNRI", layout["wr_nrpn_id"]),
        bus.contribute(b"MACH", 1)])
    area_length = len(content) - platform.STOCK_LENGTH
    return Result(payloads={MAIN_OS: content, DSP_STREAM: section7},
                  extents=extents(firmware, area_length, len(section7)),
                  notes=[f"MACHINE SEL offers {SPEC['names'][0].upper()} after SWARMER "
                         f"(type {SPEC['new_type']}; WaveTone's pages)",
                         f"{len(SPEC['edits'])} edits in section 3, two CODE chunks in the "
                         f"platform's area; section 7 {len(stream):,} -> {len(section7):,} B"])
