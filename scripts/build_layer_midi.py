"""Track layering onto a MIDI track: the layered notes go out over MIDI.

    python scripts/build_layer_midi.py

TRACK WILL TRIGGER lets an audio track trigger a MIDI track, and on stock 1.11
the MIDI track stays silent (bench, 2026-10-01). This build sends those notes
out on the MIDI track's channel, and changes nothing else.

## Where layering happens, read 2026-10-01

The table is the kit's, one 16-bit destination mask per source track:
TRACK WILL TRIGGER at kit `+0x5ce0 + 2*src` (getter `0x400315dc`, setter
`0x40031620`), TRACK CHOKES at `+0x5d00 + 2*src` (`0x40031758`, `0x400316b8`).
The screen (`0x4010fb0a`, strings `0x4021f87d` / `0x4021f890`) reads both
through `0x4010f764`. Stored kits keep them at `+10347` / `+10379`
(converters `0x400ddd..`, `0x400ddf..`).

It is applied in the frame ISR, not where the note is made. At `0x400265d2`
the ISR reads `kit[+0x5ce0 + 2*track]` through its kit pointer `0x800052a0`,
keeps the mask per (track, note) at `0x4058f3a0` for the note-off, and for
every set bit calls `0x400255b4(record, dest)`. That copies the 0x6c-byte
engine record from the engine pool (`0x401389d6`), sets track `+16` = dest,
source `+92` = the source track, flag `+56` bit 17 (`0x20000`), and links the
copy after the source (`+104`) with interrupts masked. The ISR reaches the copy
next; bit 17 stops it fanning out again (`0x4002658c`) and it is voiced like
any synth note -- on a MIDI track, which has no voice, so nothing is sent.

## Where a note is voiced, read 2026-10-02

Not at the voice trigger `0x400db524`. That is the track's held-note manager,
called **once per record** at `0x400268f8`, before the notes are voiced. The
notes are voiced in the loop after it, one pass per entry of the record's
current group (entry `+5`): `0x4002695a` tests the entry, `0x40026960`
compares its group with the one being played, `0x40026980` starts the note
(transpose `0x80005380`, voice allocation `0x4002a6a2`, ...), and
`0x40026ca0..0x40026cd2` steps to the next entry through the list
(`+28`, index `+32`) and branches back. A chord is one group: its notes pass
`0x40026980` one by one, the voice trigger saw only the first.

So the bench's builds, which hooked the voice trigger:
- layer-midi1 (gated on +56 bit 20, voiced): one note per record -- chords sent
  their lowest note only;
- layer-midi2 (no gate): voiced records coming back to the trigger each sent a
  note, flooding the MIDI pool; hanging notes, then the instrument froze;
- layer-midi3/4 (a per-track last-entry filter): still one note per chord, as
  the trigger never sees the others.

## What this build does

One hook, at the head of the per-note body, `0x40026980`. Its 6-byte
instruction (`mvz.w 0x8000537e,%d1`, absolute, position-independent) moves into
the cave and runs last, so the loop continues exactly as stock. Every note the
ISR voices passes here once. A note of a layered copy (record `-36(%fp)`,
`+56` bit 17) on a MIDI track (`0x8000537c`, the kit's `+0x5cda` mirrored per
frame) also becomes a MIDI record on the batch the ISR hands the MIDI task
(head `-180(%fp)`, tail `%a5`, posted at `0x40026f60`) -- `midiarp`'s
mechanism, from `build_arp_midi_play.py`. The MIDI task sends it on the
track's channel and schedules its note-off from the length.

The note is the ISR's entry, `%a2`: `+2` note, `+3` velocity, `+4` length,
negative velocity and length from the sound at record `+44` (`0x40026a48`,
`0x40026a8c`). The time is the one the ISR gives the voice trigger
(`0x400268de`: `-44(%fp)`, its first long nonzero -> now `0x80005398`, else
its `+4`). Every register but `%a5` (the batch tail, by design) and `%d1` (set
by the displaced instruction) is preserved.

**The MIDI pool.** `0x4012a408` pops the free list (`0x4460e4b8`, next `+92`)
without an empty check: an empty pop reads address 92 as the new head and
clears 0, 4 and 92, and every later allocation is garbage. The hook takes a
record only while at least two are free, leaving one for the MIDI task.
midiarp has the same exposure.

## The release, read 2026-10-02 (layer-midi6)

A key-up reaches the ISR as a record that is not kind 1 (`+4`, `0x40026596`).
For the source, `0x40026cee..0x40026d30` reads and clears the layering mask it
kept for (track, note) at `0x4058f3a0` and makes a release copy per layer
(`0x400255b4` again); each copy runs the per-note release loop
(`0x40026dd6` -> `0x40026d32`, entry `%a2`). A second hook there sends a MIDI
record of kind 0 (`+12`). The MIDI task's release (`0x4012b344..0x4012b3f4`)
finds the note on whichever channel it is active for the track
(`0x466765f8`), cancels its scheduled note-off (`0x4012a10c`) and sends
note-off -- so the note-on's 126-length fallback is cancelled too. The live
MIDI sender `0x4012b8b0` builds its records the same way.

The site's two instructions (`mvs.b 2(%a2),%d4; move.l %d4,-(%sp)`) push onto
the ISR's stack, so it is a `jmp` and the cave runs them and jumps back to
`0x40026d38`.

layer-midi5 on the bench: sequences and chords right; live keys hang (no
note-off). MIDI ~8 ms ahead of the recorded audio -- the audio path's latency.

## Limits, known before the bench

- **Arp on the source:** untested.
- Velocity and length defaults come from the source track's sound (the copy
  keeps its `+44`). The MIDI track's channel is the one used.
- Not with `midiarp`: this uses its cave.

| on the bench: T1 audio WILL TRIGGER T9 MIDI | means |
|---|---|
| every chord note, once, with its length | done |
| still the lowest note only | the loop does not run for the copy |
| duplicates, or notes stop after a while | a note passes 0x40026980 more than once |
| T1, and every unlayered track, not exactly stock | the hook leaks |
"""

