"""Direct jump: a pattern cued in the PTN view starts at the next step, from where the playing one was.

    python scripts/build_direct_jump.py [--out PATH]

Stock 1.11 changes to a pattern cued with [PTN] + [TRIG] when the playing pattern ends (or at
its CHANGE). This build adds a switch, set in the PTN view: [UP] turns DIRECT JUMP on, [DOWN]
turns it off, and the view's message line says "Direct Jump ON" or "Direct Jump OFF". While it
is on, [PTN] lights magenta in the PTN view instead of white. Off, the
default and what a fresh instrument reads, the change is stock's. On, a cue made in the PTN view
while the sequencer plays starts on the next step, and the new pattern goes on from the
playing pattern's position, wrapped by its own length (the Analog Rytm's rule). Program
changes, chains and songs keep stock's change, except one that comes between a jump's cue
and the jump: the jump takes the newest cue.

## The PTN view's keys, read 2026-11-11 (OS 1.11)

The PTN view's key handler `0x400fa6be` is entry 2 of its vtable (`0x402008cc`, after the
typeinfo and two destructors). It switches on the key code less 10 (`0x400fa6dc`); UP (11),
DOWN (14) and FUNC (17) go to `0x400fabb0`, which returns "handled" and does nothing. So [UP]
and [DOWN] take nothing from stock here. The view shows its own messages ("Kit Change Cued",
`0x400fa246`) with `0x4005628c(this->+120, &std::string)`; ours does the same.

## The PTN view's LEDs, read 2026-11-11 (OS 1.11)

The PTN view (`PatternSelectView`) is also an `LedHandler`, at this + 104. Its LED method is
entry 2 of that base's vtable (`0x4020097c`): a thunk, `0x400fa6b4`, that takes 104 from
`this` and branches to `0x400fa408`. That method sets each key's LED through `0x4002c318(leds,
index, mode, colour)`, with `leds` from `0x4018aabc()`: mode 1 is off, 2 is lit. The setter
keeps the first value an LED gets in a frame (`0x4002c342`), and `0x40132148` sends the colour
to the panel's own controller, which decodes it. LED 4 is [PTN]: stock lights it white (`0x71`)
while the view shows patterns (`this + 137` set), and `0x83` in bank selection ([FUNC] +
[PTN], `this + 137` clear), and the emulator's colour cache (`0x466b7420`, one byte per panel
channel) shows that channel lit only in the PTN view. PATTERN MUTE mode lights the [TRIG] keys
`0x61`, the manual's magenta, where GLOBAL MUTE mode lights them `0x21`, green.

## How stock changes pattern (emulator, 2026-11-11)

The cue: the TRIG case calls `0x400fa11e`, which posts the entry with `jsr 0x400d93f0`
(`0x400fa1da`). The sequencer's tick routine reads the tick within the step (`0x400da406`; 0..5
at 1x, `0x401f6b08` by scale). On tick 2 it runs the queue path (`0x400da416`): it clears the
armed long `0x42c5aaac`, takes the queue's head into `%d0`, and at `0x400da45a` tests whether
this is the last step before the change (the change counter `0x42c5a91c` against CHANGE, or the
pattern's length at pattern + 122196). If so, `0x400da4d2` arms the switch: the next pattern in
`0x42c5a9a4`, start step 0 in `0x42c5a9c4`, armed 1. At the next step boundary (tick 0) the
counter is advanced and wrapped (`0x400da544`..`0x400da57e`), and then, armed, the switch: the
queue is advanced, the pattern installed (`0x42c5a9a0`), the start step copied to `0x42c5a9bc`
(`0x400da6e6`..`0x400da6f8`), every track rebuilt from it (`0x400da7c2`), and the counter set to
it (`0x400da804`). The sequencer prepares each step a step ahead: at step j it evaluates step
j + 1's conditions (`0x400d8752`), in the same instant as the frame interrupt voices step j and
sends it to the DSP (`0x40026980`, measured on stock, 2026-11-11). So a pattern armed on step g
plays its first step on step g + 2. Stock's own change has the same lag.

At the switch the counter holds the index of the step being posted, the step the new pattern
fills. So the Rytm's rule is that index, wrapped by the new pattern's length.

## What this build changes

| site | stock | here |
|---|---|---|
| `0x402008cc` | the PTN view's key handler `0x400fa6be` | `ptn_keys`: [UP] or [DOWN] pressed sets the switch and shows the message; all else stock's |
| `0x4020097c` | the PTN view's LED method, thunk `0x400fa6b4` | `ptn_leds`: with the switch on and the view showing patterns, [PTN] magenta first; then stock's |
| `0x400fa1e0` | after the PTN view's post: `lea 28(%sp),%sp ; move.l %a2,(%sp)` | `cue_hook`: with the switch on and the sequencer playing, the cue is `cued` |
| `0x400da406` | `move.b 0x42c5a91e,%d1` | `tick_hook`: `cued` on a tick past 0 runs the queue path now, forced; `ours` skips the queue path until the switch |
| `0x400da45a` | `mvs.w 0x42c5aab4,%d1` | `arm_hook`: forced, and the head is another pattern: arm at once (`ours`); the head is the playing pattern: stock's test on tick 2, else the tick ends |
| `0x400da6e6` | `lea 0x42c5a9c4,%a1` | `switch_hook`: for our switch, the start step from the counter, wrapped by the new pattern's length above 1 |
| `0x400d9e10` | `movea.l 0x42c5a9a0,%a5` | `early_hook`: our switch armed, on the real tick that ends the step: the queue pruned and stock's switch run now |
| `0x400da7a6` | `move.l #900000,%d7` | `kit_hook`: for an early switch, the kit event at T |
| `0x400da7c2` | `move.l #122201,%d0` | `phase_hook`: for an early switch, every track set to start the new pattern, then the preparation again |

A cue on tick 0 of step g is armed on tick 1, any other one on the next tick. On the last tick
of the step in which it is armed, the jump commits (below), and the new pattern plays from the
step after. The sequencer's ticks run a tick ahead of the steps it sends, so at 1x a cue in the
first two thirds of the step that sounds lands on the next step, and a later one on the step
after. Armed by us, stock's tick-2 queue path does not run again before the switch, so it cannot
clear the arming (`0x400da41c`), and a second cue before the switch is taken by it: the switch
installs whatever heads the queue. A cue after stock has armed its own change at the end of the
pattern is armed again by us: the counter has wrapped there, so it starts at step 0, as stock's
would.

## The next step (emulator, 2026-11-11)

Stock prepares each step P - 1 ticks before it sounds (`0x400d9ffa`, P the track's ticks per
step): when its switch runs, the step after the boundary is already in the timed queue (head
`0x44644228`), and the switch fills the step after that. So the jump commits at the start of the
preparation (`0x400d9e10`) in the interrupt that ends the step: a real tick (`0x42c4e908`
clear), the master tick on the step's last, the sequencer playing, no STOP pending, and the
switch armed:

1. `reclaim` frees the old pattern's queued events due from T on, with interrupts masked: a
   sequencer note-on or lock (kind `+4` 1, origin `+20` 1) for a voice (type 0, or 1 from a
   track's cache), a MIDI group whose payload is the sequencer's note-on (`+52` and `+12` 1), and
   the arp request (type 9) that stock queues for every audio track with each step it prepares
   (`0x400d9ee4`), with the arp on or off. Live input (origin 2), records stock has marked (-1),
   releases (other kinds), recurring clocks and configuration events stay. Timed note-offs are
   not in this queue: a voice counts its own down (`0x80005220`) and MIDI keeps its own lists,
   so a note that started before the jump ends at its length (`--case long`, `longmidi`). Each
   record is unlinked from its bucket before it is freed through stock's own routines (MIDI
   payload `0x4012a3d2`, record `0x40138a0c`, an emptied bucket `0x40138a84`). Stock's visitor
   (`0x40138afc`) reads a record's link after its callback, so it cannot free. Stock's own
   discard only marks records (`0x400d7674`, `0x400d7694`), and a marked record keeps its lock
   until its old due time: rapid jumps between slow tracks with arps then empty the 64-object
   lock pool (`scripts/emu_directjump.py --case pool`).
2. Stock's switch runs from `0x400da58e`, with the interrupt's own stack, so its locals stay
   where it reads them. `kit_hook` times its kit event at T, ahead of the new pattern's notes.
3. `phase_hook` replaces the bridge from the old pattern (`0x400da7c2..0x400da8c8`), which reads
   the old pattern's settings. `seed_destination` sets every track to start the switch's start
   step J: next step J wrapped by the track's length, phase 0, first-fire correction one tick
   less than the track's period (`0x400d9e88` prepares it one tick ahead), the condition cycle
   J wrapped by the looped steps with Page Loop on (`+1444`, as `0x400da174` wraps it), the
   master counter J and the master tick on the step's last. LST is off for that first step.
4. The preparation runs again from `0x400d9e10`, through stock's routing (`0x400d9edc`, which
   midiarp hooks), and the interrupt goes on as stock's.

A MIDI note group that the MIDI task is about to queue (`0x4012b478..0x4012b49e`) when the jump
interrupts it is not in the queue yet, so it still plays. Stock's own discard has the same
window at its pattern change.

## Where the switch lives

One byte of the settings block's unaddressed tail, `0x405cd8c1`, after reloadconfirm's
`0x405cd8ae` and arpscale's `0x405cd8af`: saved and restored with the block, zero on a fresh
instrument, written only through the stock setting writer (`scripts/build_personalize_toggle.py`,
`toggle`). It skips `0x405cd8b0..0x405cd8c0`, where the first degreetranspose builds (pull
request #212 before its rework) kept their amounts, so a unit that ran them can hold nonzero
bytes there. No absolute operand in MAIN OS names `0x405cd8ae..0x405cd95b` (the same scan finds
the payload's `0x405cd8a3` four times), and the 114 absolute references into the block below it
are followed (48 bytes each) by offsets that stay below `0x405cd8ae`. The settings defaults
clear `0x405cd85c..0x405cd8ad` only.

## OS 1.12 (issue #382, 2026-11-13)

`compose(stock, os="1.12")` builds from the same source. Every guard, hook and vtable entry goes
through `dnfw.osport.site`: of the 73 sites, 35 hold 1.11's bytes on 1.12 and 38 differ only in
address words that the map moves. The routines' stock addresses come through `dnfw.osport.render`,
and `CHANGE` has a name so that it moves with them. Every word that differs between the 1.11 and
1.12 code is a mapped address or the switch's byte. The chunk keeps `0x46790000`, above 1.12's
DMA section, and the code keeps its layout and its labels.

No instruction names the switch, so it moves with the settings block (`0x405cd85c` ->
`0x405ce85c`) to `0x405ce8c1`. The same scan as on 1.11 finds no absolute operand in 1.12's
MAIN OS in `0x405ce8ae..0x405ce95b`, and it finds the payload's `0x405ce8a3` four times.
"""

