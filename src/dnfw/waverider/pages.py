"""Waverider's own SYN pages (Milestone 7): the page count, the page descriptors and the
knob labels a Waverider track shows. `docs/waverider-m7-pages.md` has the evidence.

A Waverider track is WaveTone to most of the UI (`coldfire`, M5): the SYN page readers
are asked about type 1, whatever the track. So these routines do not trust the type
they are handed. They ask whether the **active track** (the byte `0x42431a6c`, whose
sound is `[0x800052a0] + 52 + 1163 * t`) is a Waverider (`sound+0xDE` = 5), and only
then answer with Waverider's pages and labels:

- `wr_count`, entered by `jsr` from the page-count reader `0x400c24d2` (in place of M5's
  `canon_arg` there): 2 pages; otherwise exactly what `canon_arg` does.
- `wr_page`, entered by `jsr` from the page reader `0x400c24ee` at `0x400c24f2` (in
  place of M5's `canon_page`): our descriptor for pages 0-1, the stock empty page past
  them; otherwise exactly what `canon_page` does.
- `wr_icons`, entered by `jsr` from the SYN page draw at `0x4001821e`: on a Waverider
  track, WaveTone's oscillator icons (drawn at B and F from `WAV1`/`TBL1` and
  `WAV2`/`TBL2` after the grid of page id 7) are skipped; otherwise the stock page-id test.
- `wr_grid`, entered by `jsr` from the SYN page draw at `0x40018214` (in place of its
  call to the grid `0x40017428`): a Waverider track gets its own page, drawn by
  `wr_page_draw` (`csrc/waverider/page.c`, M8.1); every other track the stock grid.
- `wr_label`, entered by `jsr` from the SYN page's label fetch at `0x40064622` (in place
  of `jsr getShortName`): the record ids Waverider relabels get our labels; every
  other id, and every other track, goes to the stock `getShortName` `0x400372da`
  unchanged (a tail jump, so the stack is the caller's own).
- `wr_long`, entered by `jsr` from inside the long-name getter `0x400365c8` at
  `0x400365f2` (in place of its push of the record's long name and of d2): our long
  name for the ids Waverider renames, on a Waverider track; the record's otherwise.
  The header asks for it through the parameter set's display name (vtable +88,
  `0x40036612`) while a knob turns (emulator, `--stack-at 0x400365c8`).

The labels and the page layout are the owner's (2026-10-01), from the Waverider mockup,
with our own names:

    page 1, OSC 1   A TUNE  B LEV   C POS   D TBL   E RATE  F MLEV  G MPOS  H MOVE
    page 2, OSC 2   A DETN  B LEV   C POS   D TBL   E RATE  F MLEV  G MPOS  H MOVE

MLEV and MPOS were F and G the other way round until 2026-10-07 (owner: each mod control
under the control it moves, MLEV under LEV, MPOS under POS).

Only TUNE, POS and TBL work in M7 (the loop reads TUN1, WAV1 and TBL1), and LEV from M9a
(LEV1, the reader's gain); page 2's DETN, LEV, POS and TBL from M9b (osc 2: TUN2, LEV2,
WAV2, TBL2). Every other place is an empty entry (0), drawn as "-", until its milestone.

The code, the descriptors and the strings run from RAM as one platform `CODE` chunk at
`LOAD` (`dnfw.mods.platform`): the caves Waverider already uses are full.

The page is drawn in C (`csrc/waverider/page.c`), the way Tonverk's Wavefinder page
is laid out: the wave across the middle, A..D in a slim strip above it, E..H below.
That code is compiled and linked into the same chunk at `C_LOAD`, and reads this
module's control table and `wave`'s spans from a generated header (`c_header`).

This module is pure: it builds the source; `coldfire.compose` assembles and places it.
"""

from __future__ import annotations

from .live import SHAPE_TYPES as LIVE_SHAPE_TYPES
from .live import (DCLK_DEFAULT, MOVE_SHAPES, SUB_OCTAVES, SUB_WAVES, SYNC_INDEX, SYNC_NOTES,
                   dclk_names, smth_names)

LOAD = 0x4670A000                 # RAM above BSS (0x466b74d0), clear of every declared range (docs/mods-compatibility.md): 0x4670C000 until pages 3 and 4, when the renderer outgrew the 16 KB to C_END; bootscreen's stamp ends at 0x46708140
C_LOAD = LOAD + 0x1200            # the C page renderer, after this assembly (0x1000 until the destination list's numbers, 0x400 until M10a, 0x500 until M10b, 0x600 until M10b-4, 0x700 until M10b-2, 0x800 until the TBL turn, 0x900 until pages 3 and 4, 0xC00 until the shape page: 3,484 B)
C_END = 0x46710000                # the platform runtime starts here
ACTIVE_TRACK = 0x42431A6C         # byte: the UI's active track, 0..15
KIT_POINTER = 0x800052A0          # the live kit; sound t at + 52 + 1163 t
SOUND_BASE, SOUND_STRIDE, SOUND_TYPE = 52, 1163, 0xDE
NEW_TYPE, CLONE = 5, 1
GET_SHORT_NAME = 0x400372DA
EMPTY_PAGE = 0x42432BD4           # the readers' own empty-page fallback
TAG = 10                          # the tag every stock SYN descriptor ends with

# Waverider's own page titles (not drawn; the header shows the subtitle and the page
# number). Our own strings, so no descriptor points into WaveTone's. The waveform icons
# a Waverider page first showed at B and F did not come from the titles: they are the
# SYN page draw's WaveTone OSC-page overlay (page id 7), which `wr_icons` skips.
TITLES = ("WR 1", "WR 2", "WR 3", "WR 4", "WR 5")
SUBTITLE = "Waverider"             # where WaveTone's say "WaveTone"