from __future__ import annotations

import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dnfw.cli.files import read_image
from dnfw.container.section import compress
from dnfw.firmware import build as fwbuild
from dnfw.firmware.load import load
from dnfw.patch.assemble import assemble, available

MAIN_OS = 3
BASE = 0x40000400

# One of the three clean 896-byte runs (docs/code-caves.md), and midiarp's.
# The hook is past the largest smaller clean run (203 B at 0x40295698).
CAVE = 0x402D0664
CAVE_CAP = 896

KIT = 0x800052A0            # the ISR's kit pointer (0x40026534)
MIDI_MASK = 0x8000537C      # kit +0x5cda, mirrored per frame (0x40025b9a)
NOW = 0x80005398            # the ISR's clock
SOUND_BASE = 52             # kit + 52 + 1163*track: the track's sound
SOUND_STRIDE = 1163
SOUND_VELOCITY = 0x480      # default velocity when the entry's is negative
SOUND_LENGTH = 0x481        # ...and length
MIDI_RECORD = 0x4012A408    # MIDI record pool, interrupts masked while taken
MIDI_FREE = 0x4460E4B8      # its free-list head; next at +92
LAYERED = 17                # record +56: a copy made by 0x400255b4

NOTE_SITE = 0x40026980
DISPLACED = bytes.fromhex("73f98000537e")      # mvz.w 0x8000537e,%d1
RELEASE_SITE = 0x40026D32
RELEASE_DISPLACED = bytes.fromhex("792a00022f04")  # mvs.b 2(%a2),%d4 ; move.l %d4,-(%sp)

LABELS = ("note_hook", "release_hook")