from __future__ import annotations

import argparse
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dnfw import osport
from dnfw.checkout import resources_dir
from dnfw.cli.files import read_image
from dnfw.container.section import compress
from dnfw.firmware import build as fwbuild
from dnfw.firmware.load import load
from dnfw.mods import platform
from dnfw.patch.assemble import assemble, available

import build_personalize_toggle as toggle
from build_personalize_toggle import STR_CTOR

MAIN_OS = 3
BASE = 0x40000400

# RAM above BSS, given to this mod: between lfowaves' code (..0x46780ab4) and arpmodes (0x467a0000).
CODE_VA = 0x46790000

FLAG = 0x405CD8C1               # the switch: the settings block's unaddressed tail, past degreetranspose's old amounts
SETTINGS = 0x405CD85C           # the settings block: FLAG is its byte +0x65
STR_DTOR = 0x401CCBEE
KEY_CODE = 0x40116018           # key event: its code
PRESSED = 0x401160BC            # ...pressed, not a repeat
MESSAGE = 0x4005628C            # (object, &string): the view's message line
MESSAGE_OBJECT = 120            # the PTN view's message object, this + 120 (0x400fa25a)
UP, DOWN = 11, 14               # the firmware's key codes (button table 0x401f3824)

PTN_KEYS_SLOT = 0x402008CC      # the PTN view's vtable: its key handler ...
PTN_KEYS = 0x400FA6BE           # ... this one
PTN_LEDS_SLOT = 0x4020097C      # the PTN view's LedHandler vtable (this + 104): its LED method ...
PTN_LEDS = 0x400FA6B4           # ... this thunk, to 0x400fa408
LED_MANAGER = 0x4018AABC        # () -> the LED object
SET_LED = 0x4002C318            # (leds, index, mode, colour); an LED keeps its first value in a frame
PTN_LED = 4                     # the [PTN] key's LED
LED_LIT = 2                     # mode: lit (1 is off)
MAGENTA = 0x61                  # PATTERN MUTE mode's colour (GLOBAL MUTE's green is 0x21)
SHOWS_PATTERNS = 137 - 104      # the view's + 137, from its LedHandler: set unless in bank selection
CUE_SITE = 0x400FA1E0           # after the PTN view's post of a cue (jsr 0x400d93f0 at 0x400fa1da)
CUE_DISPLACED = bytes.fromhex("4fef001c" "2e8a")  # lea 28(%sp),%sp ; move.l %a2,(%sp)
CUE_BACK = CUE_SITE + len(CUE_DISPLACED)
PLAYING = 0x42C5A918            # the sequencer plays: 1
TICK = 0x42C5A91E               # the tick within the step
TICK_SITE = 0x400DA406          # the tick routine reads it
TICK_DISPLACED = bytes.fromhex("123942c5a91e")    # move.b 0x42c5a91e,%d1
TICK_BACK = TICK_SITE + len(TICK_DISPLACED)
QUEUE_PATH = 0x400DA416         # tick 2: the queue's head, then the last-step test
TICK_END = 0x400DA902           # where every tick past the boundary ends
TEST_SITE = 0x400DA45A          # the last-step test's first instruction
TEST_DISPLACED = bytes.fromhex("737942c5aab4")    # mvs.w 0x42c5aab4,%d1 (CHANGE)
CHANGE = 0x42C5AAB4             # the playing pattern's CHANGE (word)
TEST_BACK = TEST_SITE + len(TEST_DISPLACED)
ARM = 0x400DA4D2                # arm the switch to the head in %d0
PATTERN = 0x42C5A9A0            # the playing pattern
COUNTER = 0x42C5A91C            # the change counter: the index of the step being posted
START = 0x42C5A9C4              # the start step the switch takes
START_SITE = 0x400DA6E6         # the switch, before it copies the start step
START_DISPLACED = bytes.fromhex("43f942c5a9c4")   # lea 0x42c5a9c4,%a1
START_BACK = START_SITE + len(START_DISPLACED)
LENGTH = 122196                 # a pattern's length (word), from its start; 1 or less is INF