SUBNOISE = (227, 228, 229, 230, 231, 232, 233, 234)    # SUB OCT WAVE SRC / NOIS TYPE COLR DEC
SUBNOISE_LABELS = dict(zip(SUBNOISE, ("SUB", "OCT", "WAVE", "SRC", "NOIS", "TYPE", "COLR", "DEC")))
SUBNOISE_SLOT0 = 50                # their sound slots: 50..57 (the record table's slot field)
SUBNOISE_PLAIN = (227, 231)        # SUB, NOIS: 0..127 (wr_rate_fmt row 4)
SUBNOISE_COLR = 233                # -64..+63 (row 5)
SUBNOISE_DEC = 234                 # 0..126, Inf (row 6)

# Page 5, "Shape" (owner's option 4, 2026-10-12; docs/waverider-shape.md): four live knobs and
# one typed shaper, reserved before the sound features that fill them. The records are FM
# Tone's 208..211 and 235..237 in sound slots 58..64 (a WaveTone-type sound has none there)
# and WaveTone's master tuning 261 in slot 48, which the Waverider voice never reads
# (scripts/sharc_waverider_inert.py: the render is identical with 48, 49 and 58..64 at their
# extremes). 262 (FINE, slot 49) stays free. None of the eight reaches the sound yet.
# AMT is record 261 (WaveTone's MAST, a modulatable record) and P2 is 236 (mask 0): the amount can be
# an LFO destination, P2 and P1 cannot (owner, 2026-10-13: the AMT/P2 swap). The sound slots stay.
SHAPE = (208, 209, 210, 211, 235, 261, 237, 236)     # FOLD WARP FM NPOS / TYPE AMT P1 P2
SHAPE_LABELS = dict(zip(SHAPE, ("FOLD", "WARP", "FM", "NPOS", "TYPE", "AMT", "P1", "P2")))
SHAPE_RUNS = ((58, 208, 4), (62, 235, 3))      # (first sound slot, its record id, how many): 58..61, 62..64
SHAPE_TYPE = 235
TRIM_ID = 262                      # WaveTone's FINE (slot 49): the level trim, page 4 place D (docs/waverider-trim.md)
SHAPE_TYPES = LIVE_SHAPE_TYPES           # Off, Ring, AM (page5.asm), Formant (formant.asm); the list grows, no slot
SHAPE_PLAIN = tuple(rid for rid in SHAPE if rid != SHAPE_TYPE)   # 0..127 (wr_rate_fmt row 4)

# record id -> Waverider's label (the records stay WaveTone's: their slots are the
# frame's params 25..27, which the SHARC loop reads)
LABELS = {238: "TUNE", 241: "LEV", 239: "POS", 247: "TBL",
          242: "DETN", 245: "LEV", 243: "POS", 251: "TBL",
          # M10a: MOVE, the modulator (WaveTone records Waverider does not use)
          240: "RATE", 246: "MPOS", 252: "MLEV", 253: "MOVE",
          244: "RATE", 250: "MPOS", 256: "MLEV", 257: "MOVE",
          249: "PRST", 259: "TRIG",
          # M10b-2: SYNC, MOVE locked to the tempo (WaveTone's Osc Mod and Noise Character:
          # the two spare records whose default is 0, so a saved sound reads Off)
          248: "SYN1", 260: "SYN2",
          # DCLK (HOLD: the crossfade, 0 Off, 1..127 = 1..100 ms) and SMTH (DEC, WDTH: the
          # glide, 0 Off, the default a new sound gets since 0.3.1)
          254: "DCLK", 255: "SLW1", 258: "SLW2",       # SMT1/SMT2 until 0.1.1 (owner, 2026-10-15)
          # pages 3 and 4 (owner, 2026-10-07; docs/waverider-pages34.md): page 3 the
          # sub-oscillator and the noise, on FM Tone's records in slots 50..57, which a
          # WaveTone-type sound doesn't have (prototype: the screen only, no sound yet)
          **SUBNOISE_LABELS,
          # page 5: the shape (reserved)
          **SHAPE_LABELS,
          TRIM_ID: "TRIM"}
# record id -> the DEST cell's label where the page's own label is the same for both
# oscillators (each oscillator has its own page, so the pages cannot tell; the cell can):
# the stem and the oscillator, four characters like SYN1/SMT1. The pages keep LABELS
# (owner, 2026-10-13: "do all of them").
MINI_LABELS = {241: "LEV1", 245: "LEV2", 239: "POS1", 243: "POS2", 247: "TBL1", 251: "TBL2",
               240: "RAT1", 244: "RAT2", 246: "MPO1", 250: "MPO2", 252: "MLV1", 256: "MLV2",
               253: "MOV1", 257: "MOV2"}
# record id -> Waverider's long name, in the stock "Osc1 Waveform" style: what the
# header shows while a knob turns ("Osc1 Position=65"), and the LFO destination
# browser on a Waverider track
LONG_NAMES = {238: "Osc1 Tune", 239: "Osc1 Position", 247: "Osc1 Table",
              242: "Osc2 Detune", 243: "Osc2 Position", 251: "Osc2 Table",
              240: "Osc1 M.Rate", 246: "Osc1 M.Pos", 252: "Osc1 M.Level",
              253: "Osc1 M.Shape", 244: "Osc2 M.Rate", 250: "Osc2 M.Pos",
              256: "Osc2 M.Level", 257: "Osc2 M.Shape", 259: "Move Retrig",
              248: "Osc1 M.Sync", 260: "Osc2 M.Sync",
              254: "Declick", 255: "Osc1 POS Slew", 258: "Osc2 POS Slew",
              227: "Sub Level", 228: "Sub Octave", 229: "Sub Wave", 230: "Sub Source",
              231: "Noise Level", 232: "Noise Type", 233: "Noise Colour", 234: "Noise Decay",
              208: "Wave Fold", 209: "Phase Warp", 210: "FM Depth", 211: "Noise to Pos",
              235: "Shaper Type", 261: "Shaper Amount", 237: "Shaper P1", 236: "Shaper P2",
              TRIM_ID: "Level Trim"}

