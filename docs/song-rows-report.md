# Song rows overwritten in a saved project (rivvi, 2026-10-10)

**Open.** Not reproduced. What is known, what was ruled out, and one bug found on the way.

## The report

rivvi, on `destinations_fxmod_lfowaves_arpmodes_lfo4_lfofix` (moddest, fxmod, lfowaves,
arpmodes, lfo4, lfolength on 1.11), project `AM REBECCA`:
1. cleared some patterns; after saving and loading the project "they kept coming back";
2. then song 1 showed rows 03 and 04 with values no row can have (`M05`, 167,
   `1225884.1`, `K27672`);
3. playing row 03 halted the instrument: `EXCEPTION DS0059`, `V05 M0 P400D9020`.

## What the file holds

`00_Resources/09_SampleProjects/AM REBECCA.dn2prj`, decoded with DNX's `dn2codec` and
`dn2song` (song table at image `+0xc3f004`):

| row | stored bytes (29) | reads as |
|---|---|---|
| 01 | `00000000001fe006000080000000000000000000000000000000000000` | A01, 1x, length 128, 68 BPM |
| 02 | `00010000001fe00000008000000000000000004c00355641f389362908` | A01, 2x, length 128, 68 BPM; its last ten bytes are not zero |
| 03 | `c4a62908c4a92908c4a83fffffff415825360000000000000000000000` | pattern 196, 167x, length 43,071 |
| 04 | `0000000000006b940070006ffc7000700070006fff0000000000000000` | length 28,672 (`0x7000`) |
| 05 | `0000000000000000006b94000000500051005200530054000000000000` | past the row count (4) |

About 90 bytes in a row, image `+0xc3f044..+0xc3f0a0`, from row 02's tail into row 05.
The song editor keeps a row's length in 2..1024 (`0x4007c7b6`), so no edit wrote these:
the song was overwritten in RAM and a save stored it. The run of values at or just
under `0x7000` is the LFO speed default (`SPD` 48), which stock's LFOs and LFO4 share.

## The halt

`0x400d9020` is `remsl %d7,%d6,%d0` in the factory routine that works out the song
position: `%d7` is the row's length times a speed factor from the table at `0x401f6b08`.
Row 03's values make it 0. Vector 5 is the ColdFire's divide by zero. A consequence of
the rows, not their cause.

`K24` in the length column is stock: `0x4007de30` prints a length above 999 as `K` and
the length minus 1000 (`K%02d`), so the column stays three characters. 1024 is the most
a row allows, and what a row gets when its pattern's length works out at 1 or less
(`0x4007cff4`).

## Where a song lives (1.11)

| | address | size | rows |
|---|---|---|---|
| live, song n (1..16) | `0x423fe4eb + 3694 (n - 1)` | 3,694 B | 37 B from `+0x1b`; the row count at `+0xe5f` (`0x4004a256` reads them) |
| stored, in the working image | `0x4120c970 + 0xc00 (n - 1)` | 3,072 B | 29 B from `+0x10` |

Songs 1, 2 and 4 were read on stock in the emulator as the song screen draws. On the
instrument every edit to a live row reached the stored copy within 20 ms.
`tools/dn2probe.py songwatch SECONDS [SONG ...]` reads both and prints every change.

## Ruled out, on rivvi's exact mod set plus the probe

`rivvi-songwatch-usbprobe_DN2_1.11.syx` on the owner's instrument, a new project, a
7-row song, LFOs in ONE and HALF and an LFO4 running (`out/rivvi/songwatch_*.log`):

| done | song 1 |
|---|---|
| ~10 min of song playback | no change |
| editing rows (pattern, repeats, length, tempo, mutes) | only the edits, each mirrored in the stored copy |
| SAVE PROJECT, load another, load it back (three times) | cleared, then restored byte for byte (58, 57 and 53 spans) |
| clearing patterns A3 and A5 from the pattern list, saving, reloading | no change |

None of the mods' code names an address in the live songs (a scan of every
`*_code.json` for words in `0x423e0000..0x42410000`). The LFO fix writes only its code
chunk (`0x467f8000`) and byte `+119` of the LFO state records (`0x4463f498..0x44640398`).

The emulator cannot play a song: it raises no audio-frame interrupt, so the sequencer's
clock never moves (`docs/sequencer-playhead.md`). Inserting rows, changing pattern and
clearing a pattern there changed only the rows made, the same on stock.

## Found on the way: LFO4 survives a cleared pattern

The owner, same session: after the clear from the pattern list, track 1 still held its
LFO4 settings, and they came back after SAVE PROJECT and a reload. Cause and fix in
`docs/mods.md` (Mod 8) and `scripts/emu_lfo4_clear.py`. In the pattern list the cleared
pattern still showed as empty, so this alone does not light a cleared pattern up.

## Earlier case

`docs/old-project-load.md`: SKETCHPAD's song 1 stored a row count of 21,503, entered
while the owner ran fxmod + lfo4 builds. rivvi runs both. A pattern of two, not a cause.

## Next

- rivvi's project on the songwatch build: a new song 2 with the same patterns, songs 1
  and 2 watched while it plays.
- Ask rivvi what rows 3 and 4 held before, and what they were doing when it happened.
- If a change shows up: take mods out one at a time; `stock-idle-usbprobe` is the
  control for a factory bug.