NAME_ON = "Direct Jump ON"
NAME_OFF = "Direct Jump OFF"

LABELS = ("ptn_keys", "ptn_leds", "cue_hook", "tick_hook", "arm_hook", "switch_hook",
          "early_hook", "kit_hook", "phase_hook")

SOURCE = """
| The PTN view's key handler (this, event), through its vtable. [UP] or [DOWN] pressed: the
| switch on or off, and the message; their releases and repeats: handled, as stock's. All
| else: stock's handler.
ptn_keys:
    move.l  8(%sp),-(%sp)
    jsr     {KEY_CODE:#x}
    addq.l  #4,%sp
    moveq   #{UP},%d1
    cmp.l   %d1,%d0
    beq.s   1f
    moveq   #{DOWN},%d1
    cmp.l   %d1,%d0
    beq.s   1f
    jmp     {PTN_KEYS:#x}
1:  move.l  %d2,-(%sp)
    move.l  %d0,%d2
    move.l  12(%sp),-(%sp)
    jsr     {PRESSED:#x}
    addq.l  #4,%sp
    tst.b   %d0
    beq.s   9f
    moveq   #{UP},%d0
    cmp.l   %d0,%d2
    seq     %d2
    andi.l  #1,%d2                      | 1: on
    move.l  %d2,-(%sp)
    bsr.w   set
    addq.l  #4,%sp
    lea     msg_on,%a0
    tst.l   %d2
    bne.s   2f
    clr.b   cued                        | off: a cue not yet armed changes as stock's
    lea     msg_off,%a0
2:  move.l  %a0,-(%sp)
    move.l  12(%sp),-(%sp)              | this
    bsr.w   message
    addq.l  #8,%sp
9:  move.l  (%sp)+,%d2
    moveq   #1,%d0                      | handled
    rts

| (view, text): the view's message line shows TEXT, as the view's own messages do (0x400fa246).
message:
    link    %a6,#-8
    pea     -5(%a6)                     | the string's allocator
    move.l  12(%a6),-(%sp)
    pea     -4(%a6)                     | the string
    jsr     {STR_CTOR:#x}
    pea     -4(%a6)
    move.l  8(%a6),%a0
    move.l  {MESSAGE_OBJECT}(%a0),-(%sp)
    jsr     {MESSAGE:#x}
    pea     -4(%a6)
    jsr     {STR_DTOR:#x}
    lea     24(%sp),%sp
    unlk    %a6
    rts

| The PTN view's LED method (this = the view + 104, ...), through its LedHandler vtable. The
| setter keeps an LED's first value in a frame, so with the switch on and the view showing
| patterns, [PTN] is set magenta before stock's method sets it white. Then stock's method,
| through its thunk, with the stack as it came.
ptn_leds:
    bsr.w   get
    tst.l   %d0
    beq.s   1f
    move.l  4(%sp),%a0
    tst.b   {SHOWS_PATTERNS}(%a0)
    beq.s   1f
    jsr     {LED_MANAGER:#x}
    pea     {MAGENTA:#x}
    pea     {LED_LIT}
    pea     {PTN_LED}
    move.l  %d0,-(%sp)
    jsr     {SET_LED:#x}
    lea     16(%sp),%sp
1:  jmp     {PTN_LEDS:#x}

| After the PTN view posted a cue, reached by jmp: the displaced instructions, then the cue
| is ours to jump when the switch is on and the sequencer plays.
cue_hook:
    lea     28(%sp),%sp
    move.l  %a2,(%sp)
    bsr.w   get
    tst.l   %d0
    beq.s   1f
    moveq   #1,%d0
    cmp.l   {PLAYING:#x},%d0
    bne.s   1f
    move.b  %d0,cued
1:  jmp     {CUE_BACK:#x}

| The tick routine, reached by jmp, with the tick in %d1 as stock reads it. Armed by us: no
| queue path before the switch, which is on tick 0. A cue of ours on any tick past 0: the
| queue path now, forced.
tick_hook:
    move.b  {TICK:#x},%d1
    tst.b   ours
    beq.s   1f
    tst.b   %d1
    beq.s   2f
    jmp     {TICK_END:#x}
1:  tst.b   cued
    beq.s   2f
    tst.b   %d1
    beq.s   2f
    moveq   #1,%d6                      | stock sets %d6 again in the queue path
    move.b  %d6,forcing
    jmp     {QUEUE_PATH:#x}
2:  jmp     {TICK_BACK:#x}

| The last-step test, reached by jmp, the queue's head in %d0. Forced and the head is another
| pattern: arm now, the switch ours. Forced and the head is the playing pattern: stock's test
| on tick 2, the end of the tick on any other.
arm_hook:
    tst.b   forcing
    beq.s   1f
    clr.b   forcing
    clr.b   cued
    cmp.l   {PATTERN:#x},%d0
    beq.s   2f
    moveq   #1,%d1                      | stock sets %d1 again before it reads it
    move.b  %d1,ours
    jmp     {ARM:#x}
2:  mvz.b   {TICK:#x},%d1
    subq.l  #2,%d1
    beq.s   1f
    jmp     {TICK_END:#x}
1:  mvs.w   {CHANGE:#x},%d1              | the displaced instruction
    jmp     {TEST_BACK:#x}

| The switch, reached by jmp, before it copies the start step. Ours: the start step is the
| counter (the step being posted), wrapped by the new pattern's length when that is above 1.
switch_hook:
    tst.b   ours
    beq.s   1f
    clr.b   ours
    mvz.w   {COUNTER:#x},%d0
    move.l  {PATTERN:#x},%a1
    move.l  #{LENGTH},%d1
    mvs.w   (0,%a1,%d1.l),%d1
    moveq   #1,%d2
    cmp.l   %d2,%d1
    ble.s   2f
    remu.l  %d1,%d2:%d0                 | %d2 = %d0 mod %d1
    move.l  %d2,%d0
2:  move.l  %d0,{START:#x}
1:  lea     {START:#x},%a1              | the displaced instruction
    jmp     {START_BACK:#x}

{toggle.toggle(FLAG, OS)}
msg_on:
    .asciz  "{NAME_ON}"
msg_off:
    .asciz  "{NAME_OFF}"
cued:
    .byte   0
ours:
    .byte   0
forcing:
    .byte   0
    .align  2
"""