# the pages, encoders A..H; 0 is an empty place
PAGES = (
    (238, 241, 239, 247, 240, 252, 246, 253),   # OSC 1: TUNE LEV POS TBL RATE MLEV MPOS MOVE
    (242, 245, 243, 251, 244, 256, 250, 257),   # OSC 2: DETN LEV POS TBL RATE MLEV MPOS MOVE
    SUBNOISE,                                   # page 3: SUB OCT WAVE SRC / NOIS TYPE COLR DEC
    (249, 259, 254, TRIM_ID, 248, 260, 255, 258),   # page 4 (page 3 until 2026-10-07): PRST (RSET: Off/On/Random), TRIG (TYPE: 0 restart),
                                                # DCLK, TRIM (FINE, 2026-10-12); SYN1, SYN2, SMT1, SMT2 (M10b-2)
    SHAPE,                                      # page 5: FOLD WARP FM NPOS / TYPE AMT P1 P2 (reserved, 2026-10-12)
)

# M10b: the controls whose steps and value text are Waverider's own. The records stay
# WaveTone's (MOVE1 is its Noise Attack, MOVE2 the noise filter Base, TRIG the Noise
# Type), so wr_range and wr_fmt answer for them on a Waverider track only: MOVE steps
# shape by shape and the header names the shape; TRIG reads Retrig / Free.
VALUE_NAMES = {253: MOVE_SHAPES, 257: MOVE_SHAPES, 259: ("Retrig", "Free"),
               228: SUB_OCTAVES, 229: SUB_WAVES, 230: ("OSC1", "OSC2"),
               232: ("WHT", "PNK", "BRN", "DIG"),
               248: ("Off", "On"), 260: ("Off", "On"),
               SHAPE_TYPE: SHAPE_TYPES}
# record id -> (min, max, default), as the firmware's limits getter returns them
RANGES = {rid: (0, (len(names) - 1) << 8, 0) for rid, names in VALUE_NAMES.items()}
RANGES[254] = (0, 0x7F00, DCLK_DEFAULT)
# page 3's levels (prototype defaults: the sub and the noise off, COLR centred, DEC Inf)
RANGES.update({227: (0, 0x7F00, 0), 231: (0, 0x7F00, 0), 233: (0, 0x7F00, 0x4000), 234: (0, 0x7F00, 0x7F00)})   # DCLK: 3 ms for a new sound (owner, 2026-10-06)
RANGES.update({rid: (0, 0x7F00, 0) for rid in SHAPE_PLAIN})   # the shape's knobs: 0..127, off at 0
RANGES[TRIM_ID] = (0, 0x7F00, 0x4000)   # TRIM: -15..0 dB, -11 dB at the stock default (live.trim_table)
RANGES.update({rid: (0, 0x7F00, 0) for rid in (255, 258)})   # SLW1, SLW2: Off at 0 since 0.3.1 (live.smth_table)
FORMAT_S = 0x40219C2D             # "%s", the stock naming routines' format
HEAD_FORMAT = 0x40216CEE          # "%s=%s", the header's name and value (used once, at 0x40067820)
RECORD_TABLE = 0x401F7F94         # record id N at + 60 N (the naming routine at + 0x34)
SPRINTF = 0x40000E82              # (buffer, format, ...), as the stock naming routines call it

LABELS_OUT = ("is_wr", "wr_count", "wr_page", "wr_label", "wr_long", "wr_icons", "wr_grid", "wr_grid9",
              "wr_fmt", "wr_vfmt", "wr_range", "wr_turn", "wr_head", "wr_slot_id", "descriptors",
              "wr_group", "wr_group_displaced", "wr_tie", "wr_list_name", "wr_minilabel")
GRID = 0x40017428                 # the stock grid: (view, canvas)
GRID9 = 0x400175E4                # WaveTone's page-3 grid (page id 9): (view, canvas)
ICON_PAGE = 7                     # the SYN page draw's id for WaveTone's OSC page
ICON_SKIP = 0x400182C6            # its branch target past the oscillator icons


def _rep(label: str, text: str) -> str:
    """A std::string's characters with the header the firmware's copy-on-write strings
    keep in front of them (libstdc++'s old ABI: length, capacity, reference count; the
    string object is a pointer to the characters). The descriptors' title and subtitle
    are such strings (the initializer builds them with a string constructor, `jsr %a2@`
    after `pea` of the text). Reference count -1 marks the string unshareable: a copy
    clones it, and nothing ever frees this one."""
    return (f"    .align 2\n    .long {len(text)}, {len(text)}, -1\n"
            f'{label}: .asciz "{text}"')


def label(rid: int) -> str:
    """-> what place `rid` is called on the page; "-" for a place not yet working."""
    return LABELS.get(rid, "-") if rid else "-"


def ms_code(text: str) -> int:
    """A name of the form "Off", "12 ms" or "1.5 ms" as page.c's ms_text() prints it back:
    0, 0x8000 | ms, or tenths of a ms."""
    if text == "Off":
        return 0
    num = text.removesuffix(" ms")
    if "." in num:
        whole, tenth = num.split(".")
        return int(whole) * 10 + int(tenth)
    return 0x8000 | int(num)


def ms_text(code: int) -> str:
    """page.c's ms_text, for the test that the codes print the names back"""
    if code == 0:
        return "Off"
    if code & 0x8000:
        return f"{code & 0x7FFF} ms"
    return f"{code // 10}.{code % 10} ms"


