"""pslide in the emulator: each slide frame by frame against stock, SLD's control, the edits that
carry SLD, the data stock reads, NOP controls and branch counts.

    python scripts/emu_pslide.py BUILD.syx [--stock STOCK.syx] [--case NAME ...] [--controls]
        [--coverage] [--jobs N]

BUILD is a Digitone II 1.11 or 1.12 image with pslide (`dnfw mods apply --mod pslide`). Each case enters
trigs on track 1, or the track it names, through the panel in GRID RECORDING, locks the FLTR page's knob A (slot 71) or B
(slot 72) with the trig held, sets SLD with knob E on TRIG PAGE 2 with the trig held, presses
PLAY and captures every frame sent to the DSP (`0x400cf7be`, all 2,688 bytes: the trigger masks and
every voice's values). Before PLAY it reads that track's step flags, and a case whose SLD did not
take is reported as a setup failure. The same keys run on stock, where knob E does nothing, so
each lock jumps: stock gives the values each slide starts and ends on, and the build must glide
between them on the line, arrive within a frame of its time and stay there. A step is 187.5
frames at 120 BPM.

- `length-half`, `length-2`, `length-8`, `length-16`: step 5's lock with SLD 1/2, 2, 8 and 16 steps.
- `length-track-12`, `next-track-2`, `next-track-12`, `speed-track-2`: the same off track 1, where step
  evaluation's base is the track's data: a length on track 12, NEXT on tracks 2 and 12, and a
  length on track 2 at 2x in per-track mode.
- `next-track-length`: per-track mode with track 1's length 8: step 5 NEXT glides (two parameters)
  to step 1's values, which play again 4 steps on.
- `next-alone`, `next-loop-alone`: a NEXT trig with no other trig, without and with Page Loop: its
  lock stays.
- `return` (rule 9): step 9 with SLD 1 and no lock glides back from step 5's lock to the sound's value.
- `next`: step 1 with NEXT glides to step 5's lock and arrives as step 5 plays.
- `next-micro` (rule 8): step 5 also a quarter step late by micro timing ([TRIG] held, [RIGHT] six
  times): step 1 arrives on step 5's grid time, before step 5's note.
- `next-length`, `next-loop` (rule 6): 32 steps, trigs 1, 9 and 25, step 9 NEXT. Without Page
  Loop it glides to step 25 over 16 steps; with page 1 looped, to step 1 over 8.
- `knob` (rule 1): FLTR knob A turned during the slide: the value leaves the slide and ends on
  the knob's value, which the track's other voices show; it never reaches the lock.
- `knob-chord` (rule 1): the same on step 5 played as a chord of three: each voice.
- `knob-end` (rule 1): the voice's target written as a knob writes it, between the slide's last
  update and its arrival (placed by a first run): the value leaves the slide.
- `knob-start`: on one voice, the target is written just before a new slide. That slide must
  start from the smoothed value and reach its lock, rather than cancel itself as a knob change.
- `knob-chord-after` (rule 1): step 5 a chord of three sliding knobs A and B. Each voice's target of
  knob A is written as a knob writes it, after the chord's frame and before its start is finished (placed
  by a first run): on each voice knob A leaves the slide for the written value, and knob B goes on.
- `knob-unheld`: knob E turned with no trig held, then less than a unit with a trig held: SLD stays OFF.
- `push`: SLD 4 on steps 1 and 9, [TRIG 9] held on TRIG PAGE 2: SLD's box looks locked (the screen);
  knob E's push keeps SLD, its release sets step 9's to OFF and the box looks plain. Knob C's and
  F's pushes, E's with nothing held, and E's on the SYN page with no parameter at E (four [SYN] from
  TRIG PAGE 2) keep step 1's.
- `preview-sld-off`: step 1's SLD turned up and back to OFF while stopped: step 1 jumps as on stock.
- `stop` (rule 2): STOP during the slide: the value stays where the line was.
- `pattern` (rule 2): pattern 2 cued: the value stays where the line was on the frame pattern 2
  starts (16 steps after the first note).
- `tempo` (rule 3): the tempo lowered during the slide: the slope after it is the slope before
  it times the ratio of the clock rates (`0x402a0dec`), and the slide still lands on the lock.
- `machine`, `machine-same` (rule 4): step 5 preset-locked to a pool preset of FM DRUM jumps as on
  stock; preset-locked to the track's own FM TONE, it glides.
- `machine-chord` (rule 4): step 5 a chord of three, preset-locked to FM DRUM: each voice jumps as
  on stock (the chord's later notes find the dropped slide and take the whole list).
- `machine-first`, `next-preset-first`, `next-preset-first-same` (rule 4): the preset lock on step 1,
  the first note after PLAY, so the track has no voice of its own. With SLD 4 or NEXT and a pool preset
  of FM DRUM it changes at once, as on stock. On a track of FM DRUM, with NEXT and a pool preset of FM
  DRUM, it glides to step 5's lock: the test reads the kit's sound of the track, whose machine is not
  0 there.
- `next-preset-type`, `next-preset-same` (rule 4): step 5 NEXT, preset-locked to FM DRUM, changes at
  once; to the same machine, it glides to step 9's lock.
- `locktrig-preset` (rule 4): on the voice of step 1's note, preset-locked to FM DRUM, a lock trig
  with SLD changes knob A at once.
- `retrig` (rule 5): each retrig note of step 5 starts on the line, and every voice lands together.
- `retrig-dense`: the same with every knob of six pages locked too, so that the retrig voices' writes
  pass the budget and the voices move in turns: each still starts on the line and lands.
- `overlap` (rule 11): step 5's slide starts where step 1's slide was; step 1's goes on.
- `chord`, `unison`, `arp`: each voice of a chord on step 5, each of the three voices of its note with
  UNISON on in VOICE SETUP, and each arp note of a long note on step 5 that starts during the slide,
  follows the line.
- `locktrig`, `locktrig-take`: under step 1's 16-step slide of knob A, a lock trig on step 5
  slides knob B on every voice of the track over a step, step 1's slide going on; or it locks
  knob A, and that voice glides from where step 1's slide was to the lock trig's value and stays.
- `locktrig-take-chord`: step 1 a chord of three, its slide of knob A taken by the lock trig on
  step 5 on each voice: each glides from where it was to the lock trig's value and stays.
- `locktrig-off`: under step 1's slide of knobs A and B, a lock trig without SLD locks knob A: knob A
  is stock's from it, knob B goes on. A lock trig with SLD and no lock on step 3 changes nothing.
- `locktrig-first`, `locktrig-next`: a lock trig with SLD on step 1, the first step from STOP, glides
  every voice; one with NEXT glides to step 9's lock.
- `locktrig-plain`, `locktrig-other-track`: a lock trig without SLD and no slide anywhere: the frames
  are stock's; with a slide on track 2 only: that slide goes on.
- `mono`, `mono-locktrig`, `steal`: a later note on a sliding voice (VOICES 1 in VOICE SETUP, or
  track 2's notes cycling through the voices) takes it out of the slide: from that note the voice
  reads what stock's does.
- `takeover`: lock trigs on steps 2 to 9 all lock knob A over 16 steps: each takes every voice
  from the one before, whose slides end, and the pool does not run out.
- `pool`: lock trigs on steps 2 to 8 each lock another FLTR knob over 16 steps, 16 voices each:
  the pool (96 slides) runs out during the seventh, whose knob jumps as on stock on the voices left
  without a slide, while the first's slides go on.
- `conditions` (rule 7): step 1 NEXT, step 5 locked and LST (it does not play): step 1 arrives at
  step 5's lock as step 5 would play.
- `every-step`: a trig with SLD 1 on each of the 16 steps, FLTR knob A locked high and low in turn,
  then STOP: through two passes of the pattern every note's voice reaches the lock stock gives that
  note, and stock's list release frees as many lists as on stock (the stopped sequencer's list has
  no count, and a free of it would give it out twice). The knob reaches its upper and lower
  stops, so encoder acceleration cannot give the paired images different lock values.
- `muted`: track 1 quick-muted for 18 steps of slides, then unmuted: the first note after it slides.
- `muted-tracks`: 16 tracks with SLD on every step, 15 of them quick-muted, then unmuted: the notes
  and the notes whose trig's lock list reaches the applier are stock's (stock has 64 lists).
- `next-chords`: track 1's step 1, a chord of three with NEXT, copied to all 16 tracks: 48 notes
  start in one frame, more than the queue of starts holds, and the notes and the applier's
  calls are stock's.
- `no-lists`: the list allocator's free list emptied before PLAY (stock's allocator then reads
  address 0, in the emulator): the notes and the lists are stock's.
- `stop-first`, `stop-return`: step 1 with SLD, STOP, then PLAY: the restart's step 1 slides. With no lock
  of its own (step 9 locks VOL, AMP knob H) it plays as stock's: stock clears the voices' sounds at STOP.
- `stop-pending`: STOP between step 5's evaluation and its note, then PLAY: step 1 plays as on
  stock and step 5 slides.
- `arpplocks`, `directjump`, `waverider`, `lfo4` run on stock with that mod and pslide, against
  stock with that mod (`dnfw mods apply` from the stock image). `arpplocks`: track 1's arp on UP,
  step 1's long note sliding knob A, a lock trig on step 5 locking the arp's MODE and sliding knob B:
  the notes, arpplocks' arp state and the applier's calls (arpplocks reads each) are arpplocks
  alone's. `directjump`, `directjump-late` (rule 2): directjump on, pattern 2 (a trig on every step)
  cued in the PTN view during step 9's slide, in its step 13 and near its end: the slide ends where
  it is as pattern 2's first note plays. `waverider`: track 1 on Waverider, step 5's FLTR lock glides
  over 4 steps.
  `lfo4`: LFO 4 aimed at FM DRUM's TUNE, step 5's TUNE lock with SLD 2: the frames differ from lfo4
  alone's by the slide alone.
- `lfo-locks`: step 5 locks SPD, FADE, SPH and DEP of LFOs 1 to 3 (knobs A, C, F and H of each MOD
  page) with SLD 4. These values go to the ColdFire's LFO evaluator (`0x40137726`), not to the DSP, so
  this case captures the values the evaluator reads in each frame in place of the frame to the DSP:
  each jumps on stock, and on the build each follows the line from stock's value before it to the lock.
- `residual`: step 5 also locks ALGO (SYN knob A), which does not slide: it jumps as on stock.
- `restore-residual`: VOICES 1, step 1 locks ALGO and step 5 slides FLTR knob A: at step 5 the
  voice's ALGO goes back to the sound's value, as on stock, while knob A slides.
- `whole-sound`: VOICES 1, the track's VOL turned down after the pool preset was saved, and step 5
  preset-locked to that preset: step 5's note takes the preset's VOL at once, as stock's whole load
  gives it, while its knob A lock slides.
- `dense`: a lock trig locking every knob of SYN 1 and 2, FLTR 1 and 2, AMP and FX on 16 voices:
  the slides move every fourth, then every second frame, and each lands; ALGO jumps.
- `clock-back`: the clock poked back ten frames' worth during a slide (as an external clock can
  move it; the value comes from a first run of the same keys): the slide never moves back and lands.
- `control`: knob E sets SLD on each held trig, from OFF to NEXT and no further, does nothing
  with no trig held, passes to stock's LFO.T on TRIG PAGE 1, and reaches a trig on page 3.
- `copy-paste`, `copy-two`, `freeze`, `freeze-rotated`, `remove`, `clear`, `note-edit-undo`, `shift`,
  `page-paste`, `track-paste`: step 1 seeded `0x03e9` (SLD NEXT on stock's fields), then trig copy
  and paste, a two-trig copy, FREEZE TRACK with the identity mapping and with rotation, the trig
  removed and placed again, [TRIG] + [PLAY], NOTE EDIT's clear of the note and its UNDO ([FUNC] +
  [PLAY] twice), [FUNC] + [RIGHT], page and track copy and paste. The build's words keep stock's
  other bits; paste, rotated FREEZE TRACK, removal, clear and the UNDO differ from stock in SLD alone.
- `stock-plays`, `stock-reload` (stock only): stock sends the same frames to the DSP with SLD's
  bits set on its trigs as without them; stock's pattern save and reload ([FUNC] + [YES], the
  words zeroed, [FUNC] + [NO]) give the words back with SLD's bits and every other bit.

Every run watches the fault reporter (`0x4011ea6a`) and the DSP uploader's refusal
(`0x400cf678`); a run that reaches either fails. The firmware's UI takes one panel input a pass
and stalls for about 48 M instructions every 4.506 G, keeping only the last input of a stall, so
every run puts off an input that would fall in one (`clear_of_stalls`).

`--controls` builds, from BUILD, one image per entry of CONTROLS with one instruction of the
mod's chunk replaced by NOPs, and runs the case whose check that instruction serves: the case
must fail. `--coverage` counts each conditional branch of the chunk's code taken and not taken,
over every case run on BUILD, and lists each branch whose two ways did not both run. Each way's
count comes from `panel_drive --count` on the branch, its target, its next instruction and every
instruction that reaches those two: an instruction runs as often as the ways into it are taken
(`edges`). A test of an empty count before a counted loop is read from its register at the test
(`--regs-at`), as flow alone cannot split it. A run that leaves branches untaken fails.

On OS 1.12 (issue #382) the same cases run. The build's version picks the stock image and the
image the other mods apply to, and every stock address above moves through `dnfw.osport`, or
through `ON_1_12` for the three the map lacks.

The checks are `scripts/emu_pslide_checks.py`'s, and the reading of the branch counts
`scripts/emu_pslide_branches.py`'s. Needs what `scripts/emu_seqplay.py` needs,
through `PANEL_DRIVE`, and for `--controls` and `--coverage` an m68k objdump (`dnfw.image.objdump`).
A 1.12 build needs digikit `main`'s `panel_drive`, which boots 1.12.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Literal

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from dnfw import osport  # noqa: E402
from dnfw.checkout import resources_dir  # noqa: E402
from dnfw.cli.main import main as cli_main  # noqa: E402
from dnfw.cli.files import read_image  # noqa: E402
from dnfw.container.section import compress  # noqa: E402
from dnfw.firmware import build as fwbuild  # noqa: E402
from dnfw.firmware.load import load  # noqa: E402
from dnfw.image import objdump  # noqa: E402
from dnfw.mods import platform, pslide, specs  # noqa: E402
from dnfw.patch import area  # noqa: E402

import emu_pslide_checks as C  # noqa: E402
import emu_seqplay as ES  # noqa: E402
import emu_pslide_branches as BR  # noqa: E402
from emu_pslide_branches import branches, counted, edges, loop_tests, seeds  # noqa: E402
from emu_pslide_checks import (  # noqa: E402
    APPLIER, END_POKE, FRAME_BYTES, LFO_CAPTURE, LISTED, LIST_FREED, NEXT, SLD_BITS, SLOT_A, Run, check_arpplocks,
    check_clock_back, check_conditions, check_control, check_dense, check_direct_jump, check_every_step,
    check_first_preset, check_frames_stock, check_joins, check_knob, check_knob_after, check_knob_chord,
    check_knob_end, check_length, check_lfo4, check_lfo_locks, check_undo,
    check_locktrig, check_locktrig_chord, check_locktrig_first, check_locktrig_next, check_locktrig_off,
    check_locktrig_preset, check_machine, check_machine_chord, check_mono, check_mono_locktrig, check_muted,
    check_next, check_next_alone, check_next_loop, check_next_micro, check_next_preset, check_next_preset_same,
    check_next_track_2, check_next_track_length, check_other_track, check_overlap, check_pattern, check_pool,
    check_preview_off, check_residual, check_restore_residual, check_return, check_same_notes, check_speed, check_steal,
    check_push, check_stock_plays, check_stock_reload, check_stop, check_stop_first, check_stop_pending, check_stop_return,
    check_takeover, check_tempo, check_unheld, check_unison, check_whole_sound, check_words, screen, sld)

STOCK = resources_dir() / "00_Firmware/Digitone_II_OS1.11_dist/Digitone_II_OS1.11.syx"
STOCK_ZIP = resources_dir() / "00_Firmware/Digitone_II_OS1.11_dist.zip"
SOURCES = {"1.11": STOCK_ZIP, "1.12": resources_dir() / "00_Firmware/Digitone_II_OS1.12.syx"}   # what mods apply to
# keys and encoders (the firmware's button table, 0x401f3824)
TRIG_PAGE, SYN, FLTR, AMP, PRESET, TEMPO, YES, UP, NO, LEFT, DOWN, RIGHT = 1, 2, 3, 4, 7, 9, 10, 11, 12, 13, 14, 15
TRK, FUNC, RECORD, PLAY, STOP, PAGE, PTN, TRIG1, VOICE, ARP, STACK = 16, 17, 19, 20, 21, 22, 23, 25, 50, 51, 53
FX, MOD = 5, 6
KNOB_A, KNOB_B, KNOB_D, KNOB_E, KNOB_G, KNOB_H, LEVEL = 1, 2, 4, 5, 7, 8, 9      # LEVEL/DATA is panel_drive's ninth
PUSH_E = 45                          # knob E's push (41 to 48: knobs A to H as buttons)
CLOCK = 0x80005398                   # the audio interrupt's position counter
CONDITIONS, LST = 0x280, 6           # track 1's COND byte per step in the pattern; LST plays on a change
PATTERN = 0x4121898C                 # a fresh boot's pattern: track 1's step s flags at + 2 (s - 1)
FULL_PARAMETER_TURN = 128           # cover the full 0..127 range, independent of encoder acceleration
RATE = 0x402A0DEC                    # BPM x 120: the clock moves twice this in each audio frame
LIST_HEAD = 0x4464422C               # the lock-list allocator's free-list head (0x40138986)
SRC = 0x80003AF0                     # each voice's targets: word 17 + 101 voice + slot
SCALE_MODE, TRACK_SCALE, TRACK_LENGTH, TRACK_STRIDE = 122201, 1167, 1164, 1701   # per-track mode, a track's speed, length
FAULT_WATCH = "0x4011ea6a,0x400cf678"
LFO_EVALUATOR = 0x40137726           # the ColdFire's LFO evaluator: argument 0, each voice's values
# The harness's own 1.11 addresses on OS 1.12 (issue #382) that map_1.12.json lacks: the first
# pattern and the fault watches as `scripts/emu_directjump.py`'s ON_1_12 reads them, and the list
# release's free (the release, 0x401389a8 -> 0x40138c88 in the map, has 1.11's bytes but for the
# free-list head, which moves with the heap, + 0x1000: its free is at + 0x22 there too). The list
# allocator's free-list head is the operand of the release's move.l, 0x4464522c on 1.12. The note
# path's applier call (LISTED) keeps its address: the note path's bytes from 0x40026c20 to
# 0x40026c44 are 1.11's on 1.12 (map_1.12.json: exact)
ON_1_12 = {"PATTERN": 0x4121998C, "FAULT_WATCH": "0x4011ed4a,0x400cf7dc", "LIST_FREED": 0x40138CAA,
           "LIST_HEAD": 0x4464522C, "LISTED": 0x40026C2A}
# The UI takes one panel input a pass (about 4.4 M instructions), and every 4.506 G instructions from
# 4.533 G it stalls for about 48 M, keeping only the last input that arrives meanwhile: measured on
# stock and on pslide alike (2026-11-25, a turn every 6 M around the first two stalls). panel_drive
# runs the first step 100 M after the main UI (952 M with the SSI paced), a tap takes 20 M.
STEPS_FROM, TAP = 952_000_000, 20_000_000
STALL_FIRST, STALL_EVERY, STALL_SPAN, STALL_MARGIN = 4_533_000_000, 4_505_700_000, 48_000_000, 12_000_000
# label in the chunk: the case that must fail with that instruction replaced by NOPs
CONTROLS = {"u_foreign": "knob", "f_stopped": "stop", "f_cut": "pattern", "w_owner": "locktrig-take",
            "sv_machine": "machine", "n_join": "retrig", "m_vslide": "mono", "m_vserial": "mono-locktrig",
            "u_taken": "takeover", "l_slides": "residual", "u_back": "clock-back", "p_uncounted": "every-step",
            "u_foreign_all": "knob-chord", "w_owner_all": "locktrig-take-chord", "p_early": "directjump",
            "a_stock": "arpplocks", "w_unplayed": "muted-tracks", "p_preview": "preview-sld-off",
            "l_revoke": "locktrig-off", "p_next_machine": "next-preset-type", "l_machine": "locktrig-preset",
            "k_held": "knob-unheld", "u_foreign_end": "knob-end", "p_track": "next-track-2", "w_stale": "stop-first",
            "p_knob": "push", "p_release": "push", "p_page": "push", "d_locked": "push", "s_target": "knob-start",
            "d_claim": "knob-chord-after", "lv_kit": "next-preset-first-same"}
BACK = 10 * 2 * 14400                # ten frames of the clock at 120 BPM
POST_EXCHANGE_DELAY = 2_000         # place the target write after the preceding frame's smoother


# ---- panel steps ----

def tap(code: int) -> list[str]:
    return [f"tap:{code}"]


def wait(millions: int) -> list[str]:
    return [f"wait:{millions}M"]


def trig(n: int) -> int:
    return TRIG1 + n - 1


def hold(keys, inner) -> list[str]:
    down = [s for n in keys for s in (f"press:{trig(n)}", "wait:4M")]
    up = [s for n in keys for s in (f"release:{trig(n)}", "wait:2M")]
    return down + wait(40) + list(inner) + up + wait(40)


def knob_e(units: int) -> list[str]:
    return ES.turn(KNOB_E, units)


def chord(key: int, action: int) -> list[str]:
    return [f"press:{key}", "wait:5M", f"tap:{action}", "wait:5M", f"release:{key}", "wait:40M"]


def flags(track: int = 1) -> list[str]:
    """TRACK's 48 step flags"""
    return [f"peek:{PATTERN + TRACK_STRIDE * (track - 1):#x}:96"]


