"""Parameter slides: a trig's parameter locks glide where stock makes them jump.

    python scripts/build_pslide.py [--out PATH]

The design is issue #391's: model B with NEXT. Each trig has SLD on TRIG PAGE 2: OFF, a length
(1/2, 1, 2, 4, 8 or 16 steps of the track's speed) or NEXT. A trig with a length glides to its
own values over the length, from the values the track had just before it. A NEXT trig slides
from its own values to the next trig's, and arrives as that trig plays. Until a trig has SLD
set, the instrument is stock.

## The values a slide moves (read 2026-11-24, OS 1.11)

Each voice keeps three copies of its 101 values, word `17 + 101 v + s` for voice v and slot s:
the targets that the sound and the locks write (SRC, `0x80003af0`), the smoother's state in 16.16
(STATE, `0x8000de60`), and the smoother's output, which the frame to the DSP is built from. The
audio-frame interrupt calls the smoother (`0x400db12a`) at `0x4002717e`, before the modulation
apply, so an LFO modulates a slid value. A slide writes a value as its target and its smoother
state, so the smoother adds no lag to it. It runs on the hook bus's `ev_frame` at that call.

Stock's note path (voice d2, the event at -36(%fp)): a sound other than the voice's is loaded
whole (`0x4002549c`) and the voice's lock bits cleared (`0x400db052`); otherwise each slot whose
lock bit is set goes back to the sound's value (`0x400daf44`, from sound + 20 + 2 slot). Then the
lock applier (`0x400db092`) writes the trig's list: each entry's target and smoother state, and
its lock bit (`0x4664b26c + 16 v`, a bit per slot). A lock trig runs the applier once for each
voice of its track (`0x40026642`).

A turned knob or a CC writes the target of every voice of the track (`0x4002585a`), locked or
not, and not the smoother state. A slide finds such a write by a target that is not its smoother
state's value, and leaves that value to the knob.

## The trig's list, its sound and its step

Step evaluation (`0x400d8654`, a step ahead) builds each note's event: the track at + 16, the
step's flag word at + 56, its sound at + 60 (machine at sound + 222, filter type at + 223), and
a lock list at + 84, made for every trig and empty when it has no locks (`0x400d85e8`: count at
+ 8, entries of 8 bytes from + 20, the slot then the value). The list's address names the trig
while its notes play: retrigs and the notes of a chord use the same list. Stock's 64 lists come
from a free list that gives a freed list out next (`0x40138986`, `0x401389a8`). A slide holds a
count on its trig's list (word + 0) from the step evaluation, so the address names no other trig
while the slide is in one of the track's places. While the sequencer plays, when a running slide's
count is the only one left, stock is done with the trig: the slide lets go and leaves its place, so
pslide keeps no list longer than stock does by more than a frame. A pending slide ends when its
list is evaluated again, and on the frame the sequencer stops. While it is stopped, stock evaluates
the first step again after each edit (into one record, `0x446484c4`, and the same list) and at PLAY
copies that record, list pointer and all, into the event that plays, so a pending slide made while
stopped waits for PLAY. That list's count is 0 before and after PLAY: stock never frees it, and the
allocator (`0x40138986`) neither checks for an empty free list nor that a list it gives out is
free. So a slide holds no list whose count is 0: its release would put a list in use on the free
list, give it out twice and empty the free list, and the trigs after it would play without locks.

## Time

The audio interrupt adds 2 x `0x402a0dec` (BPM x 120) to a position counter (`0x80005398`) in
every frame: 28,800 at 120 BPM. A tick of the sequencer is 900,000, and a step is the ticks of
the track's speed (`0x401f6b08`: 3, 4, 6, 8, 12, 24 or 48; per-track mode at pattern + 122201
takes the track's scale at + 1167, else the pattern's at + 122202). A slide's length is in these
units, so a tempo change, or an external clock, changes the rest of the slide.

## Which code interrupts which

Step evaluation runs below the audio-frame interrupt. In the prototype's `drum-full` run none of
3,577 step evaluations started inside an audio frame, and audio frames interrupted 99 of them.
So `prepare` masks interrupts while it changes a track's slides, and the hooks of one note, which
run in the audio frame, see no slide change state between them.

## The load

The note path runs in the audio interrupt before the smoother call that `ev_frame` sits at (about
13,300 and 17,000 instructions into the interrupt). A note or a lock trig sets the frame in which
no slide moves, so the frame routine returns at once in the frames where stock does its own note
work. In the other frames the rate follows the running slides' writes (entries x voices): every
frame up to BUDGET, every second frame up to twice it, every fourth above. A slide's voice is due
when (voice + phase + frame) & divisor is 0, its phase the next in turn counted from its first
voice: slides on one voice take turns by phase, and the voices of one slide by number. A slide ends
once each voice that follows it has had its targets. A slide catches up by the clock. A slide on
one voice, when due, writes each value as it computes it; one on more voices computes its values,
then writes each due voice.

A start costs about what stock's applier costs for the same locks. Before stock's restore, the note
hook clears the voice's lock bits of the slots the slide writes (the restore would set them to the
sound's value, which the start overwrites). When the voice keeps its sound (stock loads a sound
whole when the event names one at + 64 or the voice has another, `0x40026bae..0x40026bee`), the
restore and the applier leave those slots. The voice then takes each start value from the track's
last voice in that hook (`sv_take`), and the hook after the applier sets their lock bits
(`queue_note`). The rest of the start waits in a queue for a later frame or the next lock trig
(`drain`): the entries' values, read back from the voice, and the owners. It keeps the note's clock,
and no slide moves in the note's frame, so the wait changes no value. A later note of the same trig
in that frame (a chord) takes its values from the note before it in the same way, so its join at
the drain claims owners and lock bits only: a knob or CC written to its voice since its frame
stays. A whole-sound load starts its slide at once, after the applier.

A trig whose sound has another machine or filter type than the track's last voice's sound, or
than the track's own sound in the kit when the track has no voice of its own, changes at once. The
note path finds the kit's sound of track t at `[0x800052a0]` + 52 + 1163 t (`0x40026714`).

The applier gets the trig's own list, as on stock, so a mod that reads the list there (arpplocks'
arp locks past the stock entries, + 828) reads it unchanged. At step evaluation prepare moves the
locks that do not slide to the front of the list, and for a note of the slide the list's count is
lowered to them for the applier's call, then put back. When every lock slides the applier is not
called, if its first instruction is stock's (`lea -44(%sp),%sp`): stock's applier then writes
nothing. A mod that has hooked its entry is called (arpplocks' check of the last note's list
needs every call).

## STOP and a pattern change

A running slide ends where it is when the sequencer stops (`0x42c5a918`). The sequencer
switches the playing pattern's pointer (`0x42c5a9a0`) when it evaluates the new pattern's first
step, as the old pattern's last step begins. Its step word (`0x42c5a91c`, + 1 in the step routine
at `0x400da536`) changes a tick before each step plays: 30.3 and 31.4 frames before the step's
note in the emulator, a tick being 31.25 frames at 120 BPM. So a slide of the old pattern ends
one tick of the clock after the step word next changes, in the frame the new pattern starts.
Stock's switch sets the step word to the new pattern's first step, 0 (its start step). directjump's
switch sets it to the playing position, and that step of the new pattern plays one tick later
(measured with a trig on every step of the new pattern, 2026-11-25: the switch in frame 2,406 with
the step word 13 -> 14 and the first note in 2,437; stock's 15 -> 0 in 2,781 and its first note in
3,000). So after a switch that leaves the step word at another step than 0, the old pattern's
slides end one tick of the clock later. A direct jump that starts the new pattern at its step 0 (a
shorter pattern, at a position its length divides) reads as stock's, and its slides end a step late.
"""