def c_header() -> str:
    """The control table, as C for `wr_gen.h`: per page, eight record ids and labels."""
    ids = ",\n".join(" {" + ", ".join(str(r) for r in page) + "}" for page in PAGES)
    names = ",\n".join(" {" + ", ".join(f'"{label(r)}"' for r in page) + "}" for page in PAGES)
    ranges = ",\n".join(f" {{{rid}, {lo}, {hi}, {d}}}" for rid, (lo, hi, d) in RANGES.items())
    sync_of = ", ".join(str(i) for i in SYNC_INDEX)
    sync = ", ".join(f'"{n[0]}"' for n in SYNC_NOTES)
    smth = ", ".join(str(ms_code(n)) for n in smth_names())
    dclk = ", ".join(str(ms_code(n)) for n in dclk_names())
    return (f"#define WR_PAGES {len(PAGES)}\n"
            f"#define WR_SYNC_RATES {len(SYNC_INDEX)}\n"
            f"static const unsigned char wr_sync_of_rate[WR_SYNC_RATES] = {{{sync_of}}};\n"
            f"static const char *const wr_sync_names[{len(SYNC_NOTES)}] = {{{sync}}};\n"
            f"static const unsigned short wr_smth_text[128] = {{{smth}}};\n"
            f"static const unsigned short wr_dclk_text[128] = {{{dclk}}};\n"
            f"static const unsigned short wr_ids[WR_PAGES][8] = {{\n{ids}\n}};\n"
            f"static const char wr_labels[WR_PAGES][8][6] = {{\n{names}\n}};\n"
            f"#define WR_RANGES {len(RANGES)}\n"
            f"static const int wr_ranges[WR_RANGES][4] = {{\n{ranges}\n}};\n")


TBL_IDS = (247, 251)              # TBL1, TBL2: their range and names are the page's (the pool)
RATE_IDS = (240, 244)             # RATE1, RATE2: named as note lengths while SYNC is on (the page's)
SMTH_IDS = (255, 258)             # SLW1, SLW2: named by the C page's table (Off at 0, then a time)
DCLK_ID = 254                     # DCLK: likewise (Off at 0, then 1..100 ms)
TBL_NAMES = 2 + 128               # the baked tables, then the +Drive pool's 128 (csrc/waverider/pool.h)


SLOT_RUNS = ((SUBNOISE_SLOT0, SUBNOISE[0], len(SUBNOISE)),) + SHAPE_RUNS   # the sound slots Waverider answers


def slot_id_runs(slot_at: int) -> str:
    """`wr_slot_id`'s search: for each run of slots, d0 = record id when the slot (at
    %sp@(SLOT_AT)) is in it, else on to the next run; past the last, to label 9, not taken.
    Ends at label 6 with d0 = id."""
    lines = []
    for k, (first, record, count) in enumerate(SLOT_RUNS):
        last = k == len(SLOT_RUNS) - 1
        head = f"{k + 3}:  " if k else "    "
        lines += [f"{head}move.l  %sp@({slot_at}),%d0",
                  f"    subi.l  #{first},%d0",
                  f"    moveq   #{count - 1},%d1",
                  "    cmp.l   %d0,%d1",
                  f"    bcs.s   {'9f' if last else str(k + 4) + 'f'}",
                  f"    addi.l  #{record},%d0"]
        if not last:
            lines.append("    bra.s   6f")
    return chr(10).join(lines)