BOOT = wait(1500) + tap(NO) + wait(60)


def grid(trigs, locks=(), slds=(), locktrigs=(), extra=(), track: int = 1) -> list[str]:
    """In GRID RECORDING on the active track (TRACK): TRIGS, LOCKTRIGS ([FUNC] + [TRIG]), each lock
    (step, knob, units) on the FLTR page, EXTRA, then SLD (step, value, turns first on TRIG PAGE 2)
    with knob E; TRACK's flags peeked."""
    out = tap(RECORD) + wait(20)
    for t in trigs:
        out += tap(trig(t))
    for t in locktrigs:
        out += [f"press:{FUNC}"] + wait(10) + tap(trig(t)) + [f"release:{FUNC}"] + wait(40)
    out += tap(FLTR) + wait(40)
    for t, knob, units in locks:
        out += hold([t], ES.turn(knob, units))
    out += list(extra) + tap(TRIG_PAGE) + wait(60) + tap(TRIG_PAGE) + wait(60)
    for t, value, first in slds:
        out += hold([t], list(first) + knob_e(value + (value == NEXT)))
    return out + tap(RECORD) + wait(30) + flags(track)


def machine(direction: int) -> list[str]:
    """The track's machine one up or down in MACHINE SEL ([FUNC] + [SYN])."""
    return ([f"press:{FUNC}", "wait:20M", f"tap:{SYN}", "wait:40M", f"release:{FUNC}", "wait:60M"]
            + tap(direction) + wait(40) + tap(YES) + wait(200) + tap(NO) + wait(60))


