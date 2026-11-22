"""directjump in the emulator: when a cued pattern starts, and on which step, stock alongside.

    python scripts/emu_directjump.py BUILD.syx [--stock STOCK.syx] [--case NAME ...]

Plays the sequencer headless (`scripts/emu_seqplay.py` and digikit's `panel_drive`). Each
case enters two or three patterns from the panel on track 1, each with its own trig set and
note, so that the note names the pattern and any four steps in a row name its position (the
sets are a binary de Bruijn sequence of order 4 and its complement). It sets DIRECT JUMP with
[PTN], then [UP] or [DOWN], presses PLAY on A01 and cues with [PTN] and [TRIG] keys.

`panel_drive` records the instruction count of every cue the PTN view posts (`0x400fa1e0`,
its pattern from the cue routine's argument at `0x400fa11e`), every tick (`0x400da406`), every step boundary (`0x400da584`) and every switch (`0x400da6e6`).
From these the check predicts each step's pattern and position, and so its note or silence,
and compares the prediction with the notes sent to the DSP:

- stock's switch at the boundary of step k starts the new pattern on step k + 1 (stock's lag);
- stock starts it at position 0. With DIRECT JUMP on, the build starts it at the playing
  pattern's position on that step, wrapped by the new pattern's length (the Analog Rytm's rule);
- with DIRECT JUMP on, a cue is armed on the first tick after it that is not a boundary's, and
  switches in the interrupt of the next boundary, before the boundary: the new pattern starts on
  that boundary's step. A cue made before the step's last tick starts on the next step, a later
  one on the step after.

Stock runs the same keys and must match the same prediction with start step 0. The cases:

- `off`: the switch off; the build equals stock note for note;
- `equal`, `shorter`, `longer`: A01 and A02 of 16 and 16, 16 and 12, 12 and 16 steps; `longer`
  cues in A01's second pass, so the start is A01's position, not the steps since PLAY. The
  `equal` cue falls after the step's last tick, so it starts a step later;
- `back`: a jump to A02, then back to A01;
- `rapid`: twelve cues among three patterns (16, 12 and 7 steps), at ticks 0 to 4 of their steps;
- `twice`: a second cue before the first one's switch: the switch takes the second;
- `pageloop`: A01 of 32 steps with Page Loop on page 2: the jump goes on from the full-pattern
  position, which the counters keep;
- `pertrack`: per-track mode, track 1 of 5 and 7 steps: the start is past track 1's length,
  and stock's rebuild wraps it;
- `change`: A01 with CHANGE 8 of 16 steps: the jump goes on from the pattern's position;
- `lst`, `notlst`, `lstlate`: every trig LST or !LST. LST is on from a cue's post to its switch,
  a boundary checks the condition of the step after it, the switch's boundary checks the new
  pattern's first step with LST off, and step 0 at PLAY plays whatever its condition. So a
  jump plays no LST trig and silences no !LST trig, except one old step when the cue falls
  after the step's last tick (`lstlate`);
- `stop`: stock's "stop pending" byte written between the build's arming and its switch (the
  panel's STOP is too slow to land there), then PLAY: the build equals stock note for note;
- `chain`: a chain from the chain creator, the switch on: the build equals stock note for note;
- `trigchain`: a chain made with the manual's legacy gesture ([PTN] held and a [TRIG], then each
  next [TRIG] with the previous one held), the switch on: the build equals stock note for note;
- `toggle`: the switch's byte (`0x405cd8c1`) and the screen after [PTN] tapped, [UP]; [DOWN];
  [PTN] held, [UP]; [DOWN] held into its repeats, and one settings write per press;
- `leds`: [PTN]'s colour in the firmware's LED cache (`0x466b7420`, one byte per panel channel,
  [PTN] on channel 3) in the PTN view, after [UP], with the view closed, in bank selection
  ([FUNC] + [PTN]) and after [DOWN]: the build lights it magenta (`0x61`) only in the PTN view
  with the switch on, and stock keeps white (`0x71`) there.
- `midi`: `shorter` with track 1 a MIDI track in both kits: the notes are the MIDI messages;
- `arp`, `arpsilent`: `shorter` with track 1's arp on UP in both kits, one arp note a trig;
  `arpsilent` jumps to a pattern with no trigs, so no arp note of the old pattern may follow;
- `pageloopto`: a jump in the second page of a 32-step A01, to a 32-step A02 with Page Loop on
  its second page. After the jump, track 1's condition-cycle position is its next step wrapped by
  the looped page's 16 steps, as stock keeps it from PLAY. The run ends at step 32, where stock's
  next switch comes (A01's end on stock, A02's after the jump). After that switch, stock plays
  A02 with Page Loop in a way these predictions do not cover;
- `speeds`: per-track mode, track 1 at 1/2x in A01 and 2x in A02, a jump there and one back,
  judged on half steps: each track starts on the start step wrapped by its length, at its speed;
- `long`, `longmidi`: trigs on even steps, every note 1.5 steps long, on the DSP and as MIDI.
  Every note must end 1.5 steps after it starts, and on the build a note of the old pattern must
  be sounding at a jump, so that its note-off falls after the jump;
- `early`: `shorter` with a trig on every step of A02, each a quarter step early (micro timing).
  Each A02 note sounds a quarter step before its step, except on the first step after a switch:
  a jump is made a tick before that step, when its time has passed, so that note must sound
  between its time and its step;
- `ab`: a cue in A01's first pass, to A02 with every trig 1:2. The cycle count starts again at
  a change, stock's or the jump's, so A02's first pass plays (A01's count is 1 at stock's change),
  and it goes on across A02's own ends, so its second pass is silent and its third plays;
- `abloop`: a cue at step 21 of A01's second pass, to a 48-step A02 with Page Loop on its second
  page and every trig 1:2. The count starts at the jump, and the cycle at 21 wrapped by the
  looped page's 16 steps, so the first pass plays 11 steps and the second is silent (wrapped by
  48, the cycle would wrap at once). Judged to the first stock switch after the cue (A01's end
  on stock, A02's on the build): after its own change, stock plays none of the looped page's
  trigs for 16 steps, which these predictions do not cover;
- `pool`: sixteen tracks at 1/8x with the arp on UP, eight rapid alternating cues. Stock's
  synth-lock allocator and engine-record allocator must never find their pools empty. The lock
  pool runs out on directjump3, and the record pool when a jump keeps the old pattern's arp
  clocks, though neither fault reporter runs. The input script and trace are kept with the frames.

Every run watches the firmware's fault reporter (`0x4011ea6a`) and the DSP uploader's refusal
(`0x400cf678`), and a run that reaches either fails.

On OS 1.12 (issue #382) the same cases run. The build's version picks the stock image, and every
stock address above moves through `dnfw.osport`, or through `ON_1_12` for the seven the map does
not hold (the watches are `0x4011ed4a` and `0x400cf7dc`). The switch moves with the settings block
(`build_direct_jump.overrides`), and the MIDI helpers from `emu_degreetranspose.py` take its 1.12
addresses.
Needs what `scripts/emu_seqplay.py` needs, through `PANEL_DRIVE`. A 1.12 build needs digikit
`main`'s `panel_drive`, which boots 1.12.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import subprocess
import sys
from fractions import Fraction

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from dnfw import osport  # noqa: E402
from dnfw import seqframes as SF  # noqa: E402
from dnfw.checkout import resources_dir  # noqa: E402
from dnfw.cli.files import read_image  # noqa: E402
from dnfw.firmware.load import load  # noqa: E402
from dnfw.mods import specs  # noqa: E402

import build_direct_jump as dj  # noqa: E402
import emu_degreetranspose as DT  # noqa: E402
import emu_seqplay as ES  # noqa: E402

STOCK = resources_dir() / "00_Firmware/Digitone_II_OS1.11_dist/Digitone_II_OS1.11.syx"
PTN, UP, DOWN, YES, PAGE = 23, 11, 14, 10, 22
STEP = 16_500_000                       # instructions a step at 120 BPM (emu_seqplay)
SAME_INTERRUPT = 100_000                # a tick is 2.75 M instructions at 1x; one interrupt is far less
FLAG = 0x405CD8C1
PATTERN_RAM, PATTERN_STRIDE = 0x4121898C, 122478
LENGTH_OFFSET = 122196                  # the pattern's length (word)
CONDITIONS = 0x280                      # track 1's COND per step, in RAM (stored +0x100; 0x400ddfb6)
LST, NOT_LST = 6, 7                     # COND codes (DNX's table)
ONE_OF_TWO = 8                          # COND 1:2: plays when the track's cycle count is even (0x401368b6)
TRIG_LIST, TRIG_SIZE = 0x6A50, 6        # a pattern's trigs in RAM, in the order entered: DNX's stored slot,
TRIG_LENGTH, TRIG_MICRO = 4, 5          # track, step, note, velocity, length, micro timing
MICRO_PER_STEP = 24                     # micro timing -6 sounds a quarter step early
TIME_SLACK = 0.02                       # steps: a note's time against its expected time (audio frames)
MIDI_NOTE_OFF = 0x80
RATES = {0: Fraction(2), 2: Fraction(1), 4: Fraction(1, 2)}   # TRACK_SPEED codes: 2x, 1x, 1/2x
MODE_OFFSET = 122201                    # the pattern's scale mode: 1 per track
STOP_PENDING, ARMED = 0x42C5A9E9, 0x42C5AAAC
LED_CACHE, PTN_CHANNEL = 0x466B7420, 3   # the colour sent to each panel channel; [PTN]'s
FAULT_REPORTER = 0x4011EA6A               # the firmware's EXCEPTION screen: any run that reaches it fails
UPLOAD_REFUSAL = 0x400CF678               # the DSP uploader's refusal: any run that reaches it fails too
FAULT_WATCH = f"{FAULT_REPORTER:#x},{UPLOAD_REFUSAL:#x}"
SETTING_WRITE = 0x400BB4F8                # the stock setting writer
SWITCH_PRESSES = 4                       # check_toggle's presses of [UP] and [DOWN], repeats not counted
TRACK_LENGTH = 0x480 + 0x0D             # track 1's length (DNX: track settings + 0x0D)
CUE_ENTRY, CUE, TICK, BOUNDARY, SWITCH = 0x400FA11E, 0x400FA1E0, 0x400DA406, 0x400DA584, 0x400DA6E6
DE_BRUIJN = "0000100110101111"           # order 4: every 4-step window is unique, so is its complement
HIGH = tuple(i for i, bit in enumerate(DE_BRUIJN) if bit == "1")
LOW = tuple(i for i, bit in enumerate(DE_BRUIJN) if bit == "0")
TRACKS = 16
TRACK_STRIDE, TRACK_SCALE = 1701, 1167
KIT_RAM, KIT_STRIDE = 0x4210C08C, 23921
SOUND_FIRST, SOUND_STRIDE, ARP_MODE = 52, 1163, 351
EIGHTH_SPEED = 6                        # index in the ticks-per-step table, 48 ticks
NEXT_STEP, CONDITION_CYCLE = 0x42C5A964, 0x42C5AAC8   # track 1's next step and condition-cycle position
MIDI_BLOCK = 18866                      # a kit's MIDI settings, 306 bytes a track (0x4012a276): track 1's
MIDI_BLOCK_CHANNEL, MIDI_BLOCK_FLAGS = 70, 222   # copied at the kit's load (0x4012a00c) to the MIDI task
LOCK_HEAD_READ = 0x40138992             # a0 holds the allocator's free-list head before its first dereference
RECORD_ALLOC, RECORD_FOUND = 0x401389DC, 0x401389E6   # the engine-record allocator: its head read, a record found
POOL_CUES = (1, 0) * 4                  # repeated replacement before the slow tracks' pending notes become due
# The test's own 1.11 addresses on OS 1.12 (issue #382), not in map_1.12.json because no mod names
# them, read with the survey's code map (`dnfw.osport.codemap`). The watches (+0x2e0, +0x164) and the
# allocator places (+0x2e0): 32 bytes of 1.11 occur once in 1.12, there, with their moved address
# words masked (each moved as the code map's votes say). The first pattern and kit: operand votes,
# 9/9 and 11/11, BSS +0x1000.
ON_1_12 = {"FAULT_REPORTER": 0x4011ED4A, "UPLOAD_REFUSAL": 0x400CF7DC, "LOCK_HEAD_READ": 0x40138C72,
           "RECORD_ALLOC": 0x40138CBC, "RECORD_FOUND": 0x40138CC6, "PATTERN_RAM": 0x4121998C,
           "KIT_RAM": 0x4210D08C}


@dataclasses.dataclass(frozen=True)
class Pattern:
    """A pattern entered on track 1: its slot (0 = A01), its trigs (0-based steps within 16,
    repeated on every page), its length and the semitones its trigs sit above C4. With
    LOOP_PAGE, Page Loop plays only that page (0-based)."""

    slot: int
    trigs: tuple[int, ...]
    length: int = 16
    note: int = 0
    loop_page: int | None = None
    condition: int | None = None        # every trig's COND code (DNX's: 6 LST, 7 !LST)
    track_length: int | None = None     # per-track mode, track 1 this long (LENGTH is the master's)
    change: int | None = None           # CHANGE, in steps
    speed: int | None = None            # per-track mode, track 1's speed (a RATES code)
    note_length: Fraction | None = None  # every trig's length, in steps (2/16 to 31/16)
    micro: int | None = None            # every trig's micro timing, MICRO_PER_STEP a step

    @property
    def rate(self) -> Fraction:
        return RATES[self.speed] if self.speed is not None else Fraction(1)

    def played(self, position: int) -> int:
        return 16 * self.loop_page + position % 16 if self.loop_page is not None else position

    def entered(self) -> list[int]:
        """The trigs' steps in the order GRID RECORDING enters them, page by page: their order in
        the trig list."""
        return [16 * page + s for page in range(max(1, self.length // 16)) if self.loop_page in (None, page)
                for s in self.trigs if 16 * page + s < self.length]


@dataclasses.dataclass(frozen=True)
class Case:
    """CUES: (instructions after the previous cue or PLAY, slot)."""

    patterns: tuple[Pattern, ...]
    cues: tuple[tuple[int, int], ...]
    on: bool = True
    run_steps: int = 40
    close: bool = True                  # [NO] after each cue (rapid: the cue closes the view itself)
    chain: bool = False                 # cue a chain of the patterns with the chain creator instead
    trig_chain: bool = False            # with CHAIN: [PTN] held and [TRIG] keys, not the chain creator
    compare: bool = False               # the build must equal stock note for note
    stop_after: int | None = None       # STOP this long after the last cue's keys, then PLAY
    midi: bool = False                  # track 1 a MIDI track: its notes are the MIDI messages sent
    arp: bool = False                   # track 1's arp UP in every pattern's kit
    cycle_peeks: int = 0                # read track 1's next step and condition cycle this often after the cues
    grid: int = 1                       # judged in steps of 1/GRID
    to_stock_switch: bool = False       # judged only before the first stock switch after the cue


A01, A02, A03 = Pattern(0, LOW), Pattern(1, HIGH, note=7), Pattern(2, LOW, note=4)
EVEN = tuple(range(0, 16, 2))
CASES = {
    "off": Case((A01, A02), ((90_000_000, 1),), on=False, compare=True),
    "equal": Case((A01, A02), ((90_000_000, 1),)),
    "shorter": Case((A01, dataclasses.replace(A02, length=12)), ((230_000_000, 1),)),
    "longer": Case((dataclasses.replace(A01, length=12), A02), ((300_000_000, 1),)),
    "back": Case((A01, dataclasses.replace(A02, length=12)), ((90_000_000, 1), (70_000_000, 0))),
    "rapid": Case((A01, dataclasses.replace(A02, length=12), dataclasses.replace(A03, length=7)),
                  tuple((delay, slot) for delay, slot in zip(
                      (60_000_000, 37_000_000, 41_000_000, 30_000_000, 52_000_000, 34_000_000,
                       45_000_000, 31_000_000, 39_000_000, 48_000_000, 33_000_000, 43_000_000),
                      (1, 2, 0, 1, 0, 2, 1, 0, 2, 0, 1, 0))),
                  run_steps=60, close=False),
    "pageloop": Case((Pattern(0, LOW, length=32, loop_page=1), A02), ((100_000_000, 1),)),
    "chain": Case((A01, A02), ((90_000_000, 1),), chain=True, compare=True),
    "trigchain": Case((A01, A02, A03), ((90_000_000, 1),), chain=True, trig_chain=True, compare=True),
    "pertrack": Case((dataclasses.replace(A01, track_length=5), dataclasses.replace(A02, track_length=7)),
                     ((130_000_000, 1),)),
    "change": Case((dataclasses.replace(A01, change=8), A02), ((130_000_000, 1),)),
    "stop": Case((A01, A02), ((90_000_000, 1),), close=False, stop_after=3_000_000, compare=True),
    "lstlate": Case((dataclasses.replace(A01, trigs=tuple(range(16)), condition=LST),
                     dataclasses.replace(A02, trigs=tuple(range(16)), condition=LST)), ((90_000_000, 1),)),
    "twice": Case((A01, A02, A03), ((90_000_000, 1), (1_000_000, 2)), close=False),
    "lst": Case((dataclasses.replace(A01, trigs=tuple(range(16)), condition=LST),
                 dataclasses.replace(A02, trigs=tuple(range(16)), condition=LST)), ((380_000_000, 1),)),
    "notlst": Case((dataclasses.replace(A01, trigs=tuple(range(16)), condition=NOT_LST),
                    dataclasses.replace(A02, trigs=tuple(range(16)), condition=NOT_LST)), ((380_000_000, 1),)),
    "midi": Case((A01, dataclasses.replace(A02, length=12)), ((230_000_000, 1),), midi=True),
    "arp": Case((A01, dataclasses.replace(A02, length=12)), ((230_000_000, 1),), arp=True),
    "arpsilent": Case((A01, Pattern(1, (), note=7)), ((230_000_000, 1),), arp=True),
    "pageloopto": Case((dataclasses.replace(A01, length=32), Pattern(1, HIGH, length=32, note=7, loop_page=1)),
                       ((330_000_000, 1),), run_steps=2, cycle_peeks=12),
    "speeds": Case((dataclasses.replace(A01, speed=4), dataclasses.replace(A02, speed=0)),
                   ((90_000_000, 1), (230_000_000, 0)), grid=2),
    "long": Case((Pattern(0, EVEN, note_length=Fraction(3, 2)), Pattern(1, EVEN, note=7, note_length=Fraction(3, 2))),
                 ((90_000_000, 1), (70_000_000, 0))),
    "longmidi": Case((Pattern(0, EVEN, note_length=Fraction(3, 2)),
                      Pattern(1, EVEN, note=7, note_length=Fraction(3, 2))),
                     ((90_000_000, 1), (70_000_000, 0)), midi=True),
    "early": Case((A01, Pattern(1, tuple(range(16)), length=12, note=7, micro=-6)), ((230_000_000, 1),)),
    "ab": Case((A01, dataclasses.replace(A02, condition=ONE_OF_TWO)), ((90_000_000, 1),)),
    "abloop": Case((dataclasses.replace(A01, length=32),
                    Pattern(1, HIGH, length=48, note=7, loop_page=1, condition=ONE_OF_TWO)),
                   ((815_000_000, 1),), run_steps=32, to_stock_switch=True),
}


def tap(code: int, hold: str = "6M") -> list[str]:
    return [f"press:{code}", f"wait:{hold}", f"release:{code}", f"wait:{hold}"]


def trig(step: int) -> int:
    return ES.TRIG1 + step


def pokes(pattern: Pattern) -> list[str]:
    """PATTERN's length, CHANGE and per-track mode, written to its RAM before its trigs."""
    base = PATTERN_RAM + PATTERN_STRIDE * pattern.slot
    steps = []
    if pattern.length != 16:
        steps += [f"poke:{base + LENGTH_OFFSET:#x}:{pattern.length:04x}"]
    if pattern.change is not None:
        steps += [f"poke:{base + LENGTH_OFFSET + 2:#x}:{pattern.change:04x}"]
    if pattern.track_length is not None or pattern.speed is not None:
        steps += [f"poke:{base + MODE_OFFSET:#x}:01"]
    if pattern.track_length is not None:
        steps += [f"poke:{base + TRACK_LENGTH:#x}:{pattern.track_length:02x}"]
    if pattern.speed is not None:
        steps += [f"poke:{base + TRACK_SCALE:#x}:{pattern.speed:02x}"]
    return steps + ["wait:20M"] if steps else []


