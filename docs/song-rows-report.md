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

## The file sent to the instrument and read back (2026-10-10, DNX)

DNX wrote `AM REBECCA.dn2prj` to an empty +Drive slot (25) on the owner's instrument (rivvi's mod set plus the probe), read it back and compared the decoded images (12,890,116 bytes each).

| region | result |
|---|---|
| song 1's four rows | identical, the damaged rows included |
| patterns | 40,526 bytes differ, in 285 trig-pool slots: all free, none referenced by a track |
| kits | 499 bytes over 21 kits; no cluster at the offset LFO4 writes |

The store rewrites unused storage. The control, from files alone: the bytes that changed (four-byte values repeating with a stepping low byte) are in 107 of 128 patterns of the owner's healthy 1.11 project SKETCHPAD, in 102 of rivvi's, and in none of a never-used project. Never-written pattern records hold junk in their version field in both (A12, A62, A76, A126 in each). So the file shows damage in song 1 only. A healthy project's write and read-back has not been run.

**The bytes over the song rows are not from the project.** `c4 a? 29 08` occurs only inside song 1's row 03 in the whole image: no pattern, kit or other song holds it. Read as big-endian floats the run is -1329.28, -1353.28, -1346.00, then 13.51: the first two differ by exactly 24. Row 04 holds 16-bit values at or just under `0x7000`. So two kinds of working data from RAM, floats and then 16-bit parameter values, lay over the stored rows. Which code holds those is not known.

## Song 2 rebuilt from song 1's visible values (owner, 2026-10-10)

On slot 25's copy, on rivvi's mod set plus the probe, the owner entered in song 2 what the screen shows for song 1's four rows, track mutes included. `songwatch` on songs 1 and 2 (`out/rivvi/songwatch_5.log`):

| step | result |
|---|---|
| song 2 played through its four rows | stopped at the end as set; no byte of either song changed, live or stored |
| SAVE PROJECT, another project loaded, AM REBECCA loaded back | 40 spans cleared at the unload and restored at the reload, all byte for byte; the owner: the song looks fine |

## Does stock's LFO write astray on a mod-only waveform or destination? (emulator, 2026-10-10)

The owner's question: a project saved with the mods, then played on stock. `scripts/emu_stock_foreign_lfo.py` runs stock 1.11's evaluator A with every write classed as its own memory or a stray:

| case | result |
|---|---|
| control: TRI on a stock destination | clean, the destination moves |
| waveforms 7..15, 32, 127, 255 | clean, the destination moves |
| destinations 99, 100 | clean, the destination moves |
| destinations 101, 110, 127, 128, 200, 255 | clean, nothing is written (stock's bound is 100) |

With `--blind` (the mirror buffer no longer counted as the evaluator's) all 21 cases report strays, so the detector fires. This covers the evaluator only: stock's load of such a project, its pages drawing those values, and the MIDI tracks' evaluator are not tested.

## A mod-saved sound through stock's load and save (emulator, 2026-10-10)

The owner's sharper question: does stock, reading and saving the project, put LFO4's values or a mod-only destination in the wrong place? `scripts/emu_stock_sound_roundtrip.py`, stock 1.11, a live sound saved, LFO4's eight ids filled, loaded and saved again, every write classed:

| what the sound holds | what stock does |
|---|---|
| LFO4's eight stored ids | SAVE writes zero into all eight; nothing else in the stored sound changes |
| LFO3 DEST past stock's list (110, 127, 255) | comes back as a stock destination (19, 22, 61): the LFO points at another parameter |
| LFO3 WAVE past stock's list (9, 13, 255) | kept as it is |
| writes outside the sound | SAVE: none. LOAD: 86, the same addresses and count as the control |

So stock keeps everything inside the sound: LFO4's settings are lost and a mod-only destination turns into another one, and nothing is put elsewhere. Back on the mods, zero ids are the case lfo4's load already treats as "no LFO4". The DEST case went through stock's own SAVE, not the mods', so the numbers it comes back as may differ for a file the mods saved.

## Slot 25 after a session on the mods and a stock save while playing (DNX, 2026-10-10)

Three images compared: rivvi's file, DNX's first read of slot 25 ("before"), and slot 25 after the owner built and played song 2 on the mod build, saved there, flashed plain stock 1.11 and saved while the sequencer played ("after"). Pattern numbers below are 1-based across the banks (17..32 is bank B).

**Ten empty patterns became copies of pattern 2 (A02).** In "after", patterns 8, 11, 12, 15, 113, 115, 118, 121, 126 and 128 hold pattern 2's whole record (tracks, trig pool, lock records, length 128, tempo 68; 89 trigs) with their own slot index, and their kits are kit 2 byte for byte. All ten were empty or never written in rivvi's file and in "before". Neither earlier image has any two non-empty patterns alike. Which of the three steps did it is not known: the mod session, the mod build's save, or the stock save while playing. This matches rivvi's "cleared patterns kept coming back".

**Song 1's four rows are identical in all three images.** Song 2 holds the owner's four rows, all valid.

**Lit but empty patterns (owner, on stock: B04, B07) are normal for 1.11.** Their step flags have the trig bit set on tracks 6..8 (B04) and 2..3 (B07), mostly past the 16-step length, none with a note. The owner's healthy SKETCHPAD has more of the same (1,950 flagged steps past the track length in 45 patterns, against rivvi's 1,575 in 32). Their kits hold no LFO4 values, so the LFO4 leftover is not what lights them.

**Pattern 70 (E06) lost its version field on the way in.** 45 trigs in rivvi's file; in "before" the version reads `63 63 63 04` for `00 00 00 04`, with 166 track bytes and 5,476 lock-record bytes changed and the trig pool intact. That happened in DNX's write, the instrument's store or the mod build, before any stock save. What writes `0x63` is not known.

**Stock's save zeroes LFO4's ids on the instrument too.** Kit 3, sound with LFO4 values in rivvi's file and in "before", reads zero in "after" (the emulator result above, seen in a real save). The stored-sound layout is confirmed by DNX: sound n at kit + 0x3c + 359 n, each starting `be ef ba ce`.

## Earlier case

`docs/old-project-load.md`: SKETCHPAD's song 1 stored a row count of 21,503, entered
while the owner ran fxmod + lfo4 builds. rivvi runs both. A pattern of two, not a cause.

## Next

- rivvi's project on the songwatch build: a new song 2 with the same patterns, songs 1
  and 2 watched while it plays.
- Ask rivvi what rows 3 and 4 held before, and what they were doing when it happened.
- If a change shows up: take mods out one at a time; `stock-idle-usbprobe` is the
  control for a factory bug.