# The next step. A jump commits in the interrupt that ends the cue's step, before stock prepares
# the step after it: the source's queued events from then on are freed, every track of the new
# pattern is set to start there, and stock's preparation runs again for it.
LOGICAL_TIME = 0x42C4E900       # T, a tick on at the start of each real tick
BETWEEN_TICKS = 0x42C4E908      # nonzero in the interrupts between real ticks
TICK_SPAN = 900000              # a tick of T
STOP_PENDING = 0x42C5A9E9
ARMED = 0x42C5AAAC              # set by the arming (0x400da520)
MASTER_SCALE = 0x42C5A9D8       # the master's index into TICKS_PER_STEP
TICKS_PER_STEP = 0x401F6B08     # longs by scale: 3, 4, 6, 8, 12, 24, 48
PER_TRACK_MASTER = 2            # in per-track mode the master runs at 1x
PREPARE = 0x400D9E10            # the preparation of upcoming steps, track by track
PREPARE_DISPLACED = bytes.fromhex("2a7942c5a9a0")   # movea.l 0x42c5a9a0,%a5
COMMIT = 0x400DA58E             # the switch, past the boundary's armed test
KIT_SITE = 0x400DA7A6           # the switch: the kit event's time
KIT_DISPLACED = bytes.fromhex("2e3c000dbba0")       # move.l #900000,%d7
BRIDGE_SITE = 0x400DA7C2        # the switch: each track's phase from the old pattern
BRIDGE_DISPLACED = bytes.fromhex("203c0001dd59")    # move.l #122201,%d0
UPDATE_LST = 0x40136980         # (0): LST from the cue queue's head
START_TAKEN = 0x42C5A9BC        # the start step, as the switch copied it
SCALE_MODE = 122201             # a pattern's scale mode (byte): 1 per track
MASTER_SCALE_OFFSET = 122202    # a pattern's master scale (byte)
TRACK_STRIDE = 1701             # a track's settings, from the pattern's start
TRACK_LENGTH = 1164             # ... its length (word)
TRACK_SCALE = 1167              # ... its scale (byte)
LOOP_COUNT = 1444               # ... with Page Loop on, the looped steps (byte), else 0
TRACK_SCALES = 0x42C5A9D9       # bytes by track: the scale in use
FIRST_FIRE = 0x42C5AA3C         # ... the first preparation's correction, in ticks
NEXT_STEPS = 0x42C5A964         # ... the next step
CONDITION_CYCLE = 0x42C5AAC8    # ... the condition cycle's position
CURRENT_STEPS = 0x42C5A984      # ... the current step
TRACK_TICKS = 0x42C5A974        # ... the tick within the step
COUNTDOWNS = 0x42C5AA2C         # ... the transition countdown
HOLD_MASK = 0x42C5AA2A          # word, a bit by track
FIRST_MASK = 0x42C5AA4C         # word, a bit by track
QUEUE = 0x44644228              # the timed event queue: its first bucket
FREE_MIDI = 0x4012A3D2          # (payload): a MIDI payload back to its pool, its lock released
FREE_RECORD = 0x40138A0C        # (record): an engine record back to its pool, its lock released
FREE_BUCKET = 0x40138A84        # (bucket)