def trig_pokes(pattern: Pattern) -> list[str]:
    """Every entered trig's length and micro timing, written to PATTERN's trig list. A length
    byte below 30 is (byte + 2) / 16 steps (DNX's noteLengthSteps)."""
    trigs = PATTERN_RAM + PATTERN_STRIDE * pattern.slot + TRIG_LIST
    fields = []
    if pattern.note_length is not None:
        byte = 16 * pattern.note_length - 2
        if byte.denominator != 1 or not 0 <= byte < 30:
            raise ValueError(f"note length {pattern.note_length} is not in the fine band")
        fields.append((TRIG_LENGTH, int(byte)))
    if pattern.micro is not None:
        fields.append((TRIG_MICRO, pattern.micro & 0xFF))
    return [f"poke:{trigs + TRIG_SIZE * i + field:#x}:{value:02x}"
            for i in range(len(pattern.entered())) for field, value in fields]


def trig_keys(pattern: Pattern) -> list[str]:
    """In GRID RECORDING: PATTERN's trigs on every page (on its looped page only, with Page Loop)."""
    steps = []
    entered = pattern.entered()
    for page in range(max(1, pattern.length // 16)):
        if page:
            steps += [f"tap:{PAGE}", "wait:30M"]
        steps += [f"tap:{trig(s % 16)}" for s in entered if s // 16 == page]
    if pattern.length > 16:
        steps += [f"tap:{PAGE}", "wait:30M"]
    return steps


def enter(pattern: Pattern) -> list[str]:
    """Select PATTERN's slot (the sequencer stopped, so at once), set its note, enter its trigs
    on every page, its length, and its Page Loop."""
    steps = [f"tap:{PTN}", "wait:40M", f"tap:{trig(pattern.slot)}", "wait:80M"]
    if pattern.note:
        steps += ES.turn(ES.ENCODER_A, pattern.note) + ["wait:30M"]
    steps += pokes(pattern) + [f"tap:{ES.RECORD}"] + trig_keys(pattern)
    if pattern.loop_page is not None:
        steps += [f"press:{PAGE}", "wait:80M", f"tap:{trig(8 + pattern.loop_page)}", "wait:40M",
                  f"release:{PAGE}", "wait:30M"]
    steps += [f"tap:{ES.RECORD}", "wait:30M"]
    if pattern.condition is not None:
        conditions = PATTERN_RAM + PATTERN_STRIDE * pattern.slot + CONDITIONS
        steps += [f"poke:{conditions:#x}:{bytes([pattern.condition] * pattern.length).hex()}"]
    return steps + trig_pokes(pattern)


def cue_keys(case: Case) -> list[str]:
    """The keys of CASE's cues, from PLAY: single cues in the PTN view, or one chain."""
    if case.trig_chain:
        slots = [pattern.slot for pattern in case.patterns[1:]]
        steps = [f"wait:{case.cues[0][0]}", f"press:{PTN}", "wait:6M", f"press:{trig(slots[0])}", "wait:6M",
                 f"release:{PTN}", "wait:6M"]
        for held, nxt in zip(slots, slots[1:]):
            steps += [f"press:{trig(nxt)}", "wait:6M", f"release:{trig(held)}", "wait:6M"]
        return steps + [f"release:{trig(slots[-1])}", "wait:40M"]
    if case.chain:
        steps = [f"wait:{case.cues[0][0]}"] + tap(PTN) + [f"press:{ES.FUNC}", "wait:6M"] + tap(YES)
        steps += [f"release:{ES.FUNC}", "wait:20M"]
        for pattern in case.patterns[1:] + case.patterns[:1]:
            steps += tap(trig(pattern.slot))
        return steps + tap(YES)
    steps = []
    for delay, slot in case.cues:
        steps += [f"wait:{delay}"] + tap(PTN) + tap(trig(slot)) + (tap(ES.NO) if case.close else [])
    return steps


def midi_pokes(kit: int) -> list[str]:
    """Track 1 a MIDI track on channel 1, in KIT's own MIDI block too: PLAY and the jump's kit
    change load the kit, which copies the block's flags and channel to the MIDI task."""
    block = kit + MIDI_BLOCK
    return DT.midi_pokes(kit) + [f"poke:{block + MIDI_BLOCK_FLAGS:#x}:00000001",
                                 f"poke:{block + MIDI_BLOCK_CHANNEL:#x}:0000"]


def script(case: Case) -> list[str]:
    steps = ["wait:1500M", f"tap:{ES.NO}", "wait:60M", f"tap:{ES.TRIG_PAGE}", "wait:30M"]
    for pattern in case.patterns[1:] + case.patterns[:1]:
        steps += enter(pattern) + (ES.arp_steps("UP") if case.arp else [])
    steps += [f"tap:{PTN}", "wait:40M", f"tap:{UP if case.on else DOWN}", "wait:30M",
              f"tap:{ES.NO}", "wait:40M", f"peek:{FLAG:#x}:1"]
    if case.midi:
        steps += [poke for p in case.patterns for poke in midi_pokes(KIT_RAM + KIT_STRIDE * p.slot)]
    steps += [f"tap:{ES.PLAY}"] + cue_keys(case)
    for _ in range(case.cycle_peeks):
        steps += [f"wait:{STEP // 3}", f"peek:{NEXT_STEP:#x}:1", f"peek:{CONDITION_CYCLE:#x}:1"]
    if case.stop_after is not None:
        # stock's own "stop pending" byte, written where the panel's STOP is too slow to land:
        # between the build's arming and its switch
        steps += [f"wait:{case.stop_after}", f"poke:{STOP_PENDING:#x}:01", f"peek:{ARMED:#x}:4",
                  "wait:100M", f"tap:{ES.PLAY}"]
    return steps + [f"wait:{case.run_steps * STEP}", f"tap:{ES.STOP}", "wait:20M"]


def run(image: pathlib.Path, case: Case, out: pathlib.Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    listing = out / "steps.txt"
    listing.write_text("\n".join(script(case)))
    cmd = [str(ES.panel_drive()), str(image), "--ssi-hz", "96000", "--out", str(out),
           "--capture", f"{ES.EXCHANGE}:1:48,{DT.MIDI_SEND:#x}:1:0", "--watch", FAULT_WATCH,
           "--regs-at", ",".join(f"{pc:#x}" for pc in (CUE_ENTRY, CUE, TICK, BOUNDARY, SWITCH)),
           "--steps", f"@{listing}"]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=3000)
    if not done.stdout.strip():
        raise RuntimeError(done.stderr[-400:])
    (out / "run.json").write_text(done.stdout)
    result = json.loads(done.stdout)
    if result["outcome"] != "done":
        raise RuntimeError(f"fault: {result['fault']}")
    refuse_faults(result)
    return result


def refuse_faults(result: dict) -> None:
    """Raise when the run reached the fault reporter or the DSP uploader's refusal."""
    hits = {w["pc"]: w["hits"] for w in result["watched"] if int(w["pc"], 16) in (FAULT_REPORTER, UPLOAD_REFUSAL)}
    if len(hits) != 2 or any(hits.values()):
        raise RuntimeError(f"fault watch: {hits}")


def note_events(result: dict, midi: bool) -> list[tuple[int, int]]:
    """(instruction count, note) of every note-on, each voice of a frame on its own: to the DSP,
    and with MIDI, the MIDI messages too. The step at PLAY reaches the DSP: the poked MIDI settings
    take effect after it."""
    frames = [c for c in result["captures"] if int(c["pc"], 16) == int(ES.EXCHANGE, 16)]
    ons = [(e.icount, round(note)) for e in SF.note_ons(SF.events(frames)) for note in e.notes]
    if midi:
        sent = [(c["icount"], bytes.fromhex(c["hex"])) for c in result["captures"]
                if int(c["pc"], 16) == DT.MIDI_SEND]
        ons += [(icount, msg[1]) for icount, msg in sent if msg[0] & 0xF0 == DT.NOTE_ON and msg[2]]
    return sorted(ons)


def notes_by_step(result: dict, note_of: dict[int, int], midi: bool,
                  grid: int) -> tuple[int, dict[Fraction, list[int | str]]]:
    """-> (the first note's instruction count, {step, to 1/GRID: the slot of the pattern of each note
    that sounded there, in order}). A note no pattern plays is named as itself."""
    ons = note_events(result, midi)
    t0 = ons[0][0]
    heard: dict[Fraction, list[int | str]] = {}
    for icount, note in ons:
        step = Fraction(round(grid * (icount - t0) / STEP), grid)
        heard.setdefault(step, []).append(note_of.get(note - 60, f"note {note}"))
    return t0, heard


@dataclasses.dataclass(frozen=True)
class Record:
    """What `panel_drive` recorded of one run, as instruction counts. Steps count from T0, the
    first note, which is step 0."""

    t0: int
    posts: list[tuple[int, int]]        # (when the PTN view posted a cue, the cued pattern's slot)
    ticks: list[int]
    boundaries: list[int]
    switches: list[int]

    def step_of(self, icount: int) -> int:
        return round((icount - self.t0) / STEP)

    def at_boundary(self, icount: int) -> bool:
        """ICOUNT is in a boundary's interrupt, before or at the boundary."""
        return any(icount <= b < icount + SAME_INTERRUPT for b in self.boundaries)

    def early(self, switch: int) -> bool:
        """A jump's switch: in the interrupt that ends the step, before that interrupt's boundary.
        Stock's switch comes after its boundary."""
        return not any(switch - SAME_INTERRUPT < b <= switch for b in self.boundaries)

    def starts(self) -> dict[int, int]:
        """{step: slot}: each switch starts the pattern of the latest cue posted before it, a
        jump's on its boundary's step, stock's on the step after."""
        return {self.step_of(s) + (0 if self.early(s) else 1): max(p for p in self.posts if p[0] < s)[1]
                for s in self.switches if s > self.t0}

    def expected_start(self, post: int) -> int:
        """The step a jump cued at POST must start on: armed on the first tick after it that is
        not a boundary's (tick 0), switched in the interrupt of the next boundary, so started on
        that boundary's step."""
        armed = next(t for t in self.ticks if t > post and not self.at_boundary(t))
        return self.step_of(next(b for b in self.boundaries if b > armed))

    def last_pass(self, step: int) -> bool:
        """LST for STEP's condition: on from a cue's post to the switch that installs it. The
        boundary of step b checks step b + 1, and the switch's own boundary checks the new
        pattern's first step with LST off. A jump checks the new pattern's first step after its
        switch, with LST off too."""
        if any(self.early(s) and self.step_of(s) == step for s in self.switches):
            return False
        at = next((b for b in self.boundaries if self.step_of(b) + 1 == step), None)
        return at is not None and any(
            post < at < min((s for s in self.switches if s > post), default=at + STEP) - SAME_INTERRUPT
            for post, _ in self.posts if post > self.t0)


def record(result: dict, t0: int) -> Record:
    hits = {pc: [h for h in result["regs"] if int(h["pc"], 16) == pc]
            for pc in (CUE_ENTRY, CUE, TICK, BOUNDARY, SWITCH)}

    def cued(post: dict) -> int:
        entry = max((e for e in hits[CUE_ENTRY] if e["icount"] < post["icount"]), key=lambda e: e["icount"])
        return int(entry["stack"][2], 16)

    return Record(t0, [(h["icount"], cued(h)) for h in hits[CUE]],
                  *([h["icount"] for h in hits[pc]] for pc in (TICK, BOUNDARY, SWITCH)))


@dataclasses.dataclass(frozen=True)
class Playing:
    """PATTERN, started on STEP at master POSITION."""

    pattern: Pattern
    step: int = 0
    position: int = 0
    count: int = 0                      # the cycle count at the start: kept when a pattern switches to itself

    def fired(self, step: Fraction) -> int | None:
        """How many steps track 1 has moved at STEP since the start, at its rate, or None when STEP
        falls between its steps."""
        moved = (step - self.step) * self.pattern.rate
        return int(moved) if moved.denominator == 1 else None

    def track1(self, moved: int) -> int:
        """Track 1's position MOVED steps after the start: the master position, wrapped by the
        track's own length in per-track mode (the start too), else by the pattern's."""
        length = self.pattern.track_length or self.pattern.length
        return (self.position % length + moved) % length

    def passes(self, moved: int) -> int:
        """The cycle count MOVED steps after the start: one more each time the cycle wraps. The
        cycle starts at the start position, wrapped by the looped page's 16 steps with Page Loop
        on, else by the track's length."""
        span = 16 if self.pattern.loop_page is not None else self.pattern.track_length or self.pattern.length
        return self.count + (self.position % span + moved) // span

    def to(self, step: int, pattern: Pattern, carry: bool) -> "Playing":
        """The switch to PATTERN on STEP: stock starts it at 0; a jump carries the master position,
        wrapped by the new pattern's length when that is above 1. The cycle count starts again,
        except when the pattern switches to itself at its end."""
        here = (self.position + step - self.step) % self.pattern.length
        count = self.passes(int((step - self.step) * self.pattern.rate)) if pattern is self.pattern else 0
        return Playing(pattern, step, here % pattern.length if carry and pattern.length > 1 else 0, count)

    def sounds(self, step: Fraction, rec: Record) -> bool:
        """Track 1's trig on STEP plays: track 1 moves to a step then, a trig there, and its
        condition true. Step 0, at PLAY, plays whatever its condition."""
        pattern = self.pattern
        moved = self.fired(step)
        if moved is None:
            return False
        plays = pattern.played(self.track1(moved)) % 16 in pattern.trigs
        if step == 0 or pattern.condition is None:
            return plays
        if pattern.condition == ONE_OF_TWO:
            return plays and self.passes(moved) % 2 == 0
        return plays and rec.last_pass(int(step)) == (pattern.condition == LST)


def grid_steps(case: Case, last: int) -> list[Fraction]:
    """The steps judged, in steps of 1/GRID, before LAST."""
    return [Fraction(i, case.grid) for i in range(last * case.grid)]


def timeline(case: Case, rec: Record, jump: bool, last: int) -> dict[Fraction, int | None]:
    """{step: the slot whose note must sound on it, or None}, before step LAST."""
    by_slot = {p.slot: p for p in case.patterns}
    starts = rec.starts()
    playing = Playing(case.patterns[0])
    expected: dict[Fraction, int | None] = {}
    for step in grid_steps(case, last):
        if step.denominator == 1 and int(step) in starts:
            playing = playing.to(int(step), by_slot[starts[int(step)]], jump)
        expected[step] = playing.pattern.slot if playing.sounds(step, rec) else None
    return expected


def problems(case: Case, rec: Record, heard: dict[Fraction, list[int | str]], jump: bool, last: int) -> list[str]:
    """The steps whose notes differ from the prediction: each step must have exactly one note, of
    the predicted pattern, or none. For a jump, also the cues that did not start on their step."""
    expected = timeline(case, rec, jump, last)
    wrong = [f"step {s}: heard {heard.get(s, [])}, expected {[expected[s]] if expected[s] is not None else []}"
             for s in grid_steps(case, last)
             if heard.get(s, []) != ([expected[s]] if expected[s] is not None else [])]
    if jump:
        started = sorted(rec.starts())
        wrong += [f"cue at step {(post - rec.t0) / STEP:.2f}: no start on step {rec.expected_start(post)} "
                  f"(starts on {started})"
                  for post, _ in rec.posts if post > rec.t0 and rec.expected_start(post) not in started]
    return wrong


def peeked(result: dict, address: int) -> str:
    return next(e["hex"] for e in result["results"] if e.get("peek") == f"{address:#010x}")


def cycle_problems(case: Case, rec: Record, result: dict) -> list[str]:
    """Track 1's condition-cycle position must be its next step wrapped by the steps it cycles
    over: the looped page's 16 with Page Loop on, else the pattern's length. Stock keeps them so
    from PLAY, and a jump must start both from the same step."""
    def reads(address: int) -> list[tuple[int, int]]:
        return [(e["icount"], int(e["hex"], 16)) for e in result["results"] if e.get("peek") == f"{address:#010x}"]
    wrong = []
    for (icount, step), (_, cycle) in zip(reads(NEXT_STEP), reads(CONDITION_CYCLE)):
        switched = any(rec.t0 < s < icount for s in rec.switches)
        playing = case.patterns[1] if switched else case.patterns[0]
        span = 16 if playing.loop_page is not None else playing.length
        if cycle != step % span:
            wrong.append(f"step {(icount - rec.t0) / STEP:.2f}: next step {step}, cycle {cycle}, "
                         f"expected {step % span}")
    return wrong


def voice_spans(result: dict) -> list[tuple[int, int | None]]:
    """(note-on, its voice's next note-off or None) for each voice of each note-on to the DSP."""
    found = SF.events([c for c in result["captures"] if int(c["pc"], 16) == int(ES.EXCHANGE, 16)])
    return [(on.icount, next((e.icount for e in found[i + 1:] if e.kind == "off" and voice in e.voices), None))
            for i, on in enumerate(found) if on.kind == "on" for voice in on.voices]


def midi_spans(result: dict) -> list[tuple[int, int | None]]:
    """(note-on, the next note-off of its note or None) for each MIDI note-on sent."""
    sent = [(c["icount"], bytes.fromhex(c["hex"])) for c in result["captures"]
            if int(c["pc"], 16) == DT.MIDI_SEND and len(c["hex"]) >= 6]

    def ends(msg: bytes, note: int) -> bool:
        return msg[1] == note and (msg[0] & 0xF0 == MIDI_NOTE_OFF or (msg[0] & 0xF0 == DT.NOTE_ON and not msg[2]))
    return [(icount, next((t for t, m in sent[i + 1:] if ends(m, msg[1])), None))
            for i, (icount, msg) in enumerate(sent) if msg[0] & 0xF0 == DT.NOTE_ON and msg[2]]


def length_problems(case: Case, rec: Record, result: dict, jump: bool, last: int) -> tuple[list[str], list[str]]:
    """With every trig NOTE_LENGTH long: each note must end that long after it starts, on the DSP
    by voice, or as MIDI by note, a jump between or not. On a jump, a note of the old pattern must
    be sounding, so that its note-off falls after the jump. -> (problems, facts). Notes the STOP
    cuts are not judged."""
    length = case.patterns[0].note_length
    if length is None:
        return [], []
    spans = [(on, off) for on, off in (midi_spans(result) if case.midi else voice_spans(result))
             if rec.t0 <= on < rec.t0 + (last - 2) * STEP]
    wrong = [f"note at step {(on - rec.t0) / STEP:.2f}: "
             + ("no note-off" if off is None else f"{(off - on) / STEP:.3f} steps long")
             for on, off in spans if off is None or abs((off - on) / STEP - length) > TIME_SLACK]
    jumps = [s for s in rec.switches if jump and rec.early(s)]
    across = [on for on, off in spans if off is not None and any(on < s < off for s in jumps)]
    if jumps and not across:
        wrong.append("no note sounds at a jump")
    return wrong, [f"{len(spans)} notes {float(length)} steps long, {len(across)} sounding at a jump"]


def micro_problems(case: Case, rec: Record, notes: list[tuple[int, int]]) -> tuple[list[str], list[str]]:
    """With every trig of a pattern shifted by micro timing: each of its NOTES sounds that far
    from its step, except on the first step after a jump to it. That note's time has passed when
    the jump is made, so it must sound at the jump. -> (problems, facts)."""
    pattern = next((p for p in case.patterns if p.micro is not None), None)
    if pattern is None:
        return [], []
    shift = pattern.micro / MICRO_PER_STEP
    ons = [icount for icount, note in notes if note - 60 == pattern.note]
    starts = rec.starts()
    jumps = {rec.step_of(s): s for s in rec.switches
             if s > rec.t0 and rec.early(s) and starts.get(rec.step_of(s)) == pattern.slot}
    wrong = [f"no note on step {step}, the first after a jump"
             for step in sorted(set(jumps) - {round((icount - rec.t0) / STEP) for icount in ons})]
    facts = []
    for icount in ons:
        at = (icount - rec.t0) / STEP
        step = round(at)
        if step in jumps:
            after_jump = (icount - jumps[step]) / STEP
            facts.append(f"first step after a jump, {step}: {at - step - shift:+.3f} steps from its time, "
                         f"{after_jump:+.3f} from the jump")
            if not 0 <= after_jump <= TIME_SLACK:
                wrong.append(f"first step after a jump: note at step {at:.3f}, not at the jump")
        elif abs(at - step - shift) > TIME_SLACK:
            wrong.append(f"note at step {at:.3f}, not {shift:+.3f} from its step")
    return wrong, facts


def judge(name: str, who: str, case: Case, result: dict) -> tuple[bool, list[tuple]]:
    """Print one run's verdict. -> (it passed, its notes by step and pitch, to compare with stock)."""
    t0, heard = notes_by_step(result, {p.note: p.slot for p in case.patterns}, case.midi, case.grid)
    rec = record(result, t0)
    last = rec.step_of(max(rec.boundaries)) - 1
    if case.to_stock_switch:
        cue = min(post for post, _ in rec.posts if post > t0)
        last = min(last, min(rec.step_of(s) + 1 for s in rec.switches if s > cue and not rec.early(s)))
    jump = who == "build" and case.on and not case.chain
    wrong = [] if case.chain or case.stop_after is not None else problems(case, rec, heard, jump, last)
    wrong += cycle_problems(case, rec, result)
    length_wrong, length_facts = length_problems(case, rec, result, jump, last)
    micro_wrong, micro_facts = micro_problems(case, rec, note_events(result, case.midi))
    wrong += length_wrong + micro_wrong
    flag = peeked(result, FLAG)
    good = not wrong and (who == "stock" or flag == ("01" if case.on else "00"))
    if case.stop_after is not None and who == "build":
        armed = peeked(result, ARMED)
        good &= armed == "00000001"
        wrong.append(f"armed at the STOP: {armed}")
    print(f"  {name:9} {who:5}  {'ok ' if good else 'BAD'}  switch byte {flag}, "
          f"{sum(map(len, heard.values()))} notes in steps 0..{last}" + "".join(f"\n      {w}" for w in wrong[:8])
          + "".join(f"\n      ({f})" for f in length_facts + micro_facts))
    return good, [(rec.step_of(icount), note) for icount, note in note_events(result, case.midi)]


def check(name: str, case: Case, images: dict[str, pathlib.Path], frames: pathlib.Path) -> bool:
    verdicts = {who: judge(name, who, case, run(image, case, frames / f"{name}-{who}"))
                for who, image in images.items()}
    ok = all(good for good, _ in verdicts.values())
    if case.compare:
        same = verdicts["build"][1] == verdicts["stock"][1]
        ok &= same
        print(f"  {name:9} build = stock note for note: {'yes' if same else 'NO'}")
    return ok


def check_toggle(images: dict[str, pathlib.Path], frames: pathlib.Path) -> bool:
    """[PTN] tapped, [UP]; [DOWN]; [PTN] held, [UP]; [UP] held into its repeats: the byte
    after each, and the screen."""
    steps = ["wait:1500M", f"tap:{ES.NO}", "wait:60M", f"peek:{FLAG:#x}:1",
             f"tap:{PTN}", "wait:40M", "frame:view", f"tap:{UP}", "wait:30M", "frame:on", f"peek:{FLAG:#x}:1",
             f"tap:{DOWN}", "wait:30M", "frame:off", f"peek:{FLAG:#x}:1", f"tap:{ES.NO}", "wait:40M",
             f"press:{PTN}", "wait:40M", f"tap:{UP}", "wait:30M", f"peek:{FLAG:#x}:1", f"release:{PTN}",
             "wait:40M", f"tap:{PTN}", "wait:40M", f"press:{DOWN}", "wait:400M", f"release:{DOWN}",
             "wait:30M", f"peek:{FLAG:#x}:1", f"tap:{ES.NO}", "wait:40M"]
    want = ["00", "01", "00", "01", "00"]
    ok = True
    writes: dict[str, int] = {}
    for who, image in images.items():
        out = frames / f"toggle-{who}"
        out.mkdir(parents=True, exist_ok=True)
        cmd = [str(ES.panel_drive()), str(image), "--out", str(out), "--count", f"{SETTING_WRITE:#x}",
               "--watch", FAULT_WATCH,
               "--steps", ",".join(steps)]
        result = json.loads(subprocess.run(cmd, capture_output=True, text=True, timeout=3000).stdout)
        if result["outcome"] != "done":
            raise RuntimeError(f"fault: {result['fault']}")
        refuse_faults(result)
        seen = [e["hex"] for e in result["results"] if e.get("peek") == f"{FLAG:#010x}"]
        writes[who] = next(w["hits"] for w in result["watched"] if int(w["pc"], 16) == SETTING_WRITE)
        good = seen == (want if who == "build" else ["00"] * 5)
        ok &= good
        print(f"  toggle    {who:5}  {'ok ' if good else 'BAD'}  byte after each key {seen}, "
              f"{writes[who]} setting writes; screens in {out}")
    # each press writes the switch once, and a held key's repeats write nothing
    if set(writes) == {"build", "stock"}:
        once = writes["build"] - writes["stock"] == SWITCH_PRESSES
        ok &= once
        print(f"  toggle    {'ok ' if once else 'BAD'}  {writes['build'] - writes['stock']} more setting writes on "
              f"the build than on stock, for {SWITCH_PRESSES} presses")
    return ok


def check_leds(images: dict[str, pathlib.Path], frames: pathlib.Path) -> bool:
    """[PTN]'s colour byte in the PTN view, after [UP], closed, in bank selection, after [DOWN]."""
    peek = f"peek:{LED_CACHE + PTN_CHANNEL:#x}:1"
    steps = ["wait:1500M", f"tap:{ES.NO}", "wait:60M",
             f"tap:{PTN}", "wait:60M", peek, f"tap:{UP}", "wait:60M", peek, f"tap:{ES.NO}", "wait:60M", peek,
             f"press:{ES.FUNC}", "wait:6M", f"tap:{PTN}", f"release:{ES.FUNC}", "wait:60M", peek,
             f"tap:{ES.NO}", "wait:60M", f"tap:{PTN}", "wait:60M", f"tap:{DOWN}", "wait:60M", peek,
             f"tap:{ES.NO}", "wait:40M"]
    want = {"build": ["71", "61", "01", "83", "71"], "stock": ["71", "71", "01", "83", "71"]}
    ok = True
    for who, image in images.items():
        out = frames / f"leds-{who}"
        out.mkdir(parents=True, exist_ok=True)
        cmd = [str(ES.panel_drive()), str(image), "--ssi-hz", "96000", "--out", str(out),
               "--watch", FAULT_WATCH, "--steps", ",".join(steps)]
        result = json.loads(subprocess.run(cmd, capture_output=True, text=True, timeout=3000).stdout)
        if result["outcome"] != "done":
            raise RuntimeError(f"fault: {result['fault']}")
        refuse_faults(result)
        seen = [e["hex"] for e in result["results"] if e.get("peek") == f"{LED_CACHE + PTN_CHANNEL:#010x}"]
        good = seen == want[who]
        ok &= good
        print(f"  leds      {who:5}  {'ok ' if good else 'BAD'}  [PTN] after each key {seen}")
    return ok


def pool_steps() -> list[str]:
    """Sixteen audio tracks in two patterns, slow tracks with arps, then rapid pattern cues."""
    steps = ["wait:1500M", f"tap:{ES.NO}", "wait:60M", f"tap:{ES.TRIG_PAGE}", "wait:30M"]
    for pattern in (A02, A01):
        steps += [f"press:{ES.TRK}", f"tap:{ES.TRIG1}", f"release:{ES.TRK}", "wait:30M"]
        steps += enter(dataclasses.replace(pattern, trigs=tuple(range(16))))
        for track in range(1, TRACKS):
            steps += [f"press:{ES.TRK}", f"tap:{ES.TRIG1 + track}", f"release:{ES.TRK}", "wait:30M",
                      f"tap:{ES.RECORD}"]
            steps += [f"tap:{ES.TRIG1 + step}" for step in range(16)]
            steps += [f"tap:{ES.RECORD}", "wait:30M"]
    steps += [f"tap:{PTN}", "wait:40M", f"tap:{UP}", "wait:30M", f"tap:{ES.NO}", "wait:40M"]
    for slot in (0, 1):
        pattern = PATTERN_RAM + slot * PATTERN_STRIDE
        kit = KIT_RAM + slot * KIT_STRIDE
        steps += [f"poke:{pattern + MODE_OFFSET:#x}:01"]
        for track in range(TRACKS):
            scale = pattern + track * TRACK_STRIDE + TRACK_SCALE
            arp = kit + SOUND_FIRST + track * SOUND_STRIDE + ARP_MODE
            steps += [f"poke:{scale:#x}:{EIGHTH_SPEED:02x}", f"poke:{arp:#x}:{ES.ARP_MODES.index('UP'):02x}"]
    steps += [f"peek:{FLAG:#x}:1", f"tap:{ES.PLAY}", "wait:90M"]
    for slot in POOL_CUES:
        steps += tap(PTN) + tap(trig(slot))
    return steps + ["wait:300M", f"tap:{ES.STOP}", "wait:80M"]


def pool_run(image: pathlib.Path, out: pathlib.Path) -> dict:
    """The pool fixture on IMAGE, its input script and trace kept in OUT. A trace that ended
    early or dropped records is refused."""
    out.mkdir(parents=True, exist_ok=True)
    listing = out / "steps.txt"
    listing.write_text("\n".join(pool_steps()))
    cmd = [str(ES.panel_drive()), str(image), "--ssi-hz", "96000", "--out", str(out),
           "--watch", FAULT_WATCH,
           "--regs-at", f"{CUE:#x},{LOCK_HEAD_READ:#x},{BOUNDARY:#x},{SWITCH:#x}",
           "--count", f"{RECORD_ALLOC:#x},{RECORD_FOUND:#x}",
           "--capture", f"{ES.EXCHANGE}:1:48", "--steps", f"@{listing}"]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=3000, check=True)
    (out / "run.json").write_text(done.stdout)
    result = json.loads(done.stdout)
    if result["outcome"] != "done" or result["regs_dropped"]:
        raise RuntimeError(f"incomplete pool trace: {result['outcome']}, "
                           f"dropped {result['regs_dropped']}")
    refuse_faults(result)
    return result


def pool_controls(result: dict, who: str) -> tuple[int, int, int]:
    """The pool run's positive controls: all sixteen tracks play, every cue is posted, the switch
    is as set, the lock allocator runs, and the build jumps once for each cue and stock never. A
    jump is a switch with no step boundary in its interrupt. -> (note-on frames, cues, jumps).
    Raises when a control fails."""
    notes = SF.note_ons(SF.events(result["captures"]))
    if not notes or len(notes[0].voices) != TRACKS:
        raise RuntimeError("pool control: all sixteen tracks must play")
    at = {pc: [hit["icount"] for hit in result["regs"] if int(hit["pc"], 16) == pc]
          for pc in (CUE, BOUNDARY, SWITCH, LOCK_HEAD_READ)}
    cues = sum(icount > notes[0].icount for icount in at[CUE])
    if cues != len(POOL_CUES) or peeked(result, FLAG) != ("01" if who == "build" else "00"):
        raise RuntimeError("pool control: cue count or Direct Jump setting differs")
    if not at[LOCK_HEAD_READ]:
        raise RuntimeError("pool control: the synth-lock allocator never ran")
    jumps = sum(s > notes[0].icount and not any(s - SAME_INTERRUPT < b <= s for b in at[BOUNDARY])
                for s in at[SWITCH])
    if jumps != (len(POOL_CUES) if who == "build" else 0):
        raise RuntimeError(f"pool control: {jumps} jumps")
    return len(notes), cues, jumps


def check_pool(images: dict[str, pathlib.Path], frames: pathlib.Path) -> bool:
    """Detect an empty lock or record allocation, with playback, cue and jump counts as positive
    controls."""
    ok = True
    for who, image in images.items():
        out = frames / f"pool-{who}"
        result = pool_run(image, out)
        note_frames, cues, jumps = pool_controls(result, who)
        empty = [int(hit["a"][0], 16) for hit in result["regs"] if int(hit["pc"], 16) == LOCK_HEAD_READ].count(0)
        counted = {int(w["pc"], 16): w["hits"] for w in result["watched"]}
        no_record = counted[RECORD_ALLOC] - counted[RECORD_FOUND]
        good = empty == 0 and no_record == 0
        ok &= good
        print(f"  pool      {who:5}  {'ok ' if good else 'BAD'}  {empty} empty lock allocations, "
              f"{no_record} empty record allocations, {cues} cues, {jumps} jumps, {note_frames} note-on frames. "
              f"Trace in {out}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("build", type=pathlib.Path)
    ap.add_argument("--stock", type=pathlib.Path, help="stock of the build's OS (default: the user's own)")
    ap.add_argument("--case", action="append", choices=list(CASES) + ["toggle", "leds", "pool"])
    ap.add_argument("--frames", type=pathlib.Path, default=ROOT / "out/emu-directjump")
    a = ap.parse_args()
    os_version = specs.of_firmware(load(read_image(a.build)))
    a.stock = a.stock or (STOCK if os_version == "1.11" else resources_dir() / dj.STOCKS[os_version])
    this = sys.modules[__name__]
    moved = {}
    if os_version == "1.12":
        moved = {**ON_1_12, "FLAG": dj.overrides(os_version)["FLAG"],
                 "FAULT_WATCH": f"{ON_1_12['FAULT_REPORTER']:#x},{ON_1_12['UPLOAD_REFUSAL']:#x}"}
        ES.use(os_version)
        DT.MIDI_MASK_COPIES = (DT.MIDI_MASK_COPIES[0], DT.ON_1_12["MIDI_MASK_COPY"])
        DT.MIDI_FLAGS, DT.MIDI_CHANNEL, DT.MIDI_SEND = (DT.ON_1_12["MIDI_FLAGS"], DT.ON_1_12["MIDI_CHANNEL"],
                                                        DT.ON_1_12["MIDI_SEND"])
    elif os_version != "1.11":
        raise SystemExit(f"no test addresses for OS {os_version}")
    images = {"stock": a.stock, "build": a.build}
    failures = 0
    checks = {"toggle": check_toggle, "leds": check_leds, "pool": check_pool}
    with osport.retarget(os_version, [this], {this: moved}):
        print(f"OS {os_version}: stock {a.stock.name}, switch {FLAG:#010x}, exchange {ES.EXCHANGE}, "
              f"watch {FAULT_WATCH}")
        for name in a.case or list(CASES) + list(checks):
            ok = checks[name](images, a.frames) if name in checks else check(name, CASES[name], images, a.frames)
            failures += not ok
    print(f"\n{failures} failing case(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