from __future__ import annotations

import argparse
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from dnfw import osport                                       # noqa: E402
from dnfw.checkout import resources_dir                      # noqa: E402
from dnfw.cli.files import read_image                        # noqa: E402
from dnfw.container.section import compress                  # noqa: E402
from dnfw.firmware import build as fwbuild                   # noqa: E402
from dnfw.firmware.load import load                          # noqa: E402
from dnfw.mods import bus, platform                          # noqa: E402
from dnfw.patch.assemble import assemble, available          # noqa: E402

from dump_param_sets import Records, build_tables            # noqa: E402
from pslide_engine import ENGINE                             # noqa: E402
from pslide_notes import NOTES                               # noqa: E402
from pslide_prepare import NEXT, STARTS                     # noqa: E402
from pslide_ui import UI                                     # noqa: E402

MAIN_OS = 3
BASE = 0x40000400

# RAM above BSS for this mod: the code, then its state (BSS), clear of every other mod's.
CODE_VA = 0x46C00000

# stock routines and state
SRC = 0x80003AF0                # each voice's targets: word 17 + 101 voice + slot
STATE = 0x8000DE60              # each voice's smoother state, 16.16, the same indexing
VOICE_TRACK = 0x80005308        # longs by voice: the track that owns it
VOICE_SOUND = 0x800052A8        # longs by voice: the sound it has
KIT = 0x800052A0                # the kit the note path reads a track's own sound from
LOCKMASK = 0x4664B26C           # 16 bytes by voice: a bit per slot that a lock wrote
CLOCK = 0x80005398              # the position counter, + 2 x (BPM x 120) each audio frame
PLAYING = 0x42C5A918            # the sequencer plays: 1
PATTERN = 0x42C5A9A0            # the playing pattern, switched as its first step is evaluated
STEP_WORD = 0x42C5A91C          # the sequencer's step in the pattern (word), + 1 a tick before each step plays
TICK_UNITS = 900_000            # a sequencer tick in clock units
APPLIER = 0x400DB092            # (voice, list, SRC): a lock list onto a voice
APPLIER_ENTRY = 0x4FEFFFD4      # its first instruction on stock, lea -44(%sp),%sp (h_apply reads it)
LIST_RELEASE = 0x401389A8       # (list): one count off a lock list, freed at zero
TICKS_PER_STEP = 0x401F6B08     # longs by scale: 3, 4, 6, 8, 12, 24, 48
FRAME_FLAG = 0x4058E550         # cleared after each note's locks (the instruction h_post moves)