SOURCE = f"""
| The head of the ISR's per-note body. Record -36(%fp), entry %a2.
| A layered copy's note on a MIDI track becomes a note-on on the batch.
note_hook:
    lea     -32(%sp),%sp
    movem.l %d0-%d3/%a0-%a1/%a3-%a4,(%sp)
    bsr.s   gate
    bne.s   1f
    moveq   #1,%d3                      | note on
    bsr.w   emit
1:  movem.l (%sp),%d0-%d3/%a0-%a1/%a3-%a4
    lea     32(%sp),%sp
    mvz.w   0x8000537e,%d1              | the displaced instruction, last
    rts

| The head of the ISR's per-note release body, reached by jmp: the two
| displaced instructions push onto the ISR's own stack, so they run here and
| the jmp goes back after them. A layered copy's release on a MIDI track
| becomes a note-off: the MIDI task finds the note on whichever channel it is
| active for the track, cancels its scheduled note-off and sends it
| (0x4012b344..0x4012b3f4).
release_hook:
    lea     -32(%sp),%sp
    movem.l %d0-%d3/%a0-%a1/%a3-%a4,(%sp)
    bsr.s   gate
    bne.s   1f
    moveq   #0,%d3                      | note off
    bsr.w   emit
1:  movem.l (%sp),%d0-%d3/%a0-%a1/%a3-%a4
    lea     32(%sp),%sp
    mvs.b   2(%a2),%d4                  | the displaced instructions
    move.l  %d4,-(%sp)
    jmp     {RELEASE_SITE + 6:#x}

| -> Z set when the record -36(%fp) is a layered copy on a MIDI track and the
| MIDI pool can spare a record; then %a4 the record, %d2 its track.
gate:
    move.l  -36(%fp),%a4
    move.l  56(%a4),%d1
    btst    #{LAYERED},%d1
    beq.s   8f                          | not a layered copy: stock
    move.l  16(%a4),%d2
    moveq   #15,%d1
    cmp.l   %d2,%d1
    bcs.s   8f
    mvs.w   {MIDI_MASK:#x},%d1
    btst    %d2,%d1
    beq.s   8f                          | an audio track: stock
    move.l  {MIDI_FREE:#x},%d0          | the allocator does not check the
    beq.s   8f                          | free list, and an empty pop corrupts
    move.l  %d0,%a1                     | low memory for good. Keep one spare
    tst.l   92(%a1)                     | for the MIDI task's own use.
    beq.s   8f
    moveq   #0,%d0                      | Z set: go
    rts
8:  moveq   #1,%d0                      | Z clear: stock
    rts

| One MIDI record for entry %a2 of record %a4 on track %d2, kind %d3
| (1 on, 0 off), appended to the ISR's batch.
emit:
    jsr     {MIDI_RECORD:#x}
    move.l  %d0,%a3
    move.l  %d2,8(%a3)                  | track
    move.l  %d3,12(%a3)                 | kind
    moveq   #0,%d0
    tst.l   %d3
    beq.s   1f
    move.l  #0x80,%d0                   | a note-on plays
1:  move.l  %d0,16(%a3)
    clr.l   20(%a3)
    moveq   #-1,%d0
    move.l  %d0,24(%a3)                 | the note is the inline entry at +36
    clr.l   32(%a3)
    move.l  {NOW:#x},%d0
    tst.l   %d3
    beq.s   2f
    move.l  -44(%fp),%a0                | a note-on: the time the ISR gives the
    tst.l   (%a0)                       | voice trigger (0x400268de)
    bne.s   2f
    move.l  4(%a0),%d0
2:  move.l  %d0,48(%a3)                 | the base of its note-off
    moveq   #2,%d0
    move.l  %d0,52(%a3)                 | live-played: the engine already gated mutes
    clr.b   36(%a3)
    clr.b   37(%a3)
    move.b  2(%a2),38(%a3)              | note
    clr.b   41(%a3)
    move.l  44(%a4),%d0                 | the sound its defaults come from (0x4002672c)
    bne.s   2f
    move.l  #{SOUND_STRIDE},%d0
    muls.l  %d2,%d0
    add.l   {KIT:#x},%d0
    add.l   #{SOUND_BASE},%d0
2:  move.l  %d0,44(%a3)                 | the MIDI task reads defaults through +44 too
    move.l  %d0,%a0
    move.b  3(%a2),%d1                  | velocity; negative = the sound's
    bpl.s   3f
    move.b  {SOUND_VELOCITY}(%a0),%d1
    bpl.s   3f
    moveq   #100,%d1
3:  move.b  %d1,39(%a3)
    moveq   #0,%d3
    move.b  4(%a2),%d3                  | length; negative = the sound's
    tst.b   %d3
    bpl.s   4f
    move.b  {SOUND_LENGTH}(%a0),%d3
4:  moveq   #126,%d1
    cmp.l   %d3,%d1
    bcc.s   5f
    move.l  %d1,%d3                     | INF would never be switched off
5:  move.b  %d3,40(%a3)
    tst.l   -180(%fp)
    bne.s   6f
    move.l  %a3,-180(%fp)
    bra.s   7f
6:  move.l  %a3,92(%a5)
7:  move.l  %a3,%a5
    rts
"""