NEXT_STEP = """
| The preparation's start, reached by jmp. Our jump armed, on the real tick that ends the step:
| free the source's queued events from T on, and run stock's switch, which comes back through
| phase_hook. Else the displaced instruction.
early_hook:
    tst.b   ours
    beq.w   9f
    tst.l   {BETWEEN_TICKS:#x}
    bne.w   9f
    moveq   #1,%d0
    cmp.l   {PLAYING:#x},%d0
    bne.w   9f
    tst.b   {STOP_PENDING:#x}
    bne.w   9f
    cmp.l   {ARMED:#x},%d0
    bne.w   9f
    mvz.b   {MASTER_SCALE:#x},%d0
    lea     {TICKS_PER_STEP:#x},%a0
    move.l  (0,%a0,%d0.l*4),%d4
    mvz.b   {TICK:#x},%d1
    addq.l  #1,%d1
    cmp.l   %d4,%d1
    bne.w   9f
    moveq   #1,%d0
    move.b  %d0,early_active
    move.l  {LOGICAL_TIME:#x},%d0
    subq.l  #1,%d0
    move.l  %d0,-(%sp)
    bsr.w   reclaim
    addq.l  #4,%sp
    jmp     {COMMIT:#x}
9:  move.l  {PATTERN:#x},%a5
    jmp     {PREPARE + len(PREPARE_DISPLACED):#x}

| The switch's kit event, reached by jmp: stock times it %d4 ticks on. For our jump, at T,
| ahead of the new pattern's first notes.
kit_hook:
    tst.b   early_active
    beq.s   1f
    clr.l   %d4
1:  move.l  #{TICK_SPAN},%d7
    jmp     {KIT_SITE + len(KIT_DISPLACED):#x}

| The switch's per-track bridge from the old pattern, reached by jmp. For our jump: every track
| set to start the new pattern, then the preparation again from its start. Else the displaced
| instruction.
phase_hook:
    tst.b   early_active
    beq.s   1f
    lea     -60(%sp),%sp
    movem.l %d0-%d7/%a0-%a6,(%sp)
    bsr.w   seed_destination
    movem.l (%sp),%d0-%d7/%a0-%a6
    lea     60(%sp),%sp
    clr.b   early_active
    jmp     {PREPARE:#x}
1:  move.l  #{SCALE_MODE},%d0
    jmp     {BRIDGE_SITE + len(BRIDGE_DISPLACED):#x}

| Every track of the new pattern starts on the switch's start step J: its next step J wrapped by
| its length, its phase 0, prepared one tick ahead, so it sounds at the boundary. Its condition
| cycle starts there too, wrapped by the looped steps with Page Loop on, as stock's advance wraps
| it. LST is off for the new pattern's first step: its cue has been taken. Stock sets LST from
| the queue again on the next tick (0x400d9926).
seed_destination:
    clr.l   -(%sp)
    jsr     {UPDATE_LST:#x}
    addq.l  #4,%sp
    move.l  {PATTERN:#x},%a3
    move.l  {START_TAKEN:#x},%d3
    move.w  %d3,{COUNTER:#x}
    move.l  #{SCALE_MODE},%d0
    mvz.b   (0,%a3,%d0.l),%d7
    move.l  #{MASTER_SCALE_OFFSET},%d0
    mvz.b   (0,%a3,%d0.l),%d1
    moveq   #1,%d0
    cmp.l   %d0,%d7
    bne.s   1f
    moveq   #{PER_TRACK_MASTER},%d1
1:  move.b  %d1,{MASTER_SCALE:#x}
    lea     {TICKS_PER_STEP:#x},%a0
    move.l  (0,%a0,%d1.l*4),%d0
    subq.l  #1,%d0
    move.b  %d0,{TICK:#x}
    clr.w   {HOLD_MASK:#x}
    moveq   #-1,%d0
    move.w  %d0,{FIRST_MASK:#x}
    moveq   #0,%d2
    move.l  %a3,%a5
2:  moveq   #1,%d0
    cmp.l   %d0,%d7
    bne.s   3f
    mvz.b   {TRACK_SCALE}(%a5),%d1
    mvs.w   {TRACK_LENGTH}(%a5),%d5
    bra.s   4f
3:  mvz.b   {MASTER_SCALE:#x},%d1
    move.l  #{LENGTH},%d0
    mvs.w   (0,%a3,%d0.l),%d5
4:  lea     {TRACK_SCALES:#x},%a0
    move.b  %d1,(0,%a0,%d2.l)
    lea     {TICKS_PER_STEP:#x},%a0
    move.l  (0,%a0,%d1.l*4),%d4
    subq.l  #1,%d4
    lea     {FIRST_FIRE:#x},%a0
    move.b  %d4,(0,%a0,%d2.l)
    move.l  %d3,%d0
    rems.l  %d5,%d1:%d0                 | lengths are 2..128 (stock's loads, 0x400dda4a, 0x400de06e)
    lea     {NEXT_STEPS:#x},%a0
    move.b  %d1,(0,%a0,%d2.l)
    move.l  %d1,%d4
    mvz.b   {LOOP_COUNT}(%a5),%d0
    beq.s   6f
    move.l  %d3,%d6
    rems.l  %d0,%d4:%d6
6:  lea     {CONDITION_CYCLE:#x},%a0
    move.b  %d4,(0,%a0,%d2.l)
    subq.l  #1,%d1
    lea     {CURRENT_STEPS:#x},%a0
    move.b  %d1,(0,%a0,%d2.l)
    lea     {TRACK_TICKS:#x},%a0
    clr.b   (0,%a0,%d2.l)
    lea     {COUNTDOWNS:#x},%a0
    moveq   #-1,%d0
    move.b  %d0,(0,%a0,%d2.l)
    lea     {TRACK_STRIDE}(%a5),%a5
    addq.l  #1,%d2
    moveq   #16,%d0
    cmp.l   %d0,%d2
    blt.w   2b
    rts

early_active:
    .byte   0
    .align  2

| (cutoff): free the queued events after CUTOFF that the jump replaces, with interrupts masked,
| each unlinked from its bucket before it is freed, and each bucket left empty. Replaced, from
| the sequencer (origin 1): a note-on or lock (kind 1) for a voice (type 0, or 1 from a track's
| cache) or in a MIDI payload (type 3), and the arp request queued with each step (type 9).
| Live input (origin 2), records stock has marked (-1) and releases (any other kind) stay.
reclaim:
    lea     -48(%sp),%sp
    movem.l %d2-%d7/%a2-%a6,(%sp)
    move.l  52(%sp),%d3
    move.w  %sr,%d7
    move.w  #0x2700,%sr
    lea     {QUEUE:#x},%a2
reclaim_bucket:
    move.l  (%a2),%a3
    tst.l   %a3
    beq.w   reclaim_done
    tst.l   (%a3)
    bne.w   reclaim_keep_bucket
    move.l  %d3,%d0
    sub.l   4(%a3),%d0
    bpl.w   reclaim_keep_bucket
    lea     8(%a3),%a4
    sub.l   %a5,%a5
reclaim_record:
    move.l  (%a4),%a6
    tst.l   %a6
    beq.w   reclaim_bucket_end
    move.l  (%a6),%d2                   | the type
    moveq   #1,%d1
    cmp.l   20(%a6),%d1                 | the sequencer's (origin 1)
    bne.s   reclaim_keep_record
    moveq   #9,%d0
    cmp.l   %d0,%d2
    beq.s   reclaim_remove_record       | type 9: the arp request queued with each step
    cmp.l   %d1,%d2
    bhi.s   3f
    cmp.l   4(%a6),%d1                  | types 0 and 1: a voice's note-on or lock
    beq.s   reclaim_remove_record
    bra.s   reclaim_keep_record
3:  moveq   #3,%d0
    cmp.l   %d0,%d2
    bne.s   reclaim_keep_record
    move.l  24(%a6),%a0                 | type 3: its payload the sequencer's note-on or lock
    cmp.l   52(%a0),%d1
    bne.s   reclaim_keep_record
    cmp.l   12(%a0),%d1
    bne.s   reclaim_keep_record
reclaim_remove_record:
    move.l  104(%a6),%d4
    move.l  %d4,(%a4)
    moveq   #3,%d0
    cmp.l   %d0,%d2
    bne.s   reclaim_free_engine
    move.l  24(%a6),-(%sp)
    jsr     {FREE_MIDI:#x}
    addq.l  #4,%sp
reclaim_free_engine:
    move.l  %a6,-(%sp)
    jsr     {FREE_RECORD:#x}
    addq.l  #4,%sp
    bra.w   reclaim_record
reclaim_keep_record:
    move.l  %a6,%a5
    lea     104(%a6),%a4
    bra.w   reclaim_record
reclaim_bucket_end:
    move.l  %a5,12(%a3)
    tst.l   8(%a3)
    bne.s   reclaim_keep_bucket
    move.l  16(%a3),%d6
    move.l  %d6,(%a2)
    move.l  %a3,-(%sp)
    jsr     {FREE_BUCKET:#x}
    addq.l  #4,%sp
    bra.w   reclaim_bucket
reclaim_keep_bucket:
    lea     16(%a3),%a2
    bra.w   reclaim_bucket
reclaim_done:
    move.w  %d7,%sr
    movem.l (%sp),%d2-%d7/%a2-%a6
    lea     48(%sp),%sp
    rts
"""
SOURCE += NEXT_STEP