# offsets in stock's records
SOUND_VALUES = 20               # a sound's value of slot s: word at + 20 + 2 s
SOUND_MACHINE = 222             # ... its machine type (byte)
SOUND_FILTER = 223              # ... its filter type (byte)
SOUND_BYTES = 1163              # a sound's record, and the stride of the kit's sounds
KIT_SOUND = 52                  # the kit's sound of track t: + 52 + 1163 t
SRC_HEADER_BYTES = 34           # a voice's block: 17 words before slot 0
STATE_VOICE_BYTES = 404         # a voice's STATE block: 101 longs
SLOTS = 101                     # a voice's values
TRACK_STRIDE = 1701             # a track's data, from the pattern's start
TRACK_LENGTH = 1164             # ... its length (word), in per-track mode
TRACK_SCALE = 1167              # ... its scale (byte), in per-track mode
LOOP_COUNT = 1444               # ... with Page Loop on, the looped steps (byte), else 0
LOOP_STEPS = 1445               # ... then the step of each looped place (words)
PATTERN_LENGTH = 122196         # the pattern's length (word)
SCALE_MODE = 122201             # nonzero: per-track mode
MASTER_SCALE = 122202           # the pattern's scale (byte)
LOCK_FLAGS = 120128             # a byte per track (128) and step: the step has locks
LOCK_IDS = 118512               # a byte per track (101) and slot: its lock record, -1 none
LOCK_VALUES = 97874             # a record's value for a step: + 258 record + 2 step, 0xffff none
LOCK_RECORD_BYTES = 258

# SLD in the step's flag word: value v = bit 0 in 0x0008, bit 1 in 0x0020, bit 2 in 0x0040
SLD_BITS = 0x68
SLD_NEXT = 7
HALF_TICK_UNITS = 28125         # 450,000 / 16: a half-step is ticks per step x this, in clock / 16