# (va, stock bytes, kind, label): the stock instructions become a jsr (returns
# past them) or a jmp (the cave jumps back itself) to `label`.
HOOKS = (
    (NOTE_SITE, DISPLACED, "jsr", "note_hook"),
    (RELEASE_SITE, RELEASE_DISPLACED, "jmp", "release_hook"),
)

# Read, not written: the code the hook relies on.
CONTEXT = (
    (0x400265D2, bytes.fromhex("2003"), "ISR: layering, track to d0"),
    (0x400265D4, bytes.fromhex("068000002e70"), "ISR: + 0x2e70 words = kit +0x5ce0"),
    (0x40026618, bytes.fromhex("4ebaef9a"), "ISR: jsr 0x400255b4, the layered copy"),
    (0x400255EC, bytes.fromhex("81aa0038"), "copy: flag +56 |= 0x20000"),
    (0x400255E6, bytes.fromhex("256f001c0010"), "copy: track +16 = dest"),
    (0x40026566, bytes.fromhex("20280020"), "ISR: entry index +32"),
    (0x4002657C, bytes.fromhex("45e80024"), "ISR: else the inline entry +36"),
    (0x400268DE, bytes.fromhex("206effd4"), "ISR: the voice trigger's time, -44(%fp)"),
    (0x400268E2, bytes.fromhex("4a90"), "...its first long nonzero -> now"),
    (0x400268E6, bytes.fromhex("203980005398"), "...now is 0x80005398"),
    (0x400268EE, bytes.fromhex("20280004"), "...else its +4"),
    (0x400268F4, bytes.fromhex("2f2effdc"), "ISR: the record is -36(%fp)"),
    (0x4002695A, bytes.fromhex("4a8a"), "loop: %a2 the entry, tested"),
    (0x40026960, bytes.fromhex("712a0005"), "loop: the entry's group +5"),
    (0x40026968, bytes.fromhex("6716"), "loop: same group -> 0x40026980, the note"),
    (0x40026992, bytes.fromhex("712a0002"), "note: entry +2 is the note"),
    (0x40026A48, bytes.fromhex("122a0004"), "note: entry +4 its length"),
    (0x40026A8C, bytes.fromhex("102a0003"), "note: entry +3 its velocity"),
    (0x40026CCA, bytes.fromhex("2468001c"), "loop: the next entry from the list +28"),
    (0x40026CD2, bytes.fromhex("6000fc86"), "loop: back to 0x4002695a"),
    (0x40026596, bytes.fromhex("6600073e"), "ISR: a record not kind 1 -> the release path"),
    (0x40026CEE, bytes.fromhex("2203"), "release: the source's layering mask..."),
    (0x40026CF8, bytes.fromhex("41f94058f3a0"), "...kept per (track, note) at 0x4058f3a0"),
    (0x40026D2A, bytes.fromhex("4ebae888"), "release: jsr 0x400255b4, a release copy per layer"),
    (0x40026DE0, bytes.fromhex("6700ff50"), "release loop: same group -> 0x40026d32"),
    (0x40026D38, bytes.fromhex("2f280010"), "release: %a0 is the record after the displaced pair"),
    (0x4012ACE4, bytes.fromhex("b0aa000c"), "MIDI task: kind +12 not 1 ->"),
    (0x4012ACE8, bytes.fromhex("6600065a"), "...0x4012b344, the release: note-off where active"),
    (0x4002611C, bytes.fromhex("9bcd"), "ISR: batch tail %a5 cleared"),
    (0x40026128, bytes.fromhex("42aeff4c"), "ISR: batch head -180(%fp) cleared"),
    (0x40026E4C, bytes.fromhex("2d4dff4c"), "ISR: batch head set"),
    (0x40026F5A, bytes.fromhex("4879445fe870"), "ISR: batch posted to the MIDI task's queue"),
    (0x4002672C, bytes.fromhex("2268002c"), "ISR: a note's default-giving sound is record +44"),
    (0x40025B9A, bytes.fromhex("33d28000537c"), "ISR: MIDI mask mirrored"),
    (0x4012A40E, bytes.fromhex("20794460e4b8"), "MIDI pool: head at 0x4460e4b8"),
    (0x4012A414, bytes.fromhex("43e8005c"), "MIDI pool: next at +92"),
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
OUT = ROOT / "00_Resources/02_Builds/layer-midi6_DN2_1.11.syx"


def be32(v: int) -> bytes:
    return struct.pack(">I", v)


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
                         f"-- not the image this patch was written against ({why})")