def source(page_draw: int, tbl_range: int, tbl_fmt: int, rate_fmt: int) -> str:
    """The chunk's assembly (GNU as, ColdFire), linked at LOAD. PAGE_DRAW is the C
    renderer's entry, `wr_page_draw(view, canvas)`; TBL_RANGE its `wr_tbl_range`
    ({min, max, default}), which it keeps as the +Drive pool fills, so TBL steps
    through the pool; TBL_FMT its `wr_tbl_fmt`, the formatter that names a TBL value
    (the pool position and the name, from its `wr_tbl_names`);
    RATE_FMT its `wr_rate_fmt`, a {names, count} pair per oscillator that it sets from
    the active track's SYNC (count 0: RATE's own number), and a third that names SMTH."""
    table = "\n".join(f"    .long {rid}, lab_{rid}" for rid in LABELS)
    strings = "\n".join(f'lab_{rid}: .asciz "{name}"' for rid, name in LABELS.items())
    mini_table = "\n".join(f"    .long {rid}, mini_{rid}" for rid in MINI_LABELS)
    mini_strings = "\n".join(f'mini_{rid}: .asciz "{name}"' for rid, name in MINI_LABELS.items())
    long_table = "\n".join(f"    .long {60 * rid}, long_{rid}" for rid in LONG_NAMES)
    long_strings = "\n".join(f'long_{rid}: .asciz "{name}"' for rid, name in LONG_NAMES.items())
    # record id -> position on the pages (page x 8 + knob): the destination list's order and its numbers
    key_table = "\n".join(f"    .long {rid}, {8 * p + k}" for p, entries in enumerate(PAGES)
                          for k, rid in enumerate(entries) if rid)
    pages = []
    for k, entries in enumerate(PAGES):
        pages.append(f"    .long title_{k}, subtitle\n"
                     f"    .long {', '.join(str(e) for e in entries)}\n"
                     f"    .long {TAG}")
    page_data = "\n".join(pages)
    # a row is an id and where its {names, count} pair is: TBL's and RATE's pairs change
    fmt_table = "\n".join([f"    .long {60 * rid}, pair_{rid}" for rid in VALUE_NAMES]
                          + [f"    .long {60 * rid}, {tbl_fmt:#010x}" for rid in TBL_IDS]
                          + [f"    .long {60 * rid}, {rate_fmt + 8 * k:#010x}" for k, rid in enumerate(RATE_IDS)]
                          + [f"    .long {60 * rid}, {rate_fmt + 16:#010x}" for rid in SMTH_IDS]
                          + [f"    .long {60 * DCLK_ID}, {rate_fmt + 24:#010x}"]
                          + [f"    .long {60 * rid}, {rate_fmt + 32:#010x}" for rid in SUBNOISE_PLAIN + SHAPE_PLAIN]
                          + [f"    .long {60 * SUBNOISE_COLR}, {rate_fmt + 40:#010x}"]
                          + [f"    .long {60 * SUBNOISE_DEC}, {rate_fmt + 48:#010x}"]
                          + [f"    .long {60 * TRIM_ID}, {rate_fmt + 56:#010x}"])
    fmt_pairs = "\n".join([f"pair_{rid}: .long names_{rid}, {len(names)}" for rid, names in VALUE_NAMES.items()])
    name_lists = "\n".join(f"names_{rid}:\n" + "\n".join(f"    .long name_{rid}_{k}" for k in range(len(names)))
                           for rid, names in VALUE_NAMES.items())
    name_strings = "\n".join(f'name_{rid}_{k}: .asciz "{n}"' for rid, names in VALUE_NAMES.items()
                             for k, n in enumerate(names))
    range_table = "\n".join([f"    .long {rid}, range_{rid}" for rid in RANGES]
                            + [f"    .long {rid}, {tbl_range:#010x}" for rid in TBL_IDS])
    range_values = "\n".join(f"range_{rid}: .long {lo}, {hi}, {d}" for rid, (lo, hi, d) in RANGES.items())
    return f"""
| -- is the active track a Waverider? d0 = 1 if so, else 0; every other register kept
is_wr:
    move.l  %a0,%sp@-
    move.l  %d1,%sp@-
    moveq   #0,%d1
    move.b  {ACTIVE_TRACK:#010x},%d1
    mulu.w  #{SOUND_STRIDE},%d1
    movea.l {KIT_POINTER:#010x},%a0
    adda.l  %d1,%a0
    mvs.b   %a0@({SOUND_BASE + SOUND_TYPE}),%d1
    moveq   #0,%d0
    subq.l  #{NEW_TYPE},%d1
    bne.s   1f
    moveq   #1,%d0
1:  move.l  %sp@+,%d1
    movea.l %sp@+,%a0
    rts

| -- 0x400c24d2 pages(type), from its first instruction by jsr. The stack: our return
| into the reader, the caller's return, the type. A Waverider track: 2, straight back
| to the caller. Otherwise M5's canon_arg: the displaced loads, 5 read as 1.
wr_count:
    bsr.w   is_wr
    tst.l   %d0
    beq.s   1f
    addq.l  #4,%sp
    moveq   #{len(PAGES)},%d0
    rts
1:  move.l  %sp@(8),%d0
    moveq   #{NEW_TYPE},%d1
    cmp.l   %d0,%d1
    bne.s   2f
    moveq   #{CLONE},%d0
2:  moveq   #4,%d1
    rts

| -- 0x400c24ee page(type, n), from 0x400c24f2 by jsr (after its own push of d2). The
| stack: our return, the saved d2, the caller's return, the type, the page. A Waverider
| track: our descriptor n (0..1) or the stock empty page, and back to the caller with d2
| restored. Otherwise M5's canon_page.
wr_page:
    bsr.w   is_wr
    tst.l   %d0
    beq.s   3f
    move.l  %sp@(16),%d0
    moveq   #{len(PAGES)},%d1
    cmp.l   %d1,%d0
    bcs.s   1f
    move.l  #{EMPTY_PAGE:#010x},%d0
    bra.s   2f
1:  moveq   #44,%d1
    mulu.w  %d1,%d0
    addi.l  #descriptors,%d0
2:  addq.l  #4,%sp
    move.l  %sp@+,%d2
    rts
3:  move.l  %sp@(12),%d1
    move.l  %sp@(16),%d0
    subq.l  #{NEW_TYPE},%d1
    bne.s   4f
    moveq   #{CLONE},%d1
    rts
4:  addq.l  #{NEW_TYPE},%d1
    rts

| -- the SYN page's label fetch at 0x40064622 (jsr getShortName(this, id)), now jsr
| here. A Waverider track and a relabelled id: our label. Anything else: the stock
| getShortName, by a tail jump, so it returns to the page itself.
wr_label:
    bsr.w   is_wr
    tst.l   %d0
    beq.s   9f
    move.l  %sp@(8),%d0
    lea     labels,%a0
1:  move.l  %a0@+,%d1
    beq.s   9f
    cmp.l   %d0,%d1
    beq.s   2f
    addq.l  #4,%a0
    bra.s   1b
2:  move.l  %a0@,%d0
    rts
9:  jmp     {GET_SHORT_NAME:#010x}

| -- the LFO page's DEST cell (`0x400c2528`, the one that draws SYN over the parameter's name),
| at 0x400c267c: `movel %a0@(30,%d2:l),%sp@- ; pea 0x40219c2d` (10 bytes, now jsr here and two
| nops). It pushes the destination record's short name straight from the table, not through
| getShortName, so the SYN page's wr_label never saw it: a Waverider destination drew its
| borrowed record's own name (3A Sub Level: PITCH; owner, 2026-10-13). a0 = the record table,
| d2 = 60 x the id, d0 = 4 x the id (still, from the multiply just above). On a Waverider
| track and for an id the pages label, our label; otherwise the stock pointer. Replays the two
| pushes by the return address in a1 (a0 and a1 are free after).
wr_minilabel:
    movea.l %sp@+,%a1
    movea.l %a0@(0x30,%d2:l),%a0
    move.l  %d0,%sp@-
    move.l  %d1,%sp@-
    move.l  %a0,%sp@-
    bsr.w   is_wr
    tst.l   %d0
    beq.s   8f
    move.l  %sp@(8),%d0
    lsr.l   #2,%d0
    lea     mini_labels,%a0
3:  move.l  %a0@+,%d1
    beq.s   4f
    cmp.l   %d0,%d1
    beq.s   2f
    addq.l  #4,%a0
    bra.s   3b
4:  lea     labels,%a0
1:  move.l  %a0@+,%d1
    beq.s   8f
    cmp.l   %d0,%d1
    beq.s   2f
    addq.l  #4,%a0
    bra.s   1b
2:  move.l  %a0@,%sp@
8:  movea.l %sp@+,%a0
    move.l  %sp@+,%d1
    move.l  %sp@+,%d0
    move.l  %a0,%sp@-
    move.l  #0x40219c2d,%sp@-
    jmp     %a1@

| -- the long-name getter 0x400365c8, at 0x400365f2 (`move.l %a0@(40,%d1:l),-(%sp) ;
| move.l %d2,-(%sp)`, 6 bytes: push the record's long name, then the string to build),
| now jsr here. a0 = the record table, d1 = 60 x id; a0 and a1 are free after, the next
| call (0x401ce69e) is a scratch-register call. Pushes our name or the record's, then
| d2, under the return address, and goes back.
wr_long:
    movea.l %a0@(40,%d1:l),%a1
    bsr.w   is_wr
    tst.l   %d0
    beq.s   9f
    lea     long_names,%a0
1:  move.l  %a0@+,%d0
    beq.s   9f
    cmp.l   %d0,%d1
    beq.s   2f
    addq.l  #4,%a0
    bra.s   1b
2:  movea.l %a0@,%a1
9:  movea.l %sp@+,%a0
    move.l  %a1,%sp@-
    move.l  %d2,%sp@-
    jmp     %a0@

| -- the LFO destination list (owner, 2026-10-13: one group, page and knob order, numbers).
| wr_key: d0 = a record id -> d0 = its place on the pages (page x 8 + knob), -1 for a record
| the pages do not hold. Every other register kept.
wr_key:
    move.l  %d1,%sp@-
    move.l  %a0,%sp@-
    lea     key_table,%a0
1:  move.l  %a0@+,%d1
    beq.s   2f
    cmp.l   %d1,%d0
    beq.s   3f
    addq.l  #4,%a0
    bra.s   1b
2:  moveq   #-1,%d0
    bra.s   4f
3:  move.l  %a0@,%d0
4:  movea.l %sp@+,%a0
    move.l  %sp@+,%d1
    tst.l   %d0
    rts

| wr_sortkey: d0 = a record id -> d0 = 1000 + its place on the pages, or the entry itself for
| any other record (so every entry has one key, the order is total, and what stock lists
| first in a group, META None, stays first: owner, 2026-10-13). d1 kept.
wr_sortkey:
    move.l  %d1,%sp@-
    move.l  %d0,%d1
    bsr.s   wr_key
    bpl.s   2f
    move.l  %d1,%d0
    bra.s   1f
2:  add.l   #1000,%d0
1:  move.l  %sp@+,%d1
    rts

| -- the group getter 0x400dbce8(entry), from its first instruction by jmp (its first two
| instructions, 10 bytes, are replaced). On a Waverider track the records its pages hold
| answer WaveTone's group (1), FM Tone's borrowed ones (group 0) included, so the list shows
| one SYN group. Otherwise the displaced `move.l %sp@(4),%d0 ; cmpi.l #321,%d0` and on. They
| are the stock bytes unchanged (wr_group_displaced, recorded with platform.displace), so the
| platform writes the parameter count's bound here when lfo4 adds its records.
wr_group:
    bsr.w   is_wr
    tst.l   %d0
    beq.s   9f
    move.l  %sp@(4),%d0
    bsr.s   wr_key
    bmi.s   9f
    moveq   #1,%d0
    rts
wr_group_displaced:
9:  move.l  %sp@(4),%d0
    cmpi.l  #321,%d0
    jmp     0x400dbcf2

| -- the sort comparator's tie-break at 0x400390d0 (`cmp.l %d3,%d2 ; sgt %d0 ; bra.s`, 6
| bytes, now jsr here). d3 and d2 are the two entries, a before b when the result is true. On a
| Waverider track the entries' places on the pages decide, within a group; otherwise the
| entries themselves. Returns past the else arm (4 bytes) to the comparator's exit.
wr_tie:
    bsr.w   is_wr
    tst.l   %d0
    beq.s   1f
    move.l  %d3,%d0
    bsr.s   wr_sortkey
    move.l  %d0,%sp@-
    move.l  %d2,%d0
    bsr.s   wr_sortkey
    cmp.l   %sp@+,%d0
    sgt     %d0
    bra.s   2f
1:  cmp.l   %d3,%d2
    sgt     %d0
2:  addq.l  #4,%sp@
    rts

| -- the list's name text at 0x40105af2 (`move.l %sp@(64),%sp@- ; pea 0x4021f244`, 10 bytes,
| now jsr here and two nops). d2 is the entry; the char* the format reads is at sp+64. On a
| Waverider track, for a record the pages hold, it becomes "1A " + the name (page, knob), in
| list_buf. The header's own name path does not come through here. The string object at
| sp+64 is never touched (its destructor reads a reference-count header list_buf does not
| have): only the copy of its pointer pushed for the formatter is replaced, via a0, which
| the stock code sets again before the formatter call.
wr_list_name:
    movea.l %sp@+,%a1
    move.l  %a1,%sp@-
    move.l  %d0,%sp@-
    move.l  %d1,%sp@-
    move.l  %a0,%sp@-
    move.l  %sp@(80),%sp@
    bsr.w   is_wr
    tst.l   %d0
    beq.s   8f
    move.l  %d2,%d0
    bsr.w   wr_key
    bmi.s   8f
    move.l  %d0,%d1
    lsr.l   #3,%d1
    add.l   #49,%d1
    lea     list_buf,%a0
    move.b  %d1,%a0@+
    and.l   #7,%d0
    add.l   #65,%d0
    move.b  %d0,%a0@+
    move.b  #32,%a0@+
    movea.l %sp@(80),%a1
    moveq   #59,%d1
2:  move.b  %a1@+,%d0
    move.b  %d0,%a0@+
    beq.s   3f
    subq.l  #1,%d1
    bne.s   2b
    clr.b   %a0@
3:  lea     list_buf,%a0
    move.l  %a0,%sp@
8:  movea.l %sp@+,%a0
    move.l  %sp@+,%d1
    move.l  %sp@+,%d0
    movea.l %sp@+,%a1
    move.l  %a0,%sp@-
    move.l  #0x4021f244,%sp@-
    jmp     %a1@

| -- the SYN page draw at 0x4001821e (`moveq #7 ; cmp.l %d3,%d0 ; bne.w` past the icons),
| now `jsr` here and a nop. Back to the icons (0x40018226) when the stock test would draw
| them: page id 7 in d3, and not a Waverider track. Otherwise the return address becomes
| the stock branch target, past them. d0 is scratch there (the stock code loads it).
wr_icons:
    bsr.w   is_wr
    tst.l   %d0
    bne.s   3f
    moveq   #{ICON_PAGE},%d0
    cmp.l   %d3,%d0
    beq.s   2f
1:  move.l  #{ICON_SKIP:#010x},%sp@
2:  rts
| a Waverider track: never WaveTone's icons (its page, wave included, is wr_grid's)
3:  bra.s   1b

| -- the SYN page draw at 0x40018214 (`move.l %d2,-(%sp) ; move.l %a2,-(%sp) ; jsr grid ;
| addq.l #8,%sp`, 10 bytes), now jsr here and two nops. a2 = the view, d2 = the canvas.
wr_grid:
    move.l  %d2,%sp@-
    move.l  %a2,%sp@-
    bsr.w   is_wr
    tst.l   %d0
    beq.s   1f
    jsr     {page_draw:#010x}
    addq.l  #8,%sp
    rts
1:  jsr     {GRID:#010x}
    addq.l  #8,%sp
    rts

| -- the same for the SYN page draw's page-id-9 arm (WaveTone's page 3, a Waverider's
| page 3 since M10a), entered by `jsr` at 0x40018208 with nothing pushed: the site's
| `subq.l #8,%sp` after it leaves the 8 bytes the draw's shared exit pops
wr_grid9:
    move.l  %d2,%sp@-
    move.l  %a2,%sp@-
    bsr.w   is_wr
    tst.l   %d0
    beq.s   1f
    jsr     {page_draw:#010x}
    addq.l  #8,%sp
    rts
1:  jsr     {GRID9:#010x}
    addq.l  #8,%sp
    rts

| -- the value text 0x400c243c(id, value), at 0x400c2464 (`movea.l %a0@(0x34,%d0:l),%a0 ;
| jsr %a0@`, 6 bytes: call the record's naming routine with the value and the buffer),
| now jsr here. a0 = the record table, d0 = 60 x id; the stack is the routine's own:
| our return (0x400c246a), the value, the buffer. A Waverider track and a control in
| fmt_table whose names-and-count pair has names (count above 0): its name for value >> 8
| (the last name past the end), printed as the stock routines print theirs; a count below
| 0 makes the first word a C formatter, f(buffer, value), that writes the text itself.
| Anything else (count 0, or no row): the record's routine (still in a1), by a tail jump.
wr_fmt:
    movea.l %a0@(0x34,%d0:l),%a1
    move.l  %d0,%d1
wr_fmt_named:
    bsr.w   is_wr
    tst.l   %d0
    beq.s   9f
    lea     fmt_table,%a0
1:  move.l  %a0@+,%d0
    beq.s   9f
    cmp.l   %d0,%d1
    beq.s   2f
    addq.l  #4,%a0
    bra.s   1b
2:  movea.l %a0@,%a0
    move.l  %a0@(4),%d1
    beq.s   9f
    bmi.s   5f
    movea.l %a0@,%a0
    move.l  %sp@(4),%d0
    andi.l  #0xFFFF,%d0           | the word, unsigned: the caller sign-extends (TBL at 0x8000 up)
    asr.l   #8,%d0
    bpl.s   3f
    moveq   #0,%d0
3:  cmp.l   %d1,%d0
    blt.s   4f
    move.l  %d1,%d0
    subq.l  #1,%d0
4:  lsl.l   #2,%d0
    move.l  %a0@(0,%d0:l),%sp@-
    pea     {FORMAT_S:#010x}
    move.l  %sp@(16),%sp@-
    jsr     {SPRINTF:#010x}
    lea     %sp@(12),%sp
    rts
| a negative count: the pair's first word is a C formatter, f(buffer, value)
5:  movea.l %a0@,%a0
    move.l  %sp@(4),%sp@-
    move.l  %sp@(12),%sp@-
    jsr     %a0@
    addq.l  #8,%sp
    rts
9:  movea.l %a1,%a0
    jmp     %a1@

| -- the parameter set's value text (vtable +0x5c, 0x40036692(this, id, value, buffer)),
| the other way a value is named -- the SYN page's readouts and the header ask it.
| With a naming routine on the record it ends at 0x40036708 (`movea.l %a2@(0x34),%a1 ;
| movem.l (%sp),%d2-%d4/%a2 ; lea 16(%sp),%sp ; jmp %a1@`, 14 bytes: a tail call with
| the value and the buffer), now `jmp` here. a2 = the record. Does the same, then
| wr_fmt's own test: the routine's frame is wr_fmt's.
wr_vfmt:
    movea.l %a2@(0x34),%a1
    move.l  %a2,%d1
    subi.l  #{RECORD_TABLE:#010x},%d1
    movem.l %sp@,%d2-%d4/%a2
    lea     %sp@(16),%sp
    bra.w   wr_fmt_named

| -- the limits getter 0x400dbff0(id), a0 = where to put {{min, max, default}}: its first
| two instructions (`move.l %d2,-(%sp) ; move.l %sp@(8),%d1`, 6 bytes) now jsr here.
| Every clamp asks it -- the knob turn 0x40036adc among 14 callers. A Waverider track
| and a control in range_table: ours, and straight back to the caller with d0 = a0, as
| the getter returns. Anything else: the two displaced instructions, then on at
| 0x400dbff6. A row is an id and where its triple is: TBL's is the C page's, which the
| +Drive pool changes.
wr_range:
    move.l  %sp@(8),%d1
    bsr.w   is_wr
    tst.l   %d0
    beq.s   9f
    lea     range_table,%a1
1:  move.l  %a1@+,%d0
    beq.s   9f
    cmp.l   %d0,%d1
    beq.s   2f
    addq.l  #4,%a1
    bra.s   1b
2:  movea.l %a1@,%a1
    move.l  %a1@+,%a0@
    move.l  %a1@+,%a0@(4)
    move.l  %a1@,%a0@(8)
    move.l  %a0,%d0
    addq.l  #4,%sp
    rts
9:  movea.l %sp@+,%a1
    move.l  %d2,%sp@-
    move.l  %sp@(8),%d1
    jmp     %a1@

| -- the knob turn 0x40036adc(set, id, current, delta), d4 = the id: its loads of current
| and delta (`move.l %sp@(56),%d2 ; move.l %sp@(60),%d7`, 8 bytes) now jsr here. Its
| caller passes current sign-extended from the stored word, so TBL's top values (0x8000
| up, the pool's last two tables) read as negative, and the clamp sent any turn from them
| to 0, Prim. A Waverider track and TBL1 or TBL2: current as the unsigned word it is.
| Anything else as stock. d0 is free here (the next use is the getter's answer).
wr_turn:
    move.l  %sp@(60),%d2
    move.l  %sp@(64),%d7
    cmpi.l  #{TBL_IDS[0]},%d4
    beq.s   1f
    cmpi.l  #{TBL_IDS[1]},%d4
    bne.s   9f
1:  bsr.w   is_wr
    tst.l   %d0
    beq.s   9f
    andi.l  #0xFFFF,%d2
9:  rts

| -- the header's "name=value" (0x40067820: `move.l %fp@(-36),%sp@- ; pea "%s=%s"`, 10
| bytes, then the header's own printf 0x400562e6), d2 = the id: now jsr here, which
| pushes the same two. TBL1 or TBL2 on a Waverider track (owner, tbl128b): the name ""
| and the format "%s%s", so the header shows only the value, "T:126 HS Sa".
wr_head:
    movea.l %sp@+,%a0
    move.l  %fp@(-36),%sp@-
    pea     {HEAD_FORMAT:#010x}
    cmpi.l  #{TBL_IDS[0]},%d2
    beq.s   1f
    cmpi.l  #{TBL_IDS[1]},%d2
    bne.s   9f
1:  bsr.w   is_wr
    tst.l   %d0
    beq.s   9f
    lea     head_none,%a1             | ColdFire: no #imm to d16(An) for .l; a1 is free here
    move.l  %a1,%sp@(4)
    lea     head_value,%a1
    move.l  %a1,%sp@
9:  jmp     %a0@
head_none:  .asciz ""
head_value: .asciz "%s%s"
    .align 2

| -- param_set_slot_to_id(slot, type, filter) at 0x400dc02a, every per-machine list's
| source (p-locks, LFO destinations, CC): the bus's ev_param_slot handler (dnfw.mods.bus),
| int f(slot, type, filter), nonzero when taken. Slot 50..57 of a Waverider sound: page 3's
| record, 227 + slot - 50; slots 58..61 and 62..64: page 5's, 208 + slot - 58 and 235 + slot
| - 62. A Waverider sound is type 5 (its own type: the engine's callers), or type 1 on a
| Waverider track (the UI reports 5 as WaveTone, 1). Anything else: 0, and the bus asks the
| next handler, then the stock routine.
wr_slot_id:
{slot_id_runs(4)}
6:  move.l  %d0,%a0
    moveq   #{NEW_TYPE},%d1
    cmp.l   %sp@(8),%d1
    beq.s   2f
    moveq   #1,%d1
    cmp.l   %sp@(8),%d1
    bne.s   9f
    bsr.w   is_wr
    tst.l   %d0
    beq.s   9f
2:  move.l  %a0,%d0
    rts
9:  moveq   #0,%d0
    rts

    .align 2
fmt_table:
{fmt_table}
    .long 0
{fmt_pairs}
range_table:
{range_table}
    .long 0
{range_values}
{name_lists}
labels:
{table}
    .long 0
mini_labels:
{mini_table}
    .long 0
long_names:
{long_table}
    .long 0
key_table:
{key_table}
    .long 0
    .align 2
list_buf:
    .space 64
descriptors:
{page_data}
{_rep("subtitle", SUBTITLE)}
{chr(10).join(_rep(f"title_{k}", t) for k, t in enumerate(TITLES))}
{strings}
{mini_strings}
{long_strings}
{name_strings}
    .align 2
"""
