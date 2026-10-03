# Track layering onto MIDI tracks -- how the firmware does it, and `layermidi`

Digitone II OS 1.11. Read 2026-10-01..02; the mod passed on the instrument on
2026-10-02 (`docs/flashing.md`). Every address is 1.11's.

## The question

TRACK WILL TRIGGER can select a MIDI track as a destination, and on stock
firmware the MIDI track then plays nothing (bench, 2026-10-01). Where does
layering happen, and why does a MIDI destination stay silent?

## The tables

One 16-bit destination mask per source track, in the kit (the RAM kit, `0x5d71`
bytes, `0x4210c08c + 0x5d71 * index`, current one at `0x42c5a9ac`):

| table | kit offset | getter | setter |
|---|---|---|---|
| TRACK WILL TRIGGER | `+0x5ce0 + 2*src` | `0x400315dc` (word >> dest & 1) | `0x40031620` |
| TRACK CHOKES | `+0x5d00 + 2*src` | `0x40031758` | `0x400316b8` |

Both sit just after the synth/MIDI mask (`+0x5cda`). The screen
(`0x4010fb0a`; strings `"%s WILL TRIGGER..."` `0x4021f87d`, `"%s CHOKES..."`
`0x4021f890`) asks `0x4010f764(owner, src, dest)` per cell. A stored kit keeps
the two at `+10347` / `+10379` (converters `0x400ddd..` / `0x400ddf..`).

**Not `+0x2ca0`.** An earlier note (SYXGRID, from the stored format) put the
table at kit `+0x2ca0`; in RAM nothing reads that offset when a layered track
plays (`scripts/emu_layer_probe.py`, 2026-10-01), and kit `+0x14` -- tried next
-- is a per-track level (`0x6400`), with the kit name at `+0x36`.

## Where it is applied: the frame ISR

Not where a note is made. The sequencer and the live key-down build a record for
the source track only; layering is applied when the frame ISR (`0x40025e36`)
reaches that record:

- **Fan-out, `0x400265d2`.** For a record that is not itself a copy, the ISR
  reads `kit[+0x5ce0 + 2*track]` through its kit pointer `0x800052a0`, keeps the
  mask per (track, note) at `0x4058f3a0` for the release, and for each set bit
  (`ff1`) calls **`0x400255b4(record, dest)`**.
- **The copy, `0x400255b4`.** Takes an engine record (`0x401389d6`), copies the
  source's `0x6c` bytes, clears `+60`, `+64`, `+84`, sets track `+16` = dest,
  flag `+56` bit 17 (`0x20000`), source track `+92`, and links it after the
  source (`+104`) with interrupts masked. The ISR reaches it next; bit 17 keeps
  it from fanning out again (`0x4002658c`).
- **Voicing.** The copy then goes the way of any synth note. On a MIDI track
  there is no voice, so nothing sounds and nothing is sent. That is the whole
  reason a MIDI destination is silent: the copy is never a MIDI record.

## Where a note is voiced -- and where it is not

**The voice trigger `0x400db524` is not per note.** It is the track's held-note
manager (it keeps a held copy in a per-track slot `0x42c645e8 + 28*track`, and
for a record already voiced -- `+56` bit 20 -- it returns at once, `0x400db580`).
The ISR calls it **once per record**, at `0x400268f8`.

The notes are voiced in the loop after it, one pass per entry of the record's
current group:

| | |
|---|---|
| `0x4002695a` | `%a2` the entry; null ends the record |
| `0x40026960` | the entry's group (`+5`) against the one being played (`-96(%fp)`); a later group requeues the record |
| **`0x40026980`** | **the note**: entry `+2` plus the transposes (`0x80005380`), voice allocation `0x4002a6a2`, velocity `+3` (negative: the sound's `+0x480`, via record `+44`), length `+4` (negative: `+0x481`) |
| `0x40026ca0..0x40026cd2` | the next entry: index from the record's list (`+28`, next index at `+28 + 0xd000 + 2*i`), `%a2 = +28 + 6*i`, back to `0x4002695a` |

An entry is 6 bytes: `+0` flag (negative: skip), `+2` note, `+3` velocity, `+4`
length, `+5` group. A record's current entry is its list's (`+28`, index `+32`)
when `+32 >= 0`, else the inline one at `+36` (`0x40026566`). **A sequencer trig
uses the list; the inline entry is left unfilled.** A chord is one record whose
notes are one group of the list.

## The release

A key-up reaches the ISR as a record that is not kind 1 (`+4`; `0x40026596`
branches to `0x40026cd6`):

- for the source, `0x40026cee..0x40026d30` reads and clears the mask kept at
  `0x4058f3a0` for (track, note) and makes a **release copy** per layer, with
  the same `0x400255b4`;
- each record then runs the per-note release loop: `0x40026dd6` (group test)
  -> **`0x40026d32`** (entry `%a2`; voice release via `0x4002a6a2`) -> next
  entry (`0x40026da0..0x40026dd4`).

## The MIDI side

- **Records.** The MIDI task (`0x4012a9a8`) takes batches the ISR builds during
  a frame (head `-180(%fp)`, tail `%a5`, `+92` the link) and posts at
  `0x40026f2c..0x40026f60` (queue `0x445fe870`). A record: track `+8`, kind
  `+12` (1 note-on), `+16` `0x80` play, `+24` -1 = the inline entry `+36`
  (note `+38`, velocity `+39`, length `+40`), sound `+44`, time `+48`, source
  `+52` (1 = sequencer, which takes a mute test at `0x4012ac4c`; 2 = live).
  midiarp found this format; the live MIDI sender `0x4012b8b0` builds the same.
- **Note-on** (`0x4012ace4` kind 1): sent at once, with its note-off scheduled at
  time `+48` plus the length from the trig length table (`0x4012b266`), into a
  per-(channel, note) slot (`0x446004a8`).
- **Release** (kind not 1, `0x4012b344..0x4012b3f4`): for each of the 16
  channels where the note is active for the track (`0x466765f8`), cancels the
  scheduled note-off (`0x4012a10c`) and sends note-off.
- **The pool.** 64 records; free list at `0x4460e4b8`, next at `+92`. The
  allocator `0x4012a408` **pops without checking**: on an empty pool it reads
  address 92 as the new head, clears 0, 4 and 92, and returns 0, and every later
  allocation is garbage. A bench build that sent one record per *repeat* of a
  voiced record emptied it, and the instrument froze minutes later.

## The mod

`layermidi` (`src/dnfw/mods/layermidi.py`, built by `scripts/build_layer_midi.py`):

1. **`0x40026980`** (`jsr`; the displaced `mvz.w 0x8000537e,%d1` runs last in
   the code): for a layered copy (`-36(%fp)` `+56` bit 17) on a MIDI track
   (`0x8000537c`, the kit's `+0x5cda` mirrored per frame), a note-on on the
   batch, from the entry `%a2`, with the time the ISR gives the voice trigger
   (`0x400268de`). INF (127) is sent as 126, so a note whose release never comes
   still ends; a release cancels that.
2. **`0x40026d32`** (`jmp`; its two instructions push onto the ISR's stack, so
   the code runs them and jumps back to `0x40026d38`): for the same, a kind-0
   record.
3. A record is taken only while two are free.

Every other register is preserved, and every other record and track is stock.

The code runs from the mod platform: a 324-byte `CODE` chunk that the platform
loader copies to `0x467d8000` at start-up (`layer-midi7`, 2026-10-03). Up to
`layer-midi6` it sat in the cave at `0x402d0664`, which was midiarp's and
usbprobe's too; that cave now stays stock, and the two hooks are the only edits
in the image. The code is the same: every reference out of it is absolute.

It is not combined with midiarp. The bytes no longer collide, but both turn
layered copies on MIDI tracks into MIDI, so the pair is refused by hand
(`matrix.REFUSED`) until the maintainer re-checks it.

## Bench history

`docs/flashing.md`, 2026-10-01..02: stock (silent) -> midiarp (random notes) ->
`layer-midi1` (lowest chord note) -> `layer-midi2` (flood, freeze) ->
`layer-midi4` (lowest chord note) -> `layer-midi5` (chords right, live hangs) ->
`layer-midi6` (pass). `layer-midi7` = `layermidi` is the same code on the mod
platform, checked in the emulator; not yet on the instrument.

The two wrong turns (1 and 4) came from one assumption: that the voice trigger
is called per note. The emulator harness at the time called the hook per chord
note, so it agreed with the assumption. `scripts/emu_layer_midi.py` now runs the
ISR's own loops instead, and reproduces `layer-midi4`'s one-note chord before
showing `layermidi`'s three.

## Running the evidence

    python scripts/build_layer_midi.py            # the image, with every guard asserted
    dnfw extract 00_Resources/02_Builds/layer-midi7_DN2_1.11.syx -o out/layer-midi7
    python scripts/gen_layermidi_code.py          # the shipped JSON and JS
    pytest test/test_layermidi_mod.py
    <digikit>/.venv/bin/python -u scripts/emu_make_snapshots.py   # once: boot400M, ui1200M
    <digikit>/.venv/bin/python -u scripts/emu_layer_midi.py [--post] [--control]
    <digikit>/.venv/bin/python -u scripts/emu_layer_midi.py out/layer-midi4 --trigger-only

The emulator scripts need digikit with the DN2 fixes from this project's open
PRs there (#19, #24) -- see `scripts/emu_make_snapshots.py`.

## Open

- **Arp on the source track:** not tried.
- **OS 1.12:** not built. The routines move; re-derive from `docs/version-anchors.md`.