def compose(stock: bytes, log=print) -> dict:
    """Apply the build to a stock MAIN OS. -> {content, cave}."""
    if not available():
        raise SystemExit("no m68k assembler found")
    content = bytearray(stock)

    log("part 1 -- the code this relies on, asserted")
    for va, want, why in CONTEXT:
        check(content, va, want, why)
        log(f"  {va:#010x}  {want.hex():<14}  {why}")

    log("part 2 -- the cave")
    if any(content[CAVE - BASE:CAVE - BASE + CAVE_CAP]):
        raise SystemExit(f"cave at {CAVE:#010x} is not free")
    payload, at = assemble_stubs(SOURCE, CAVE)
    if len(payload) > CAVE_CAP:
        raise SystemExit(f"cave overflows: {len(payload)} > {CAVE_CAP}")
    content[CAVE - BASE:CAVE - BASE + len(payload)] = payload
    log(f"  {len(payload)} of {CAVE_CAP} bytes at {CAVE:#010x}")

    log("part 3 -- the hooks")
    for va, stock_bytes, kind, label in HOOKS:
        check(content, va, stock_bytes, label)
        new = bytes.fromhex("4eb9" if kind == "jsr" else "4ef9") + be32(at[label])
        if len(new) != len(stock_bytes):
            raise SystemExit(f"hook at {va:#010x} is not {len(stock_bytes)} bytes")
        content[va - BASE:va - BASE + len(new)] = new
        log(f"  {va:#010x}  {stock_bytes.hex()} -> {new.hex()}  {kind} {label}")

    return {"content": bytes(content), "cave": (CAVE, len(payload))}


def main() -> int:
    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    if section is None:
        raise SystemExit("image has no MAIN OS section")
    content = compose(section.unpack())["content"]

    print("part 4 -- repack")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    replacement = compress(section.id, section.dest, content)
    OUT.write_bytes(fwbuild.build(firmware, {MAIN_OS: replacement}))
    print(f"  wrote {OUT} ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