# PRESET, POOL, the first slot, SAVE TO HERE, the name, <SAVE>
POOL_SAVE = (tap(PRESET) + wait(60) + (tap(DOWN) + wait(20)) * 3 + tap(YES) + wait(120) + tap(RIGHT) + wait(60)
             + (tap(YES) + wait(200)) * 3 + tap(NO) + wait(60))
def preset_lock(step: int) -> list[str]:
    """STEP held: LEVEL/DATA opens the pool list (10 then 28 counts) and moves to slot 001 (7)"""
    return [f"press:{trig(step)}", "wait:40M", f"turn:{LEVEL}:10", "wait:60M", f"turn:{LEVEL}:28", "wait:60M",
            f"turn:{LEVEL}:7", "wait:60M", f"release:{trig(step)}", "wait:60M"]


PRESET_LOCK_5 = preset_lock(5)


def per_track_2x(track: int) -> list[str]:
    """Per-track mode on, TRACK at 2x (speed 0 of the ticks table): pattern pokes while stopped"""
    return [f"poke:{PATTERN + SCALE_MODE:#x}:01", f"poke:{PATTERN + TRACK_STRIDE * (track - 1) + TRACK_SCALE:#x}:00"]
RETRIG = ES.turn(KNOB_A, 3) + ES.turn(KNOB_D, 4) + ES.turn(3, 10)        # RTRG on, RATE, LEN
# Page Loop on page 1 in GRID RECORDING ([PAGE] held, [TRIG 9])
PAGE_LOOP_1 = [f"press:{PAGE}", "wait:60M", f"press:{trig(9)}", "wait:20M", f"release:{trig(9)}", "wait:20M",
               f"release:{PAGE}", "wait:40M"]
def long_note(step: int) -> list[str]:
    """STEP's note 60 units longer in NOTE EDIT ([TRIG] held, [STACK]; [FUNC] + knob G)"""
    return ([f"press:{trig(step)}", "wait:40M", f"tap:{STACK}", "wait:60M", f"release:{trig(step)}", "wait:30M",
             f"press:{FUNC}"] + ES.turn(KNOB_G, 60) + [f"release:{FUNC}", "wait:30M"] + tap(NO) + wait(40))


LONG_5 = long_note(5)
def note_chord(step: int) -> list[str]:
    """STEP's note made a chord of three in NOTE EDIT ([TRIG] held, [STACK]): two notes added up 4 and 3"""
    return ([f"press:{trig(step)}", "wait:40M", f"tap:{STACK}", "wait:60M", f"release:{trig(step)}", "wait:30M"]
            + [s for semis in (4, 3) for s in [f"press:{FUNC}", f"tap:{DOWN}", f"release:{FUNC}", "wait:40M"]
               + ES.turn(KNOB_E, semis) + ["wait:30M"]] + tap(NO) + wait(40))


NOTE_CHORD_5 = note_chord(5)
ARP_UP = tap(ARP) + wait(40) + ES.turn(KNOB_A, 2) + wait(20) + tap(NO) + wait(40)
# arpplocks' arp state for track 1, the sound the ISR reads SPEED and N.LEN from, and its shadow sound
ARP_STATE, ARP_SOUNDS, ARPPLOCKS_SHADOW = 0x405984A8, 0x4058E8D8, 0x467C0000
ARP_LOCK_5 = tap(ARP) + wait(40) + hold([5], ES.turn(KNOB_A, 1)) + tap(NO) + wait(40)   # arpplocks: MODE on step 5
DIRECT_JUMP_ON = tap(PTN) + wait(40) + tap(UP) + wait(30) + tap(NO) + wait(40)        # directjump's switch
# A02 (selected at once while stopped) gets a trig on every step, then A01 again
A02_EVERY_STEP = (tap(PTN) + wait(40) + tap(trig(2)) + wait(80) + tap(RECORD) + wait(20)
                  + [s for n in range(1, 17) for s in tap(trig(n))] + tap(RECORD) + wait(30)
                  + tap(PTN) + wait(40) + tap(trig(1)) + wait(80))
WAVERIDER = ([f"press:{FUNC}", "wait:20M", f"tap:{SYN}", "wait:40M", f"release:{FUNC}", "wait:60M"]
             + (tap(DOWN) + wait(40)) * 4 + tap(YES) + wait(200) + tap(NO) + wait(60))    # MACHINE SEL's fifth
# LFO 4 ([MOD] four times from another page) aimed one step into DEST (FM DRUM's TUNE), DEPTH 3 units up:
# it moves TUNE without reaching the clamp
LFO4_TUNE = (tap(MOD) + wait(30)) * 4 + ES.turn(KNOB_D, 1) + tap(YES) + wait(20) + ES.turn(8, 3) + tap(NO) + wait(40)
MONO = tap(VOICE) + wait(60) + ES.turn(KNOB_E, 1) + tap(NO) + wait(40)    # VOICE SETUP: VOICES 1
# VOICE SETUP: UNISON's STATE on (knob F) and V.AMNT 3 (knob G, from 2)
UNISON_3 = tap(VOICE) + wait(60) + ES.turn(6, 1) + wait(20) + ES.turn(7, 1) + tap(NO) + wait(40)
# step 5 held on each of LFO 1 to 3's pages ([MOD] from the FLTR page, then again): SPD, FADE, SPH and DEP
# (knobs A, C, F and H) 10 units up
LFO_LOCKS_5 = [s for _ in range(3) for s in tap(MOD) + wait(40) + hold([5], [t for k in (1, 3, 6, 8)
                                                                         for t in ES.turn(k, 10)])]