# the engine's sizes
MAX_ENTRIES = 101
HEADER_BYTES = 100              # each buffer: its header, then its entries (B_ENT)
BUF_SIZE = -(-(HEADER_BYTES + 8 * MAX_ENTRIES) // 16) * 16   # each buffer on a line of the cache (16 bytes)
POOL_N = 96
HEADER_LONGS = HEADER_BYTES // 4  # what a lock trig's voice slide copies before its entries
BUDGET = 512                    # value writes in a frame before slides move every second frame
BUDGET2 = 2 * BUDGET            # above it, every fourth frame
MACHINES = 4                    # stock's machines with an eligibility row (Waverider: shared only)
FILTERS = 6

# TRIG PAGE 2 (scripts/pslide_ui.py)
RENDERER = 0x40065A0C           # (page, canvas): the parameter pages' renderer
KNOB_HANDLER = 0x40067470       # (page, event): the parameter pages' knob handler
PARAM_OF = 0x40063F24           # (page, knob index): the page's parameter at that knob, 0 none
RTRG_ID = 0x132                 # RTRG's parameter, knob A of TRIG PAGE 2
KNOB_E = 5                      # an event's code for knob E (1..8: knobs A..H)
EVENT_CODE = 12                 # an event's code
EVENT_DELTA = 16                # ... a knob's counts
COUNTS_PER_UNIT = 28            # a knob's counts for one unit of LEN or NOTE
PAGE_APP = 0x68                 # a page's application
PAGE_UI = 0x6C                  # ... its UI state
HELD_BITS = 0x258               # the UI state's held steps, a bit each (step % 32 of long step / 32)
HELD_ANY = 0x268                # ... nonzero while a trig is held
SELECTED_TRACK = 0x4003EFDE     # (application): the selected track's object
TRACK_DATA = 0x10               # a track object's step flags, a word each
DATA_SLOT = 0x28                # a track context's vtable: its step flags
FLAG_SETTER = 0x40054690        # (track object, step, mask, on): a step's flag
FLAG_GET = 0x4004E95A           # (track, step, mask): a step's flag, 1 or 0
GET_0020 = 0x4004EA24           # (track, step): flag 0x0020
SET_0020 = 0x40054A2C           # (track, step, on): flag 0x0020
REDRAW = 0x4011C7BA             # (page): draw it again
FILL = 0x40114842               # (canvas, x0, y0, x1, y1, mode): 0 clears, > 0 sets, < 0 inverts
OUTLINE = 0x40114626            # (canvas, x0, y0, x1, y1, 1): a box
TEXT = 0x4011545C               # (canvas, font, x, y, alignment, format, ...)
LABEL = 0x40115668              # (canvas, font, x, y, 1, 0, width template, format, ...)
FONT_COPY = 0x40115E6C          # (copy, font): an 8-byte font object for TEXT
FONT_RELEASE = 0x40115CE8       # (copy)
VALUE_FONT = 0x40293C64         # LEN's value font
LABEL_FONT = 0x40291760         # the knobs' label font
SLD_BOX_X, SLD_BOX_Y = 24, 7    # knob E's place: LEN's box at E's cell (24, 0)
SLD_BOX_X1, SLD_BOX_Y1 = 43, 24 # ... the dots of the empty place, cleared under it
SLD_LABEL_Y = 0
SLD_CLEAR = 0xFF97              # a flag word without SLD

# the eligibility rule (issue #391): an LFO destination with a maximum of 0x5000 or more
TABLE = 0x401F7F94              # stock's parameter records (scripts/dump_param_sets.py)
MODULATION_BITS = 0x1E00
MINIMUM_MAXIMUM = 0x5000
F_MAXIMUM, F_MODULATION = 12, 36

# the hooks: (va, the stock bytes it replaces, the label, jmp or jsr)
PREP = 0x400D8AE2               # step evaluation: move.l %fp,84(%a3) ; move.l %a3,%d0
PREP_BACK = PREP + 6
PRE = 0x40026BAC                # note path: movea.l %d2,%a4 ; move.l 64(%a0),%d0
PRE_BACK = PRE + 6
APPLY = 0x40026C34              # note path: jsr 0x400db092
POST = 0x40026C3E               # note path: clr.l 0x4058e550
POST_BACK = POST + 6
LOCK = 0x40026642               # lock-trig loop: pea SRC ; move.l %d0/%d2 ; movea.l %d6,%a1 ; jsr (%a1)
LOCK_BACK = LOCK + 14
UI_DRAW = 0x4006DDE6            # TRIG page draw: jsr 0x40065a0c
UI_KNOB = 0x4006DF1A            # TRIG page knobs: jsr 0x40067470
PUSH = 0x4006793E               # the parameter pages' key handler, a knob's push or release: tst.l %d3 ; beq.w
PUSH_BACK = PUSH + 6            # ... the handling of the knob's parameter
PUSH_NONE = 0x40067A30          # ... its return for a knob with no parameter
IS_RELEASE = 0x40116040         # (event): 1 for a key's release (bit 4 of + 16)
KNOB_E_PUSH = 4                 # the key handler's knob for knob E's push: its code, 45, less 41
COPY = 0x40053E1A               # trig copy: mvs.b %d0,%d0 ; move.l %d0,-64(%fp)
COPY_BACK = COPY + 6
PASTE = 0x400555C2              # trig paste: move.l %d3,-(%sp) ; jsr 0x4018b1c6
PASTE_CALL = 0x4018B1C6
PASTE_BACK = PASTE + 8
EUC_READ = 0x400550DA           # FREEZE TRACK: jsr 0x4004ea24 (pc) ; move.l %d2,-(%sp)
EUC_READ_BACK = EUC_READ + 6
EUC_SET = 0x4005520A            # FREEZE TRACK: move.l %d3/%d2/%a2,-(%sp) ; jsr 0x40054a2c (pc)
EUC_SET_BACK = EUC_SET + 10
CLEAR_MASK = 0x4004FD36         # a trig's own settings cleared: andi.l #0x7fff -> #0x7f97
HOOKS = (      # (va, the stock bytes it replaces, the label, jmp or jsr, what)
    (PREP, bytes.fromhex("274e0054200b"), "h_prep", "jmp", "step evaluation -> a trig's slide"),
    (PRE, bytes.fromhex("284220280040"), "h_pre", "jmp", "a note, before the restore -> its start values"),
    (APPLY, bytes.fromhex("4eb9400db092"), "h_apply", "jsr", "a note's applier call -> the other locks"),
    (POST, bytes.fromhex("42b94058e550"), "h_post", "jmp", "a note, after the applier -> start or join"),
    (LOCK, bytes.fromhex("487980003af02f002f0222464e91"), "h_lock", "jmp",
     "a lock trig's applier call, per voice -> its slide"),
    (UI_DRAW, bytes.fromhex("4eb940065a0c"), "ui_draw", "jsr", "the TRIG page's renderer call -> SLD"),
    (UI_KNOB, bytes.fromhex("4eb940067470"), "ui_knob", "jsr", "the TRIG page's knob handler call -> knob E"),
    (PUSH, bytes.fromhex("4a83670000ee"), "ui_push", "jmp",
     "a knob's push or release, the knob with no parameter -> knob E's release takes SLD off"),
    (COPY, bytes.fromhex("71002d40ffc0"), "copy_hook", "jmp", "trig copy -> SLD in the clipboard"),
    (PASTE, bytes.fromhex("2f034eb94018b1c6"), "paste_hook", "jmp", "trig paste -> SLD from the clipboard"),
    (EUC_READ, bytes.fromhex("4eba99482f02"), "euc_read", "jmp", "FREEZE TRACK's read of 0x0020 -> and 0x0040"),
    (EUC_SET, bytes.fromhex("2f032f022f0a4ebaf81a"), "euc_set", "jmp", "FREEZE TRACK's set of 0x0020 -> and 0x0040"),
)
# (va, stock bytes, new bytes, what): data that changes in place
EDITS = (
    (CLEAR_MASK, bytes.fromhex("028000007fff"), bytes.fromhex("028000007f97"),
     "a trig's own settings cleared: SLD with RTRG's lock bit"),
)
LABELS = ("slide_frame", "h_prep", "h_pre", "h_apply", "h_post", "h_lock", "update", "prepare", "next_step",
          "next_entries", "ns_loop",
          "prep_next", "start_values", "sv_sound", "sv_drop", "note_start", "note_join",
          "lock_slide", "release", "u_arrive", "add_entry", "slot_slides", "set_length", "ui_draw",
          "ui_knob", "copy_hook", "paste_hook", "euc_read", "euc_set", "set_sld", "sld_bits",
          "f_stopped", "f_cut", "u_foreign", "w_owner", "sv_machine", "n_join", "m_vserial",
          "m_vslide", "l_slides", "u_taken", "u_back", "w_alone", "let_go", "w_stale", "frame_work", "frame_exit", "wv_each",
          "p_uncounted", "f_note", "w_due", "u_all", "sv_returns",
          "a_none", "p_whole", "sv_claim", "u_one", "u_single", "us_each", "u_foreign_all",
          "w_owner_all", "a_stock", "a_part", "l_part", "p_dropped", "p_early",
          "p_preview", "preview_off", "drop_earlier", "p_nolist", "w_unplayed", "u_foreign_end",
          "p_next_machine", "last_voice", "l_machine", "revoke", "l_revoke", "k_held", "p_track", "ui_push",
          "p_knob", "p_release", "p_page", "d_locked", "drain", "drain_due", "queue_note", "d_later",
          "d_join", "d_dropped", "d_values", "d_claim", "lv_kit", "q_full", "q_whole", "q_later", "p_queued", "s_target", "s_novel", "bss_start")

# Read, not written: the code the hooks rely on.
CONTEXT = (
    (0x400D866A, bytes.fromhex("223c000006a5"), "step evaluation: d1 = 1701 x the track, then a5 (0x400d8688)"),
    (0x400D8A82, bytes.fromhex("d5cd"), "step evaluation: a2 = the pattern + a5, the track's data, at the hook"),
    (0x400D8996, bytes.fromhex("27400054"), "step evaluation: the list at + 84"),
    (0x400D89A8, bytes.fromhex("d3fc0001d540"), "step evaluation: the has-locks bytes, + 120128"),
    (0x400D89F6, bytes.fromhex("27440010"), "step evaluation: the track at + 16"),
    (0x400D8A98, bytes.fromhex("27420038"), "step evaluation: the flags at + 56"),
    (0x400D8AC4, bytes.fromhex("2748003c"), "step evaluation: the sound at + 60"),
    (0x400D8640, bytes.fromhex("7465b48066c2"), "the lock-list builder: slots 0 to 100, its bound"),
    (0x400D860C, bytes.fromhex("752a50a0"), "the lock-list builder: the record by track and slot"),
    (0x400D8622, bytes.fromhex("79702a02"), "the lock-list builder: the record's value for the step"),
    (0x400DA156, bytes.fromhex("12351800660c207c0001dd547d75880060047d6a"),
     "the next step wraps at the pattern's length, or + 1164 per track"),
    (0x400DA174, bytes.fromhex("1c2a05a467047d86"), "with Page Loop, at + 1444"),
    (0x400265C0, bytes.fromhex("2c3c400db092"), "lock-trig loop: the applier in d6, which h_lock calls directly"),
    (0x40026708, bytes.fromhex("24280040661a2428003c6614343c048b4c032800068200000034d4b9800052a0"),
     "note path: a note's sound, event + 64, else + 60, else the kit's: 1163 x track + 52 + [0x800052a0]"),
    (0x40026BB2, bytes.fromhex("49ec05ee670e"), "note path: a sound at event + 64 loads whole into the voice"),
    (0x40026BC6, bytes.fromhex("2028003c660a202eff90d0b9800052a0b0b3cc006706"),
     "note path: event + 60 (or the kit's) against the voice's sound, a3 = SRC: VOICE_SOUND by voice"),
    (0x40026C0E, bytes.fromhex("487980003af02f024eb9400daf44"), "note path: the restore, before the applier"),
    (0x40026C20, bytes.fromhex("206effdc20280054"), "note path: the event's list"),
    (0x40027B04, bytes.fromhex("2239402a0dec2001d080"), "audio interrupt: the clock's rate, twice"),
    (0x40027B16, bytes.fromhex("23c880005398"), "audio interrupt: the clock"),
    (0x400DAF7C, bytes.fromhex("d1fc4664b26c"), "the restore: the lock bits"),
    (0x400DAFB2, bytes.fromhex("776b0014"), "the restore: the sound's value at + 20 + 2 slot"),
    (0x400DB0BE, bytes.fromhex("41ea0014"), "the applier: the entries from + 20"),
    (0x400DB0D4, bytes.fromhex("b2aa0008"), "the applier: the count at + 8"),
    (0x400DB0FC, bytes.fromhex("8fb10c00"), "the applier: the lock bit"),
    (0x4002585A, bytes.fromhex("4feffff048d7041c"), "the parameter write to every voice of a track"),
    (0x401F6B08, bytes.fromhex("000000030000000400000006000000080000000c0000001800000030"), "ticks per step by scale"),
    (0x400DA536, bytes.fromhex("303942c5a91c7a0133c042c5a920528033c042c5a91c"),
     "the sequencer's step routine: the step word + 1"),
    # the entry of each stock routine the code calls
    (0x401389A8, bytes.fromhex("2f02206f0008"), "the lock list's release"),
    (0x40054690, bytes.fromhex("4e56ffe448d7"), "the step flag setter"),
    (0x4004E95A, bytes.fromhex("2f02206f0008"), "the step flag getter"),
    (0x4004EA24, bytes.fromhex("487800202f2f"), "the getter of flag 0x0020"),
    (0x40054A2C, bytes.fromhex("71af000f2f00"), "the setter of flag 0x0020"),
    (0x40063F24, bytes.fromhex("2f027008206f"), "a page's parameter at a knob"),
    (0x4003EFDE, bytes.fromhex("2f0a2f02246f"), "the selected track's object"),
    (0x4011C7BA, bytes.fromhex("206f00044a28"), "a page's redraw"),
    (0x40114842, bytes.fromhex("4fefffd448d7"), "the canvas fill"),
    (0x40114626, bytes.fromhex("4fefffd448d7"), "the canvas box"),
    (0x4011545C, bytes.fromhex("4e56ff4c48d7"), "the canvas text"),
    (0x40115668, bytes.fromhex("4e56ff44202e"), "the canvas label"),
    (0x40115E6C, bytes.fromhex("206f000420bc"), "the font copy"),
    (0x40115CE8, bytes.fromhex("206f000420bc"), "the font release"),
    (0x4018B1C6, bytes.fromhex("206f00042010"), "the trig paste's write"),
    (0x40065A0C, bytes.fromhex("4fefffbc48d7"), "the parameter pages' renderer"),
    (0x40067470, bytes.fromhex("4e56ffb048d7"), "the parameter pages' knob handler"),
    (0x40116040, bytes.fromhex("206f00047201"), "a key event's release test"),
    # the parameter pages' key handler, at the push hook
    (0x40067884, bytes.fromhex("242e000c"), "the key handler: d2 = the event"),
    (0x4006788E, bytes.fromhex("246e0008"), "the key handler: a2 = the page"),
    (0x40067916, bytes.fromhex("4e94205228000684ffffffd72f042f0a206800bc4e90"),
     "the key handler, a knob's push: d4 = the knob (the code less 41), the page's parameter at it"),
    (0x4006792C, bytes.fromhex("2f002600"), "the key handler: d3 = that parameter, at the hook"),
    (0x40067A30, bytes.fromhex("760160000990"), "the key handler's return for a knob with no parameter"),
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCKS = {"1.11": "00_Firmware/Digitone_II_OS1.11_dist.zip", "1.12": "00_Firmware/Digitone_II_OS1.12.syx"}
STOCK = resources_dir() / STOCKS["1.11"]
OUT = resources_dir() / "02_Builds/pslide_DN2_1.11.syx"

DATA = """
    .balign 4
elig_shared:
{ELIG_SHARED}
elig_machine:
{ELIG_MACHINE}
elig_filter:
{ELIG_FILTER}
    .balign 16
bss_start:
    .equ g_frame, bss_start + 0
    .equ g_start, bss_start + 4
    .equ g_head, bss_start + 8
    .equ g_free, bss_start + 12
    .equ g_bump, bss_start + 16
    .equ g_div, bss_start + 20
    .equ g_wsum, bss_start + 24
    .equ g_rr, bss_start + 28
    .equ g_note, bss_start + 32
    .equ g_lock_list, bss_start + 36
    .equ g_lock_n, bss_start + 84
    .equ g_lock_save, bss_start + 88
    .equ g_knob, bss_start + 40
    .equ g_ptn, bss_start + 44
    .equ g_cut_step, bss_start + 48
    .equ g_cut_wait, bss_start + 52
    .equ g_cut_at, bss_start + 56
    .equ g_cut_now, bss_start + 60
    .equ g_owned, bss_start + 64
    .equ g_played, bss_start + 68
    .equ g_stop_edge, bss_start + 72
    .equ g_due, bss_start + 76
    .equ g_due_now, bss_start + 80
    .equ g_qn, bss_start + 92
    .equ g_qframe, bss_start + 96
    .equ g_qclock, bss_start + 100
    .equ tracks, bss_start + 128
    .equ vslide, tracks + 16 * T_SIZE
    .equ vserial, vslide + 64
    .equ g_queue, vserial + 16
    .equ owners, g_queue + 8 * QUEUE_N
    .equ pool, owners + {OWNERS_BYTES}
"""
OWNERS_BYTES = 16 * 2 * SLOTS          # a word for each voice and slot
QUEUE_N = 16                           # the starts one frame's notes queue: a note per voice
BSS_BYTES = 128 + 16 * 64 + 64 + 16 + 8 * QUEUE_N + OWNERS_BYTES + POOL_N * BUF_SIZE


def masks(stock: bytes, os: str = "1.11") -> dict[str, list[tuple[int, int, int, int]]]:
    """The slots that slide, from stock's own records: the shared pages, each machine's and each
    filter type's. A slot slides when stock offers it as an LFO destination and its maximum is
    0x5000 or more. Each mask is four longs, slot s at bit s % 32 of long s // 32."""
    records = Records(stock, osport.addr(os, TABLE))
    tables = build_tables(records)

    def mask(record_ids) -> tuple[int, int, int, int]:
        slots = [records.field(r, 4) for r in record_ids
                 if records.field(r, F_MODULATION) & MODULATION_BITS
                 and records.field(r, F_MAXIMUM) >= MINIMUM_MAXIMUM]
        return tuple(sum(1 << (s % 32) for s in slots if s // 32 == k) for k in range(4))
    machine = [mask(v for k, v in tables["machine"].items() if k // 40 == m) for m in range(MACHINES)]
    filters = [mask(v for k, v in tables["filter"].items() if k // 3 == f) for f in range(FILTERS)]
    return {"shared": [mask(tables["sound"].values())], "machine": machine, "filter": filters}


def longs(rows: list[tuple[int, int, int, int]]) -> str:
    return "\n".join("    .long " + ", ".join(f"{w:#010x}" for w in row) for row in rows)


def overrides(os: str) -> dict:
    """What the map cannot place: each hook's return address, which no instruction names, is the
    hook's site on OS (whose displaced bytes `compose` checks) plus the bytes it displaces"""
    sites = {"PREP": PREP, "PRE": PRE, "POST": POST, "LOCK": LOCK, "COPY": COPY, "PASTE": PASTE,
             "EUC_READ": EUC_READ, "EUC_SET": EUC_SET, "PUSH": PUSH}
    return {f"{name}_BACK": osport.addr(os, va) + globals()[f"{name}_BACK"] - va for name, va in sites.items()}


def source(stock: bytes, os: str = "1.11") -> str:
    """The routines for OS, their stock addresses through `dnfw.osport`, and the eligibility tables
    read from STOCK"""
    m = masks(stock, os)
    text = osport.render(ENGINE + STARTS + NEXT + NOTES + UI, globals(), os,
                         None if os == "1.11" else overrides(os))
    return text + DATA.format(ELIG_SHARED=longs(m["shared"]), ELIG_MACHINE=longs(m["machine"]),
                              ELIG_FILTER=longs(m["filter"]), OWNERS_BYTES=OWNERS_BYTES)


def assemble_code(text: str, base: int) -> tuple[bytes, dict[str, int]]:
    """Assemble once and read each label's address off a trailing table."""
    table = "\n".join(f"    .long {name}" for name in LABELS)
    blob = assemble(text + "\n    .balign 4\n" + table + "\n", base=base)
    width = 4 * len(LABELS)
    addrs = struct.unpack(">%dI" % len(LABELS), blob[-width:])
    return blob[:-width], dict(zip(LABELS, addrs))


def compose(stock: bytes, log=print, os: str = "1.11") -> dict:
    """Apply the build to a stock MAIN OS. -> {content, blob, labels, bss, frame}: the hooked image,
    the code for a platform `CODE` chunk at CODE_VA with BSS bytes after it, and the frame
    handler's address for the hook bus."""
    def site(va, want, why):
        try:
            return osport.site(os, va, want, stock, BASE)
        except osport.NotPorted as exc:
            raise SystemExit(f"{why}: {exc}") from None
    if not available():
        raise SystemExit("no m68k assembler found")
    content = bytearray(stock)

    log("part 1 -- the code this relies on, asserted")
    for va, want, why in CONTEXT:
        va, want = site(va, want, why)
        log(f"  {va:#010x}  {want.hex():<24}  {why}")

    log(f"part 2 -- the code, from {CODE_VA:#010x}")
    payload, at = assemble_code(source(stock, os), CODE_VA)
    blob = payload + bytes(-len(payload) % 4)
    if at["bss_start"] != CODE_VA + len(blob):
        raise SystemExit("the state does not start where the code ends")
    log(f"  {len(payload)} bytes, then {BSS_BYTES} bytes of state")

    log("part 3 -- the hooks")
    for va, stock_bytes, label, how, _ in HOOKS:
        va, stock_bytes = site(va, stock_bytes, label)
        new = bytes.fromhex("4ef9" if how == "jmp" else "4eb9") + struct.pack(">I", at[label])
        new += bytes.fromhex("4e71") * ((len(stock_bytes) - len(new)) // 2)
        if len(new) != len(stock_bytes):
            raise SystemExit(f"hook at {va:#010x} does not fit {len(stock_bytes)} bytes")
        content[va - BASE:va - BASE + len(new)] = new
        log(f"  {va:#010x}  {stock_bytes.hex()} -> {new.hex()}  {how} {label}")
    for va, stock_bytes, new, what in EDITS:
        va, stock_bytes = site(va, stock_bytes, what)
        content[va - BASE:va - BASE + len(new)] = new
        log(f"  {va:#010x}  {stock_bytes.hex()} -> {new.hex()}  {what}")
    return {"content": bytes(content), "blob": blob, "labels": at, "bss": BSS_BYTES,
            "frame": at["slide_frame"]}


def chunks(built: dict) -> list[tuple[bytes, bytes]]:
    """The platform chunks: the code with its state, and the frame handler's subscription."""
    code = platform.area.CodeChunk(CODE_VA, built["blob"], built["bss"]).pack()
    return [(platform.area.CODE, code), bus.subscribe(b"FRAM", built["frame"])]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", type=pathlib.Path, default=OUT)
    a = p.parse_args()
    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    if section is None:
        raise SystemExit("image has no MAIN OS section")
    built = compose(section.unpack())
    content = platform.join(built["content"], chunks(built))

    print("part 4 -- repack")
    if a.out.exists():
        raise SystemExit(f"{a.out} exists; builds are never overwritten")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    replacement = compress(section.id, section.dest, content)
    a.out.write_bytes(fwbuild.build(firmware, {MAIN_OS: replacement}))
    print(f"  wrote {a.out} ({a.out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