# (va, stock bytes, label): each site becomes `jmp label`, nop-padded.
HOOKS = (
    (CUE_SITE, CUE_DISPLACED, "cue_hook"),
    (TICK_SITE, TICK_DISPLACED, "tick_hook"),
    (TEST_SITE, TEST_DISPLACED, "arm_hook"),
    (START_SITE, START_DISPLACED, "switch_hook"),
    (PREPARE, PREPARE_DISPLACED, "early_hook"),
    (KIT_SITE, KIT_DISPLACED, "kit_hook"),
    (BRIDGE_SITE, BRIDGE_DISPLACED, "phase_hook"),
)
# (va, stock pointer, label): a vtable entry that becomes the label's address.
POINTERS = (
    (PTN_KEYS_SLOT, PTN_KEYS, "ptn_keys"),
    (PTN_LEDS_SLOT, PTN_LEDS, "ptn_leds"),
)

# Read, not written: the code the hooks rely on.
CONTEXT = (
    (0x402008C4, bytes.fromhex("401b684e401b6906"), "the PTN view's vtable: its two destructors"),
    (0x4020096C, bytes.fromhex("ffffff9840200880401b68c2401b6922"), "its LedHandler vtable: this + 104, two destructors"),
    (0x400FA6B4, bytes.fromhex("7098d1af00046000fd4c"), "PTN LEDs: the thunk, this - 104, to 0x400fa408"),
    (0x400FA414, bytes.fromhex("4bf94018aabc"), "PTN LEDs: the LED object from 0x4018aabc"),
    (0x400FA420, bytes.fromhex("47f94002c318"), "PTN LEDs: the setter"),
    (0x400FA5D4, bytes.fromhex("203c000000834a2a00896704103c0071"), "PTN LEDs: [PTN] 0x83, or 0x71 with + 137 set"),
    (0x400FA5EC, bytes.fromhex("48780002487800042f044e93"), "PTN LEDs: ...lit, LED 4"),
    (0x4018AABC, bytes.fromhex("4e56fff02f0a"), "the LED object's getter"),
    (0x4002C318, bytes.fromhex("4feffff048d7041c242f0018246f0014282f001c262f0020"), "the LED setter: (leds, index, mode, colour)"),
    (0x4002C33E, bytes.fromhex("41f22c004aa800286630"), "the LED setter: an LED set in this frame keeps its value"),
    (0x400FA6D0, bytes.fromhex("4eb940116018"), "PTN keys: the code"),
    (0x400FA6DC, bytes.fromhex("0680fffffff6"), "PTN keys: the jump table by code - 10"),
    (0x400FA6F4, bytes.fromhex("04be"), "...UP (11) -> 0x400fabb0"),
    (0x400FA6FA, bytes.fromhex("04be"), "...DOWN (14) -> 0x400fabb0"),
    (0x400FABB0, bytes.fromhex("7601"), "PTN keys: handled, nothing done"),
    (0x400FAE02, bytes.fromhex("1003"), "PTN keys: returns %d3"),
    (0x400FA246, bytes.fromhex("486effe748794021ec0d"), "PTN view: a message's allocator and text"),
    (0x400FA25A, bytes.fromhex("2f2a00784eb94005628c"), "PTN view: the message line, this + 120"),
    (0x400FA264, bytes.fromhex("2f024eb9401ccbee"), "PTN view: the message's string destroyed"),
    (0x400FA1DA, bytes.fromhex("4eb9400d93f0"), "PTN view: the cue's post"),
    (0x400FA1E6, bytes.fromhex("4eb94011c7ba"), "PTN view: after the post, a redraw of (%sp)"),
    (0x400DA26A, bytes.fromhex("b0b942c5a918"), "tick routine: playing is 1"),
    (0x400DA2C2, bytes.fromhex("123942c5a91e"), "tick routine: the tick, advanced"),
    (0x400DA40C, bytes.fromhex("7c027b01bc8566000116"), "tick routine: tick 2 -> queue path"),
    (0x400DA416, bytes.fromhex("227942c5aac042b942c5aaac"), "queue path: the head; armed cleared"),
    (0x400DA460, bytes.fromhex("7e01207942c5a9a0"), "last-step test, after CHANGE"),
    (0x400DA4D2, bytes.fromhex("23c042c5a9a4"), "arm: the next pattern from %d0"),
    (0x400DA4F0, bytes.fromhex("42b942c5a9c4"), "arm: start step 0"),
    (0x400DA520, bytes.fromhex("23c242c5aaac"), "arm: armed"),
    (0x400DA52A, bytes.fromhex("4a01660003d4"), "tick routine: past tick 0 -> the end"),
    (0x400DA544, bytes.fromhex("528033c042c5a91c"), "boundary: the counter advanced"),
    (0x400DA584, bytes.fromhex("4ab942c5aaac"), "boundary: armed?"),
    (0x400DA6AA, bytes.fromhex("23d142c5a9a0"), "switch: the pattern installed"),
    (0x400DA6EC, bytes.fromhex("4df942c5a9c8"), "switch: after the start step's lea"),
    (0x400DA6F8, bytes.fromhex("23d142c5a9bc"), "switch: the start step copied"),
    (0x400DA804, bytes.fromhex("33c042c5a91c"), "switch: the counter set to the start step"),
    (0x400DA55E, bytes.fromhex("203c0001dd54"), "the pattern's length at + 122196"),
    (0x400DA902, bytes.fromhex("42024bf942c5a9ea"), "the end of a tick past the boundary"),
    (0x401CE69E, bytes.fromhex("4e5600002f02"), "std::string's constructor"),
    (0x401CCBEE, bytes.fromhex("4e56fffc206e"), "std::string's destructor"),
    (0x4005628C, bytes.fromhex("598f2f0a2f02"), "the message line"),
    # the next step
    (0x400D9922, bytes.fromhex("76012f034eb940136980"), "tick routine: LST from the queue's head, every interrupt"),
    (0x40136980, bytes.fromhex("4aaf000456c0448013c04463ec784e75"), "LST: on when its argument is nonzero"),
    (0x400D9E16, bytes.fromhex("2e3c42c5a964"), "preparation: after the pattern pointer"),
    (0x400D9E24, bytes.fromhex("47f942c5aa2c45f942c5aa3c49f942c5a974"), "preparation: countdowns, first-fire corrections and phases by track"),
    (0x400D9E88, bytes.fromhex("28361c004a00660671129880"), "preparation: ticks ahead, the period less the first-fire correction"),
    (0x400D9FFA, bytes.fromhex("223c000dbba05384202f006020454c014800d0b942c4e900d88021440008"), "preparation: base time T + (ahead - 1) ticks, at record + 8"),
    (0x400D89FE, bytes.fromhex("27400014"), "sound producer: the origin at + 20"),
    (0x400D8AA8, bytes.fromhex("27400004"), "sound producer: the kind at + 4"),
    (0x400D8EEA, bytes.fromhex("2d470034"), "MIDI producer: the payload's origin at + 52"),
    (0x400D8F02, bytes.fromhex("2d47000c"), "MIDI producer: the payload's kind at + 12"),
    (0x4012B486, bytes.fromhex("70037a01208021450014214a0018216a00380008"), "MIDI continuation: type 3, origin + 20, payload + 24, base + 8"),
    (0x400D7694, bytes.fromhex("206f0004201067067203b280660670ff214000144e75"), "stock's discard: types 0 and 3, + 20 = -1"),
    (0x40138B0A, bytes.fromhex("2479446442284a8a673c4a926704246a00104a8a6710202f001090aa00046aee6004246a00104a8a671c266a00084a8b67f02f2f00182f0b206f001c4e90266b0068"), "the visitor: the queue past its immediate bucket, times + 4, records + 8, links + 104"),
    (0x4012A3D2, bytes.fromhex("2f0a7001246f0008b0926726"), "MIDI payload release (payload): a cache's payload kept"),
    (0x40138A0C, bytes.fromhex("2f0a246f00084a92660e202a0054"), "engine record release (record): a type 0's lock at + 84"),
    (0x40138A84, bytes.fromhex("206f000440c046fc270043f944644230"), "bucket release (bucket), masked"),
    (0x400DA58A, bytes.fromhex("6700035e227942c5aac042b942c5aaac"), "boundary: armed -> the switch, which takes the queue's entry"),
    (0x400DA7AC, bytes.fromhex("4c074800d8b942c4e900"), "switch: the kit event at T + %d4 ticks"),
    (0x400DA7C8, bytes.fromhex("74011e350800203942c5a9bc"), "switch: the bridge, from the start step"),
    (0x400DA156, bytes.fromhex("12351800660c207c0001dd547d75880060047d6a048c7f87bc876e024213"), "advance: the next step wraps at the pattern's length, or + 1164 per track"),
    (0x400DA174, bytes.fromhex("1c2a05a467047d86"), "advance: with Page Loop the condition cycle wraps at + 1444"),
    (0x401F6B08, bytes.fromhex("000000030000000400000006000000080000000c0000001800000030"), "ticks per step by scale: 3, 4, 6, 8, 12, 24, 48"),
) + toggle.CONTEXT[:1]          # the setting writer

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCKS = {"1.11": "00_Firmware/Digitone_II_OS1.11_dist.zip",       # under 00_Resources (issue #382)
          "1.12": "00_Firmware/Digitone_II_OS1.12.syx"}