# every knob of SYN pages 1 and 2, FLTR pages 1 and 2, AMP and FX turned up 2 units, step 5 held
# (a page key tapped on its own first page opens its second)
EVERY_KNOB_5 = [s for page in (SYN, SYN, FLTR, FLTR, AMP, FX)
                for s in tap(page) + wait(40) + hold([5], [t for k in range(1, 9) for t in ES.turn(k, 2)])]


def loop_pattern(loop: bool) -> list[str]:
    """32 steps: trigs 1, 9 and 25 (17 removed after the page copy), 9 locked +12 then NEXT, 25 at
    +6; with LOOP, Page Loop on page 1 ([PAGE] held, [TRIG 9])."""
    s = tap(RECORD) + wait(20) + tap(trig(1)) + tap(trig(9)) + tap(FLTR) + wait(40) + hold([9], ES.turn(KNOB_A, 12))
    s += chord(FUNC, PAGE) + tap(PAGE) + wait(40) + tap(NO) + wait(40)          # SEQUENCER PAGE SETUP: 32 steps
    s += tap(PAGE) + wait(40) + tap(trig(1)) + wait(30) + hold([9], ES.turn(KNOB_A, -6)) + tap(PAGE) + wait(40)
    s += tap(TRIG_PAGE) + wait(60) + tap(TRIG_PAGE) + wait(60) + hold([9], knob_e(NEXT + 1))
    if loop:
        s += [f"press:{PAGE}", "wait:60M", f"press:{trig(9)}", "wait:20M", f"release:{trig(9)}", "wait:20M",
              f"release:{PAGE}", "wait:40M"]
    return s + tap(RECORD) + wait(30) + flags()


# ---- runs ----

def clear_of_stalls(steps: list[str], start: int = STEPS_FROM, tap_span: int = TAP) -> list[str]:
    """STEPS from instruction START, each panel input put off past the UI stall it would fall in, so
    that none is lost. TAP_SPAN: a tap's instructions"""
    out, t = [], start
    for step in steps:
        kind, _, rest = step.partition(":")
        if kind in ("turn", "tap", "press", "release"):
            span = tap_span if kind == "tap" else 0
            k = max(0, (t - STALL_FIRST) // STALL_EVERY)
            for start in (STALL_FIRST + k * STALL_EVERY, STALL_FIRST + (k + 1) * STALL_EVERY):
                if start - STALL_MARGIN <= t + span and t < start + STALL_SPAN + STALL_MARGIN:
                    out.append(f"wait:{start + STALL_SPAN + STALL_MARGIN - t}")
                    t = start + STALL_SPAN + STALL_MARGIN
        out.append(step)
        if kind == "wait":
            t += int(rest[:-1]) * 1_000_000 if rest.endswith("M") else int(rest)
        elif kind == "tap":
            t += tap_span
    return out


def drive(image: pathlib.Path, steps: list[str], ssi: bool, counts: list[int], regs: tuple[int, ...] = (),
          capture: str | None = None) -> Run:
    cmd = [str(ES.panel_drive()), str(image), "--watch", FAULT_WATCH, "--steps", ",".join(clear_of_stalls(steps))]
    if ssi:
        cmd += ["--ssi-hz", "96000", "--capture", capture or f"{ES.EXCHANGE}:1:{FRAME_BYTES}"]
    if counts:
        cmd += ["--count", ",".join(f"{pc:#x}" for pc in counts)]
    if regs:
        cmd += ["--regs-at", ",".join(f"{pc:#x}" for pc in regs)]
    with tempfile.TemporaryDirectory() as out:
        done = subprocess.run(cmd + ["--out", out], capture_output=True, text=True)
        if not done.stdout.strip():
            raise SystemExit(f"panel_drive gave no result: {done.stderr[-300:]}")
        d = json.loads(done.stdout)
        screens = [screen(pathlib.Path(r["frame"])) for r in d.get("results", []) if "frame" in r]
    return run_of(d, counts, screens)


def run_of(d: dict, counts: list[int], screens: list) -> Run:
    """panel_drive's result D as a Run: the fault watches, the hits of COUNTS, and SCREENS, read from its
    `frame:` files"""
    watched = {int(w["pc"], 16): w["hits"] for w in d.get("watched", [])}
    faults = [watched.get(int(pc, 16), 0) for pc in FAULT_WATCH.split(",")]
    peeks = [r for r in d.get("results", []) if "peek" in r]
    return Run(d["outcome"], faults, [bytes.fromhex(c["hex"]) for c in d.get("captures", [])],
               [bytes.fromhex(r["hex"]) for r in peeks], {pc: n for pc, n in watched.items() if pc in set(counts)},
               [c["icount"] for c in d.get("captures", [])], [r["icount"] for r in peeks],
               [(int(r["pc"], 16), [int(v, 16) for v in r["d"]]) for r in d.get("regs", [])], d.get("regs_dropped", 0),
               screens)


# ---- the edits ----

COPY_TRIG = hold([1], tap(RECORD))
FREEZE = [f"press:{FUNC}", "wait:5M", "turn:4:-10", "wait:15M", "turn:4:-10", "wait:15M", "turn:4:-8", "wait:15M",
          f"release:{FUNC}", "wait:40M"]


@dataclasses.dataclass(frozen=True)
class Case:
    name: str
    steps: tuple[str, ...]
    check: Callable[[Run, Run], list[str]]
    sld: dict = dataclasses.field(default_factory=dict)     # step -> SLD the setup must have set
    ssi: bool = True
    stock_steps: tuple[str, ...] | None = None             # stock's own keys, when they differ
    on_stock_only: bool = False                             # both runs on stock
    clock_back: int = 0          # the step before which the clock is poked BACK (read in a first run)
    target_poke: tuple[int, Literal["start", "end", "after"]] | None = None  # split step, and where to write
    same_counts: tuple[int, ...] = ()   # instructions that must run as often on the build as on its control
    mods: tuple[str, ...] = ()   # other mods: the case runs on stock with them and pslide, against stock with them
    capture: str | None = None   # panel_drive's capture (pc:argument:bytes) in place of the frame to the DSP


BASE = ([1, 5], [(5, KNOB_A, 12)])
def select(track: int) -> list[str]:
    """[TRK] + [TRIG n]: TRACK becomes the active track"""
    return [f"press:{TRK}", "wait:10M", f"tap:{trig(track)}", f"release:{TRK}", "wait:30M"]


TRACK_2 = select(2)
def cases() -> list[Case]:
    """The cases, their keys made from this module's addresses when it is called (`main` moves them
    for a 1.12 build)"""
    # the edits: step 1 seeded 0x03e9
    edit = (BOOT + tap(RECORD) + wait(20) + tap(trig(1)) + tap(trig(5)) + wait(20) + [f"poke:{PATTERN:#x}:03e9"]
            + wait(20))
    arp_peeks = [f"peek:{ARP_STATE:#x}:40", f"peek:{ARP_SOUNDS:#x}:4", f"peek:{ARPPLOCKS_SHADOW:#x}:1164"]
    clock_back = BOOT + grid(*BASE, [(5, 6, ())]) + tap(PLAY) + wait(150)
    clock_back_at = len(clock_back)
    clock_back += wait(300)
    knob_end = BOOT + grid(*BASE, [(5, 4, ())]) + tap(PLAY) + wait(10)
    knob_end_at = len(knob_end)
    knob_end += wait(300)
    knob_start = BOOT + MONO + grid(*BASE, [(5, 4, ())]) + tap(PLAY) + wait(10)
    knob_start_at = len(knob_start)
    knob_start += wait(200)
    knob_after = (BOOT + grid([1, 5], [(5, KNOB_A, 12), (5, KNOB_B, 6)], [(5, 4, ())], extra=NOTE_CHORD_5) + tap(PLAY)
                  + wait(10))
    knob_after_at = len(knob_after)
    knob_after += wait(200)
    mutes = [s for n in range(1, 16) for s in chord(FUNC, trig(n))]   # tracks 1 to 15 muted, or unmuted
    conditions = BOOT + grid([1, 5, 6, 7, 8, 9], [(5, KNOB_A, 12), (6, KNOB_A, 4), (7, KNOB_A, 12), (8, KNOB_A, 4),
                                                  (9, KNOB_A, 12)], [(1, NEXT, ())] + [(n, 2, ()) for n in range(5, 10)])
    return [
        Case("length-half", tuple(BOOT + grid(*BASE, [(5, 1, ())]) + tap(PLAY) + wait(100)), check_length(0.5), {5: 1}),
        Case("length-2", tuple(BOOT + grid(*BASE, [(5, 3, ())]) + tap(PLAY) + wait(120)), check_length(2), {5: 3}),
        Case("length-8", tuple(BOOT + grid(*BASE, [(5, 5, ())]) + tap(PLAY) + wait(300)), check_length(8), {5: 5}),
        Case("length-16", tuple(BOOT + grid(*BASE, [(5, 6, ())]) + tap(PLAY) + wait(400)), check_length(16), {5: 6}),
        Case("return", tuple(BOOT + grid([1, 5, 9], [(5, KNOB_A, 12)], [(9, 2, ())]) + tap(PLAY) + wait(200)),
             check_return, {9: 2}),
        Case("next", tuple(BOOT + grid(*BASE, [(1, NEXT, ())]) + tap(PLAY) + wait(150)), check_next, {1: NEXT}),
        Case("next-micro", tuple(BOOT + grid(*BASE, [(1, NEXT, ())], extra=hold([5], (tap(RIGHT) + wait(20)) * 6))
                                 + tap(PLAY) + wait(150)), check_next_micro, {1: NEXT}),
        Case("next-track-2", tuple(BOOT + TRACK_2 + grid(*BASE, [(1, NEXT, ())], track=2) + tap(PLAY) + wait(150)),
             check_next_track_2, {1: NEXT}),
        Case("next-track-length", tuple(BOOT + grid([1, 5], [(5, KNOB_A, 12), (5, KNOB_B, 6)], [(5, NEXT, ())])
                                        + [f"poke:{PATTERN + SCALE_MODE:#x}:01", f"poke:{PATTERN + TRACK_LENGTH:#x}:0008"]
                                        + tap(PLAY) + wait(250)), check_next_track_length, {5: NEXT}),
        Case("next-loop-alone", tuple(BOOT + grid([1], [(1, KNOB_A, 12)], [(1, NEXT, ())], extra=PAGE_LOOP_1) + tap(PLAY)
                                      + wait(250)), check_next_alone, {1: NEXT}),
        Case("next-alone", tuple(BOOT + grid([1], [(1, KNOB_A, 12)], [(1, NEXT, ())]) + tap(PLAY) + wait(250)),
             check_next_alone, {1: NEXT}),
        Case("next-track-12", tuple(BOOT + select(12) + grid(*BASE, [(1, NEXT, ())], track=12) + tap(PLAY)
                                    + wait(150)), check_next_track_2, {1: NEXT}),
        Case("length-track-12", tuple(BOOT + select(12) + grid(*BASE, [(5, 4, ())], track=12) + tap(PLAY)
                                      + wait(150)), check_length(4), {5: 4}),
        Case("speed-track-2", tuple(BOOT + TRACK_2 + grid(*BASE, [(5, 4, ())], track=2) + per_track_2x(2)
                                    + tap(PLAY) + wait(150)), check_speed, {5: 4}),
        Case("preview-sld-off", tuple(BOOT + grid([1, 5], [(1, KNOB_A, 12)], [(1, 4, ())]) + tap(RECORD) + wait(20)
                                      + hold([1], knob_e(-8)) + tap(RECORD) + wait(30) + flags() + tap(PLAY)
                                      + wait(150)), check_preview_off),
        Case("next-length", tuple(BOOT + loop_pattern(False) + tap(PLAY) + wait(500)), check_next_loop(16, False),
             {9: NEXT}),
        Case("next-loop", tuple(BOOT + loop_pattern(True) + tap(PLAY) + wait(500)), check_next_loop(8, True),
             {9: NEXT}),
        Case("knob", tuple(BOOT + grid(*BASE, [(5, 6, ())]) + tap(FLTR) + wait(30) + tap(PLAY) + wait(150)
                           + ["turn:1:10", "wait:2M"] * 3 + wait(300)), check_knob, {5: 6}),
        Case("knob-chord", tuple(BOOT + grid(*BASE, [(5, 6, ())], extra=NOTE_CHORD_5) + tap(FLTR) + wait(30) + tap(PLAY)
                                 + wait(150) + ["turn:1:10", "wait:2M"] * 3 + wait(300)), check_knob_chord, {5: 6}),
        Case("knob-end", tuple(knob_end), check_knob_end, {5: 4}, target_poke=(knob_end_at, "end")),
        Case("knob-start", tuple(knob_start), check_length(4), {5: 4}, target_poke=(knob_start_at, "start")),
        Case("knob-chord-after", tuple(knob_after), check_knob_after, {5: 4}, target_poke=(knob_after_at, "after")),
        Case("push", tuple(BOOT + grid([1, 9], [], [(1, 4, ()), (9, 4, ())]) + tap(RECORD) + wait(20) + tap(TRIG_PAGE)
                           + wait(60) + tap(TRIG_PAGE) + wait(60) + [f"press:{trig(9)}", "wait:60M", "frame:held"]
                           + [f"press:{PUSH_E}", "wait:40M"] + flags() + [f"release:{PUSH_E}", "wait:40M", "frame:off"]
                           + flags() + [f"release:{trig(9)}", "wait:40M"] + hold([1], tap(PUSH_E - 2)) + flags()
                           + hold([1], tap(PUSH_E + 1)) + flags() + tap(PUSH_E) + wait(40) + flags()
                           + (tap(SYN) + wait(60)) * 4 + hold([1], tap(PUSH_E)) + flags()), check_push, {1: 4, 9: 4},
             ssi=False),
        Case("knob-unheld", tuple(BOOT + tap(RECORD) + wait(20) + tap(trig(1)) + tap(TRIG_PAGE) + wait(60)
                                  + tap(TRIG_PAGE) + wait(60) + [f"turn:{KNOB_E}:10", "wait:15M"] * 2
                                  + hold([1], [f"turn:{KNOB_E}:10", "wait:15M"]) + flags()), check_unheld, ssi=False),
        Case("stop", tuple(BOOT + grid(*BASE, [(5, 6, ())]) + tap(PLAY) + wait(150) + tap(STOP) + wait(150)),
             check_stop, {5: 6}),
        Case("pattern", tuple(BOOT + grid([1, 9], [(9, KNOB_A, 12)], [(9, 6, ())]) + tap(PLAY) + wait(40)
                              + [f"press:{PTN}", "wait:10M", f"tap:{trig(2)}", f"release:{PTN}"] + wait(400)),
             check_pattern, {9: 6}),
        Case("tempo", tuple(BOOT + grid(*BASE, [(5, 6, ())]) + tap(PLAY) + wait(150) + tap(TEMPO) + wait(10)
                            + ["turn:1:-127", "wait:2M"] * 4 + wait(300) + [f"peek:{RATE:#x}:4"]), check_tempo, {5: 6}),
        Case("machine", tuple(BOOT + machine(DOWN) + POOL_SAVE + machine(UP)
                              + grid(*BASE, [(5, 4, ())], extra=()) + tap(RECORD) + wait(20) + PRESET_LOCK_5
                              + tap(RECORD) + wait(30) + tap(PLAY) + wait(200)), check_machine(False), {5: 4}),
        Case("machine-chord", tuple(BOOT + machine(DOWN) + POOL_SAVE + machine(UP)
                                    + grid(*BASE, [(5, 4, ())], extra=NOTE_CHORD_5) + tap(RECORD) + wait(20)
                                    + PRESET_LOCK_5 + tap(RECORD) + wait(30) + tap(PLAY) + wait(200)),
             check_machine_chord, {5: 4}),
        Case("next-preset-type", tuple(BOOT + machine(DOWN) + POOL_SAVE + machine(UP)
                                       + grid([1, 5, 9], [(5, KNOB_A, 12), (9, KNOB_A, 4)], [(5, NEXT, ())])
                                       + tap(RECORD) + wait(20) + PRESET_LOCK_5 + tap(RECORD) + wait(30)
                                       + tap(PLAY) + wait(250)), check_next_preset, {5: NEXT}),
        Case("machine-first", tuple(BOOT + machine(DOWN) + POOL_SAVE + machine(UP)
                                    + grid([1, 5], [(1, KNOB_A, 12)], [(1, 4, ())]) + tap(RECORD) + wait(20)
                                    + preset_lock(1) + tap(RECORD) + wait(30) + tap(PLAY) + wait(200)),
             check_first_preset, {1: 4}),
        Case("next-preset-first", tuple(BOOT + machine(DOWN) + POOL_SAVE + machine(UP)
                                        + grid([1, 5], [(1, KNOB_A, 12), (5, KNOB_A, 4)], [(1, NEXT, ())])
                                        + tap(RECORD) + wait(20) + preset_lock(1) + tap(RECORD) + wait(30)
                                        + tap(PLAY) + wait(200)), check_first_preset, {1: NEXT}),
        Case("next-preset-first-same", tuple(BOOT + machine(DOWN) + POOL_SAVE
                                             + grid([1, 5], [(1, KNOB_A, 12), (5, KNOB_A, 4)], [(1, NEXT, ())])
                                             + tap(RECORD) + wait(20) + preset_lock(1) + tap(RECORD) + wait(30)
                                             + tap(PLAY) + wait(200)), check_next, {1: NEXT}),
        Case("next-preset-same", tuple(BOOT + POOL_SAVE + grid([1, 5, 9], [(5, KNOB_A, 12), (9, KNOB_A, 4)],
                                                               [(5, NEXT, ())])
                                       + tap(RECORD) + wait(20) + PRESET_LOCK_5 + tap(RECORD) + wait(30)
                                       + tap(PLAY) + wait(250)), check_next_preset_same, {5: NEXT}),
        Case("locktrig-preset", tuple(BOOT + machine(DOWN) + POOL_SAVE + machine(UP)
                                      + grid([1], [(5, KNOB_A, 4)], [(5, 2, ())], locktrigs=[5]) + tap(RECORD)
                                      + wait(20) + preset_lock(1) + tap(RECORD) + wait(30) + tap(PLAY) + wait(250)),
             check_locktrig_preset, {5: 2}),
        Case("machine-same", tuple(BOOT + POOL_SAVE + grid([1, 5], [(5, KNOB_A, 12), (5, KNOB_B, 6)], [(5, 4, ())])
                                   + tap(RECORD) + wait(20) + PRESET_LOCK_5
                                   + tap(RECORD) + wait(30) + tap(PLAY) + wait(200)), check_machine(True), {5: 4}),
        Case("retrig", tuple(BOOT + grid(*BASE, [(5, 4, RETRIG)]) + tap(PLAY) + wait(200)), check_joins, {5: 4}),
        Case("retrig-dense", tuple(BOOT + grid(*BASE, [(5, 4, RETRIG)], extra=EVERY_KNOB_5) + tap(PLAY) + wait(200)),
             check_joins, {5: 4}),
        Case("chord", tuple(BOOT + grid(*BASE, [(5, 4, ())], extra=NOTE_CHORD_5) + tap(PLAY) + wait(200)),
             check_joins, {5: 4}),
        Case("unison", tuple(BOOT + UNISON_3 + grid(*BASE, [(5, 4, ())]) + tap(PLAY) + wait(200)), check_unison,
             {5: 4}),
        Case("arp", tuple(BOOT + grid(*BASE, [(5, 4, ())], extra=LONG_5) + ARP_UP + tap(PLAY) + wait(200)),
             check_joins, {5: 4}),
        Case("overlap", tuple(BOOT + grid([1, 5], [(1, KNOB_A, 12), (5, KNOB_A, 4)], [(1, 6, ()), (5, 4, ())])
                              + tap(PLAY) + wait(300)), check_overlap, {1: 6, 5: 4}),
        Case("locktrig", tuple(BOOT + grid([1], [(1, KNOB_A, 12), (5, KNOB_B, 6)], [(1, 6, ()), (5, 2, ())],
                                           locktrigs=[5]) + tap(PLAY) + wait(300)), check_locktrig(False),
             {1: 6, 5: 2}),
        Case("locktrig-off", tuple(BOOT + grid([1], [(1, KNOB_A, 12), (1, KNOB_B, 6), (5, KNOB_A, 4)],
                                               [(1, 6, ()), (3, 2, ())], locktrigs=[3, 5]) + tap(PLAY) + wait(300)),
             check_locktrig_off, {1: 6, 3: 2}),
        Case("locktrig-first", tuple(BOOT + grid([2], [(1, KNOB_A, 12)], [(1, 4, ())], locktrigs=[1]) + tap(PLAY)
                                     + wait(200)), check_locktrig_first, {1: 4}),
        Case("locktrig-next", tuple(BOOT + grid([1, 9], [(5, KNOB_B, 6), (9, KNOB_B, 2)], [(5, NEXT, ())],
                                                locktrigs=[5]) + tap(PLAY) + wait(300)), check_locktrig_next, {5: NEXT}),
        Case("locktrig-plain", tuple(BOOT + grid([1], [(5, KNOB_A, 4)], locktrigs=[5]) + tap(PLAY) + wait(250)),
             check_frames_stock),
        Case("locktrig-other-track", tuple(BOOT + TRACK_2 + grid([1], [(1, KNOB_A, 12)], [(1, 6, ())], track=2)
                                           + select(1) + grid([], [(5, KNOB_A, 4)], locktrigs=[5]) + tap(PLAY)
                                           + wait(300)), check_other_track),
        Case("locktrig-take", tuple(BOOT + grid([1], [(1, KNOB_A, 12), (5, KNOB_A, 4)], [(1, 6, ()), (5, 2, ())],
                                                locktrigs=[5]) + tap(PLAY) + wait(300)), check_locktrig(True),
             {1: 6, 5: 2}),
        Case("locktrig-take-chord", tuple(BOOT + grid([1], [(1, KNOB_A, 12), (5, KNOB_A, 4)], [(1, 6, ()), (5, 2, ())],
                                                      locktrigs=[5], extra=note_chord(1)) + tap(PLAY) + wait(300)),
             check_locktrig_chord, {1: 6, 5: 2}),
        Case("mono", tuple(BOOT + MONO + grid([1, 5], [(1, KNOB_A, 12)], [(1, 6, ())]) + tap(PLAY) + wait(250)),
             check_mono, {1: 6}),
        Case("mono-locktrig", tuple(BOOT + MONO + grid([1, 9], [(5, KNOB_B, 6)], [(5, 6, ())], locktrigs=[5])
                                    + tap(PLAY) + wait(250)), check_mono_locktrig, {5: 6}),
        Case("steal", tuple(BOOT + grid([1], [(1, KNOB_A, 12)], [(1, 6, ())]) + TRACK_2
                            + tap(RECORD) + wait(20) + [t for n in range(1, 17) for t in tap(trig(n))] + tap(RECORD)
                            + wait(30) + tap(PLAY) + wait(300)), check_steal, {1: 6}),
        Case("takeover", tuple(BOOT + grid([1], [(n, KNOB_A, 12 if n % 2 == 0 else 4) for n in range(2, 10)],
                                           [(n, 6, ()) for n in range(2, 10)], locktrigs=list(range(2, 10)))
                               + tap(PLAY) + wait(250)), check_takeover, {n: 6 for n in range(2, 10)}),
        Case("pool", tuple(BOOT + grid([1], [(n, n - 1, 6) for n in range(2, 9)], [(n, 6, ()) for n in range(2, 9)],
                                       locktrigs=list(range(2, 9))) + tap(PLAY) + wait(400)), check_pool,
             {n: 6 for n in range(2, 9)}),
        Case("conditions", tuple(conditions + [f"poke:{PATTERN + CONDITIONS + 4:#x}:{bytes([LST] * 5).hex()}"]
                                 + tap(PLAY) + wait(200)), check_conditions, {1: NEXT, 5: 2, 9: 2},
             stock_steps=tuple(conditions + tap(PLAY) + wait(200))),
        Case("every-step", tuple(BOOT + grid(list(range(1, 17)), slds=[(n, 2, ()) for n in range(1, 17)],
                                             extra=hold(range(1, 17), ES.turn(KNOB_A, FULL_PARAMETER_TURN))
                                             + hold(range(2, 17, 2), ES.turn(KNOB_A, -FULL_PARAMETER_TURN)))
                                 + tap(PLAY) + wait(560)
                                 + tap(STOP) + wait(60)), check_every_step, {n: 2 for n in range(1, 17)},
             same_counts=(LIST_FREED,)),
        Case("muted", tuple(BOOT + grid(list(range(1, 17)), [(n, KNOB_A, 12 if n % 2 else 4) for n in range(1, 17)],
                                        [(n, 2, ()) for n in range(1, 17)]) + tap(PLAY) + wait(60)
                            + chord(FUNC, trig(1)) + wait(300) + chord(FUNC, trig(1)) + wait(150)), check_muted,
             {n: 2 for n in range(1, 17)}),
        Case("muted-tracks", tuple(BOOT + grid(list(range(1, 17)), [(5, KNOB_A, 12)], [(n, 2, ()) for n in range(1, 17)])
                                   + tap(RECORD) + wait(20) + chord(FUNC, RECORD)
                                   + [s for n in range(2, 17) for s in chord(TRK, trig(n)) + chord(FUNC, STOP)]
                                   + tap(RECORD) + wait(30) + mutes + tap(PLAY) + wait(450) + mutes + wait(200)),
             check_same_notes, {5: 2}, same_counts=(LISTED,)),
        Case("next-chords", tuple(BOOT + grid([1, 5], [(5, KNOB_A, 12)], [(1, NEXT, ())], extra=note_chord(1))
                                  + tap(RECORD) + wait(20) + chord(FUNC, RECORD)
                                  + [s for n in range(2, 17) for s in chord(TRK, trig(n)) + chord(FUNC, STOP)]
                                  + tap(RECORD) + wait(30) + tap(PLAY) + wait(200)), check_same_notes, {1: NEXT},
             same_counts=(LISTED,)),
        Case("no-lists", tuple(BOOT + grid(*BASE, [(5, 4, ())]) + [f"poke:{LIST_HEAD:#x}:00000000"] + tap(PLAY)
                               + wait(450)), check_same_notes, {5: 4}, same_counts=(LISTED,)),
        Case("stop-first", tuple(BOOT + grid([1, 5], [(1, KNOB_A, 12)], [(1, 4, ())]) + tap(PLAY) + wait(150)
                                 + tap(STOP) + wait(100) + tap(PLAY) + wait(150)), check_stop_first, {1: 4}),
        Case("stop-return", tuple(BOOT + grid([1, 9], [], [(1, 3, ()), (9, 4, ())],
                                              extra=tap(AMP) + wait(40) + hold([9], ES.turn(KNOB_H, -40)))
                                  + tap(PLAY) + wait(225) + tap(STOP) + wait(100) + tap(PLAY) + wait(150)),
             check_stop_return, {1: 3, 9: 4}),
        Case("stop-pending", tuple(BOOT + grid(*BASE, [(5, 4, ())]) + tap(PLAY) + wait(46) + tap(STOP) + wait(100)
                                   + tap(PLAY) + wait(200)), check_stop_pending, {5: 4}),
        Case("arpplocks", tuple(BOOT + ARP_UP + grid([1], [(1, KNOB_A, 12), (5, KNOB_B, 6)], [(1, 6, ()), (5, 2, ())],
                                                     locktrigs=[5], extra=long_note(1) + ARP_LOCK_5)
                                + tap(PLAY) + wait(300) + arp_peeks), check_arpplocks, {1: 6, 5: 2},
             mods=("arpplocks",), same_counts=(APPLIER,)),
        Case("directjump", tuple(BOOT + A02_EVERY_STEP + grid([1, 9], [(9, KNOB_A, 12)], [(9, 6, ())]) + DIRECT_JUMP_ON
                                 + tap(PLAY) + wait(150) + tap(PTN) + wait(6) + tap(trig(2)) + wait(300)),
             check_direct_jump, {9: 6}, mods=("directjump",)),
        Case("directjump-late", tuple(BOOT + A02_EVERY_STEP + grid([1, 9], [(9, KNOB_A, 12)], [(9, 6, ())])
                                      + DIRECT_JUMP_ON + tap(PLAY) + wait(200) + tap(PTN) + wait(6) + tap(trig(2))
                                      + wait(300)), check_direct_jump, {9: 6}, mods=("directjump",)),
        Case("waverider", tuple(BOOT + WAVERIDER + grid(*BASE, [(5, 4, ())]) + tap(PLAY) + wait(150)), check_length(4),
             {5: 4}, mods=("waverider",)),
        Case("lfo4", tuple(BOOT + machine(DOWN) + LFO4_TUNE + grid([1, 5], [], [(5, 3, ())], extra=tap(SYN) + wait(40)
                                                                          + hold([5], ES.turn(KNOB_A, 6)))
                           + tap(PLAY) + wait(200)), check_lfo4, {5: 3}, mods=("lfo4",)),
        Case("lfo-locks", tuple(BOOT + grid([1, 5], [], [(5, 4, ())], extra=LFO_LOCKS_5) + tap(PLAY) + wait(200)),
             check_lfo_locks, {5: 4}, capture=f"{LFO_EVALUATOR:#x}:0:{LFO_CAPTURE}"),
        Case("residual", tuple(BOOT + grid(*BASE, [(5, 4, ())], extra=tap(SYN) + wait(40)
                                           + hold([5], ES.turn(KNOB_A, 2)))
                               + tap(PLAY) + wait(200)), check_residual, {5: 4}),
        Case("restore-residual", tuple(BOOT + MONO + grid([1, 5], [(5, KNOB_A, 12)], [(5, 2, ())],
                                                          extra=tap(SYN) + wait(40) + hold([1], ES.turn(KNOB_A, 2)))
                                       + tap(PLAY) + wait(250)), check_restore_residual, {5: 2}),
        Case("whole-sound", tuple(BOOT + POOL_SAVE + tap(AMP) + wait(40)
                                 + ES.turn(KNOB_H, -FULL_PARAMETER_TURN) + MONO + grid(*BASE, [(5, 4, ())])
                                 + tap(RECORD) + wait(20) + PRESET_LOCK_5 + tap(RECORD) + wait(30)
                                 + tap(PLAY) + wait(200)), check_whole_sound, {5: 4}),
        Case("dense", tuple(BOOT + grid([1], [], [(5, 3, ())], locktrigs=[5], extra=EVERY_KNOB_5) + tap(PLAY)
                            + wait(200)), check_dense, {5: 3}),
        Case("clock-back", tuple(clock_back), check_clock_back, {5: 6}, clock_back=clock_back_at),
        Case("control", tuple(BOOT + tap(RECORD) + wait(20) + tap(trig(1)) + tap(trig(5)) + tap(TRIG_PAGE) + wait(60)
                              + tap(TRIG_PAGE) + wait(60) + hold([1], knob_e(3)) + hold([5], knob_e(8))
                              + flags() + hold([1, 5], knob_e(-1)) + flags() + knob_e(5) + flags()
                              + hold([1], knob_e(-5)) + flags()
                              + tap(TRIG_PAGE) + wait(60) + hold([5], ES.turn(KNOB_E, 1)) + flags()
                              + chord(FUNC, PAGE) + tap(PAGE) + wait(40) + tap(PAGE) + wait(40) + tap(NO) + wait(40)
                              + tap(PAGE) + wait(40) + tap(PAGE) + wait(40) + tap(trig(1)) + wait(30)
                              + tap(TRIG_PAGE) + wait(60) + hold([1], knob_e(2))      # (from TRIG PAGE 1)
                              + flags()), check_control, ssi=False),
        Case("copy-paste", tuple(edit + COPY_TRIG + hold([9], tap(STOP)) + flags()), check_words({9: SLD_BITS}),
             ssi=False),
        Case("copy-two", tuple(edit + [f"poke:{PATTERN + 8:#x}:0021"] + hold([1, 5], tap(RECORD)) + hold([9], tap(STOP))
                               + flags()), check_words({9: SLD_BITS, 13: 0x0020}), ssi=False),
        Case("freeze", tuple(edit + chord(FUNC, AMP) + ES.turn(KNOB_A, 4) + ES.turn(KNOB_D, 1) + FREEZE + flags()),
             check_words({}, tuple(range(1, 17))), ssi=False),
        Case("freeze-rotated", tuple(edit + chord(FUNC, AMP) + ES.turn(KNOB_A, 1) + ES.turn(KNOB_G, 1)
                                     + ES.turn(KNOB_D, 1) + FREEZE + flags()), check_words({3: SLD_BITS}), ssi=False),
        Case("remove", tuple(edit + tap(trig(1)) + wait(40) + tap(trig(1)) + wait(40) + flags()),
             check_words({1: 0}), ssi=False),
        Case("clear", tuple(edit + [f"poke:{PATTERN:#x}:83e9"] + hold([1], tap(PLAY)) + flags()),
             check_words({1: 0}), ssi=False),
        Case("note-edit-undo", tuple(edit + hold([1], tap(STACK)) + chord(FUNC, PLAY) + flags() + chord(FUNC, PLAY)
                                     + flags()), check_undo, ssi=False),
        Case("shift", tuple(edit + chord(FUNC, RIGHT) + flags()), check_words({}, tuple(range(1, 17))), ssi=False),
        Case("page-paste", tuple(edit + chord(PAGE, RECORD) + chord(FUNC, PAGE) + tap(PAGE) + wait(40) + tap(NO)
                                 + wait(40) + tap(PAGE) + wait(40) + chord(PAGE, PLAY) + chord(PAGE, STOP)
                                 + [f"peek:{PATTERN + 32:#x}:64"]), check_words({}, tuple(range(1, 17))), ssi=False),
        Case("track-paste", tuple(edit + chord(FUNC, RECORD) + chord(TRK, trig(2)) + chord(FUNC, STOP)
                                  + [f"peek:{PATTERN + 1701:#x}:64"]), check_words({}, tuple(range(1, 17))), ssi=False),
        Case("stock-plays", tuple(BOOT + grid(*BASE) + [f"poke:{PATTERN:#x}:03e9", f"poke:{PATTERN + 8:#x}:03e9"]
                                  + flags() + tap(PLAY) + wait(200)), check_stock_plays,
             stock_steps=tuple(BOOT + grid(*BASE) + flags() + tap(PLAY) + wait(200)), on_stock_only=True),
        Case("stock-reload", tuple(edit + [f"poke:{PATTERN + 8:#x}:0021"] + flags() + chord(FUNC, YES) + wait(60)
                                   + [f"poke:{PATTERN:#x}:0000", f"poke:{PATTERN + 8:#x}:0000"] + flags()
                                   + chord(FUNC, NO) + wait(60) + flags()), check_stock_reload, ssi=False,
             on_stock_only=True),
    ]


# ---- a case on two images ----

def problems_of(case: Case, b: Run, s: Run) -> list[str]:
    out = [f"{who}: {run.outcome}, fault reporter {run.faults[0]}, upload refusal {run.faults[1]}"
           for who, run in (("build", b), ("stock", s)) if run.outcome != "done" or any(run.faults)]
    if out:
        return out
    for step, value in case.sld.items():           # the setup's SLD, read before PLAY
        if sld(b.word(0, step)) != value or sld(s.word(0, step)) != 0:
            return [f"setup: step {step} SLD {sld(b.word(0, step))}, stock {sld(s.word(0, step))}, not {value}"]
    out = [f"{pc:#010x} runs {b.counts.get(pc)} times on the build, {s.counts.get(pc)} on its control"
           for pc in case.same_counts if b.counts.get(pc) != s.counts.get(pc)]
    try:
        return out + case.check(b, s)
    except (IndexError, StopIteration, ValueError) as exc:
        return out + [f"the frames do not fit the case: {type(exc).__name__} {exc}"]


def keys(case: Case, image: pathlib.Path, steps: tuple[str, ...], build: bool = True) -> list[str]:
    """STEPS, with the clock poked BACK where the case says, from its value there in a first run
    (the emulator is deterministic, so the second run reaches the same value). On a BUILD, with
    TARGET_POKE: the first run finds step 5's voice and the requested slide boundary. The second
    writes that voice's target of knob A (as a knob writes it) in the frame before that boundary, or
    with "after", each voice's of step 5's chord in the frame after the chord's"""
    if case.clock_back:
        head, tail = list(steps[:case.clock_back]), list(steps[case.clock_back:])
        clock = int.from_bytes(drive(image, head + [f"peek:{CLOCK:#x}:4"], case.ssi, []).peeks[-1], "big")
        return head + [f"poke:{CLOCK:#x}:{(clock - BACK) % 2 ** 32:08x}"] + tail
    if case.target_poke is not None and build:
        split, boundary = case.target_poke
        head, tail = list(steps[:split]), list(steps[split:])
        first = drive(image, head + [f"peek:{CLOCK:#x}:4"] + tail, case.ssi, [])
        k, v = first.note(1)
        frame, voices = k, [v]
        if boundary == "end":
            series = first.series(v, SLOT_A)
            frame = next(f for f in range(k, len(series)) if series[f] == series[-1])
        elif boundary == "after":
            frame, voices = k + 1, first.voices(1)
        at = first.icounts[first.first + frame - 1] + POST_EXCHANGE_DELAY
        pokes = [f"poke:{SRC + 2 * (17 + 101 * x + SLOT_A):#x}:{END_POKE:04x}" for x in voices]
        return head + [f"wait:{at - first.peek_at[-1]}"] + pokes + tail
    return list(steps)


def run_case(case: Case, build: pathlib.Path, stock: pathlib.Path, counts: list[int],
             stock_runs: dict, regs: tuple[int, ...] = ()) -> tuple[list[str], Run]:
    image = stock if case.on_stock_only else build
    same = list(case.same_counts)
    b = drive(image, keys(case, image, case.steps), case.ssi, ([] if case.on_stock_only else counts) + same,
              () if case.on_stock_only else regs, case.capture)
    if case.on_stock_only and case.stock_steps is None:
        return problems_of(case, b, b), b
    if case.name not in stock_runs:
        stock_runs[case.name] = drive(stock, keys(case, stock, case.stock_steps or case.steps, False), case.ssi,
                                      same, (), case.capture)
    return problems_of(case, b, stock_runs[case.name]), b


def compose(mods: tuple[str, ...], folder: pathlib.Path, source: pathlib.Path = STOCK_ZIP) -> pathlib.Path:
    """SOURCE (stock) with MODS, as `dnfw mods apply` makes it, in FOLDER"""
    out = folder / ("+".join(mods) + ".syx")
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        failed = cli_main(["mods", "apply", *[x for m in mods for x in ("--mod", m)], str(source), "-o", str(out)])
    if failed or not out.exists():
        raise NotApplicable(f"dnfw mods apply {' '.join(mods)} failed on {source.name}")
    return out


class NotApplicable(Exception):
    """`dnfw mods apply` refused the mods on the stock image"""


def pair(case: Case, build: pathlib.Path, stock: pathlib.Path, images: dict) -> tuple[pathlib.Path, pathlib.Path]:
    """(the image the case runs on, its control): BUILD and STOCK, or stock with the case's mods and
    pslide and stock with its mods"""
    return (images[case.mods + ("pslide",)], images[case.mods]) if case.mods else (build, stock)


# ---- the chunk: controls and branch counts ----



def chunk_of(image: pathlib.Path):
    """(the firmware, its MAIN OS split from the area, the area's chunks, the index of pslide's
    CODE chunk), refusing an image whose chunk is not pslide_code.json's"""
    firmware = load(read_image(image))
    original, chunks = platform.split(firmware.container.find(pslide.SECTION).unpack())
    found = [i for i, (cid, data) in enumerate(chunks)
             if cid == area.CODE and area.CodeChunk.unpack(data).load == BR.CODE_VA]
    if len(found) != 1 or area.CodeChunk.unpack(chunks[found[0]][1]).image[:len(BR.BLOB)] != BR.BLOB:
        raise SystemExit(f"{image} has no CODE chunk at {BR.CODE_VA:#x} equal to pslide_code.json's")
    return firmware, original, chunks, found[0]


def control_image(build: pathlib.Path, label: str, folder: pathlib.Path) -> pathlib.Path:
    """BUILD with the instruction at LABEL replaced by NOPs"""
    firmware, original, chunks, i = chunk_of(build)
    code = area.CodeChunk.unpack(chunks[i][1])
    at = BR.LABELS[label] - BR.CODE_VA
    size = objdump.disassemble(code.image[at:at + 8], BR.LABELS[label])[0].size
    image = bytearray(code.image)
    image[at:at + size] = bytes.fromhex("4e71") * (size // 2)
    chunks[i] = (area.CODE, area.CodeChunk(code.load, bytes(image), code.bss, code.init).pack())
    section = firmware.container.find(pslide.SECTION)
    content = platform.join(original, chunks)
    out = folder / f"control-{label}-{build.stem}.syx"
    out.write_bytes(fwbuild.build(firmware, {pslide.SECTION: compress(section.id, section.dest, content)}))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("build", type=pathlib.Path)
    ap.add_argument("--stock", type=pathlib.Path, help="stock of the build's OS (default: the user's own)")
    ap.add_argument("--case", action="append", choices=[c.name for c in cases()], help="only these cases")
    ap.add_argument("--controls", action="store_true", help="also run each NOP control's case")
    ap.add_argument("--coverage", action="store_true", help="count each conditional branch both ways")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    a = ap.parse_args()
    os_version = specs.of_firmware(load(read_image(a.build)))
    if os_version not in SOURCES:
        raise SystemExit(f"no test addresses for OS {os_version}")
    a.stock = a.stock or (STOCK if os_version == "1.11" else SOURCES[os_version])
    moved = {}
    if os_version == "1.12":
        ES.use(os_version)
        moved = {sys.modules[__name__]: ON_1_12,
                 C: {"LIST_FREED": ON_1_12["LIST_FREED"], "LISTED": ON_1_12["LISTED"]},
                 BR: {"BLOB": bytes.fromhex(pslide.SPECS[os_version]["code"]["blob"])}}
    with osport.retarget(os_version, [sys.modules[__name__], C, BR], moved):
        print(f"OS {os_version}: stock {a.stock.name}, pattern {PATTERN:#010x}, exchange {ES.EXCHANGE}, "
              f"watch {FAULT_WATCH}")
        return run_all(a, SOURCES[os_version])


def run_all(a: argparse.Namespace, source: pathlib.Path) -> int:
    """The cases A names on A.build against A.stock, the mods' images composed from SOURCE"""
    every = cases()
    chosen = [c for c in every if not a.case or c.name in a.case]
    chunk_of(a.build)
    points, ways = branches() if a.coverage else ([], {})
    counts = counted(points, ways)
    stock_runs: dict[str, Run] = {}
    with tempfile.TemporaryDirectory() as scratch:
        folder = pathlib.Path(scratch)
        images, refused = compose_images(chosen + ([c for c in every if c.name in CONTROLS.values()]
                                                   if a.controls else []), folder, source)
        if refused:
            print("not run: " + ", ".join(c.name for c in chosen if c.mods in refused)
                  + f" ({', '.join('+'.join(m) for m in sorted(refused))} does not apply to {source.name})")
            chosen = [c for c in chosen if c.mods not in refused]
        regs = tuple(loop_tests(points))
        with ThreadPoolExecutor(a.jobs) as pool:
            results = list(pool.map(lambda c: run_case(c, *pair(c, a.build, a.stock, images), counts, stock_runs,
                                                       regs), chosen))
        failed = report_cases(chosen, results)
        if a.coverage:
            failed += report_coverage(points, ways, counts, results)
        if a.controls:
            failed += run_controls({c.name: c for c in every if c.mods not in refused}, a, images, folder,
                                   stock_runs)
    return 1 if failed else 0


def compose_images(needed: list[Case], folder: pathlib.Path, source: pathlib.Path) -> tuple[dict, set]:
    """Each set of other mods that NEEDED's cases run with, alone and with pslide, composed from
    SOURCE: (the images, the sets that do not apply to SOURCE, such as a mod with no build for its OS)"""
    images, refused = {}, set()
    for mods in {c.mods for c in needed if c.mods}:
        try:
            for m in (mods, mods + ("pslide",)):
                images[m] = compose(m, folder, source)
        except NotApplicable:
            refused.add(mods)
            continue
        chunk_of(images[mods + ("pslide",)])
    return images, refused


def report_cases(chosen: list[Case], results: list[tuple[list[str], Run]]) -> int:
    """Each case's verdict and its problems: -> how many failed"""
    for case, (found, _) in zip(chosen, results):
        print(f"{case.name:15s} {'FAIL' if found else 'ok'}" + "".join(f"\n    {p}" for p in found))
    return sum(bool(found) for found, _ in results)


def report_coverage(points: list[tuple[int, int, int]], ways: dict[int, set], counts: list[int],
                    results: list[tuple[list[str], Run]]) -> int:
    """How many of the chunk's conditional branches ran both ways over RESULTS (`edges`, seeded by
    the loop tests' registers), and each that did not or whose ways the counts cannot tell apart:
    -> how many those are"""
    hits = {pc: sum(run.counts.get(pc, 0) for _, run in results) for pc in counts}
    names = sorted((v, k) for k, v in BR.LABELS.items())
    loops = loop_tests(points)
    runs = [run for _, run in results]
    seeded = seeds(loops, runs)
    if any(run.regs_dropped for run in runs):      # lower bounds: they show a way ran, not its count
        print("(a run dropped logged hits: the loop tests' counts are lower bounds and seed nothing)")
        solved = edges(points, ways, hits) | {at: (seeded[0][at], seeded[1][at]) for at in seeded[0]}
    else:
        solved = edges(points, ways, hits, seeded)
    found = [(point, solved[point[0]]) for point in points]
    open_ = [(point, ways_run) for point, ways_run in found if None in ways_run or 0 in ways_run]
    print(f"\nbranches: {len(points) - len(open_)} of {len(points)} ran both ways, each way counted apart")
    for (at, _, _), (taken, not_taken) in open_:
        label = max((n for n in names if n[0] <= at), default=(BR.CODE_VA, "?"))
        print(f"    {at:#x} ({label[1]} + {at - label[0]}): taken {'?' if taken is None else taken}, "
              f"not taken {'?' if not_taken is None else not_taken}")
    return len(open_)


def run_controls(by_name: dict[str, Case], a: argparse.Namespace, images: dict, folder: pathlib.Path,
                 stock_runs: dict) -> int:
    """Each NOP control's case on its control image (CONTROLS): -> how many pass, which each must not"""
    controls = {label: name for label, name in CONTROLS.items() if name in by_name}
    runs = {label: pair(by_name[name], a.build, a.stock, images) for label, name in controls.items()}
    nops = {label: (control_image(runs[label][0], label, folder), runs[label][1]) for label in controls}
    with ThreadPoolExecutor(a.jobs) as pool:
        found = list(pool.map(lambda lc: run_case(by_name[lc[1]], *nops[lc[0]], [], stock_runs)[0],
                              controls.items()))
    print()
    for (label, name), problems in zip(controls.items(), found):
        print(f"control {label:10s} ({name}): " + (f"fails as it must: {problems[0]}" if problems
                                                     else "PASSES: the case does not depend on it"))
    return sum(not problems for problems in found)


if __name__ == "__main__":
    raise SystemExit(main())