STOCK = resources_dir() / STOCKS["1.11"]
OUT = resources_dir() / "02_Builds/directjump_DN2_1.11.syx"


def overrides(os: str) -> dict:
    """What the map cannot place: FLAG, which no instruction names, moves with the settings block"""
    return {"FLAG": osport.addr(os, SETTINGS) + (FLAG - SETTINGS)}


def source(os: str = "1.11") -> str:
    """The routines for OS (issue #382): their stock addresses through `dnfw.osport`"""
    return osport.render(SOURCE, globals(), os, None if os == "1.11" else overrides(os))


def assemble_stubs(source: str, base: int) -> tuple[bytes, dict[str, int]]:
    """Assemble once and read each label's address off a trailing table."""
    table = "\n".join(f"    .long {name}" for name in LABELS)
    blob = assemble(source + "\n    .align 2\n" + table + "\n", base=base)
    width = 4 * len(LABELS)
    addrs = struct.unpack(">%dI" % len(LABELS), blob[-width:])
    return blob[:-width], dict(zip(LABELS, addrs))


def compose(stock: bytes, log=print, os: str = "1.11") -> dict:
    """Apply the build to a stock MAIN OS. -> {content, blob, labels, flag}: the hooked image and
    the code, 4-padded, for a platform `CODE` chunk at CODE_VA.

    OS is STOCK's version (issue #382): every guard, hook and vtable entry goes through
    `dnfw.osport.site`, and the switch's byte moves with the settings block."""
    def site(va, want, why):
        try:
            return osport.site(os, va, want, stock, BASE)
        except osport.NotPorted as exc:
            raise SystemExit(f"{why}: {exc}") from None
    if not available():
        raise SystemExit("no m68k assembler found")
    content = bytearray(stock)
    flag = FLAG if os == "1.11" else overrides(os)["FLAG"]
    if any(content[flag - BASE:flag - BASE + 1]):
        raise SystemExit("the switch's byte is not zero in the image")

    log("part 1 -- the code this relies on, asserted")
    for va, want, why in CONTEXT:
        va, want = site(va, want, why)
        log(f"  {va:#010x}  {want.hex():<24}  {why}")

    log(f"part 2 -- the code, from {CODE_VA:#010x}")
    payload, at = assemble_stubs(source(os), CODE_VA)
    blob = payload + bytes(-len(payload) % 4)
    log(f"  {len(payload)} bytes: " + ", ".join(f"{k} {v:#010x}" for k, v in at.items()))

    log("part 3 -- the hooks")
    for va, stock_bytes, label in HOOKS:
        va, stock_bytes = site(va, stock_bytes, label)
        new = bytes.fromhex("4ef9") + struct.pack(">I", at[label])
        new += bytes.fromhex("4e71") * ((len(stock_bytes) - len(new)) // 2)
        if len(new) != len(stock_bytes):
            raise SystemExit(f"hook at {va:#010x} does not fit {len(stock_bytes)} bytes")
        content[va - BASE:va - BASE + len(new)] = new
        log(f"  {va:#010x}  {stock_bytes.hex()} -> {new.hex()}  jmp {label}")
    for va, stock_pointer, label in POINTERS:
        va, stock_entry = site(va, struct.pack(">I", stock_pointer), label)
        content[va - BASE:va - BASE + 4] = struct.pack(">I", at[label])
        log(f"  {va:#010x}  {stock_entry.hex()} -> {at[label]:#010x}  {label}")

    return {"content": bytes(content), "blob": blob, "labels": at, "flag": flag}


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
