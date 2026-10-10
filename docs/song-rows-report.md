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

**Ten empty patterns hold copies of pattern 2 (A02): the owner's own copies.** In "after", patterns 8, 11, 12, 15, 113, 115, 118, 121, 126 and 128 hold pattern 2's whole record (tracks, trig pool, lock records, length 128, tempo 68; 89 trigs) with their own slot index, and their kits are kit 2 byte for byte. The owner copied patterns by hand that day, looking for an action that damages a song. So this is the instrument's copy and paste, which takes the kit with the pattern, and not a fault. Neither earlier image has any two non-empty patterns alike.

**Song 1's four rows are identical in all three images.** Song 2 holds the owner's four rows, all valid.

**Lit but empty patterns (owner, on stock: B04, B07) are normal for 1.11.** Their step flags have the trig bit set on tracks 6..8 (B04) and 2..3 (B07), mostly past the 16-step length, none with a note. The owner's healthy SKETCHPAD has more of the same (1,950 flagged steps past the track length in 45 patterns, against rivvi's 1,575 in 32). Their kits hold no LFO4 values, so the LFO4 leftover is not what lights them.

**Pattern 70 (E06) lost its version field on the way in.** 45 trigs in rivvi's file; in "before" the version reads `63 63 63 04` for `00 00 00 04`, with 166 track bytes and 5,476 lock-record bytes changed and the trig pool intact. That happened in DNX's write, the instrument's store or the mod build, before any stock save. What writes `0x63` is not known.

**Stock's save zeroes LFO4's ids on the instrument too.** Kit 3, sound with LFO4 values in rivvi's file and in "before", reads zero in "after" (the emulator result above, seen in a real save). The stored-sound layout is confirmed by DNX: sound n at kit + 0x3c + 359 n, each starting `be ef ba ce`.

## Can a paste do it? (emulator, 2026-10-10)

The owner's idea: something on the clipboard pasted in the wrong place, from an LFO page or LFO4's. `scripts/emu_song_paste.py`, stock 1.11 and rivvi's mod set (`out/rivvi/rivvi_combo.syx`), every stage read off the screen as well.

**Into the song editor** (song 1 with two rows, row 02 selected, [FUNC] + [STOP]):

| on the clipboard | stock | rivvi's set |
|---|---|---|
| control: row 02 with another length, pasted on row 01 | row 01 changes, "PASTE ON ROW 01" | the same |
| an LFO page (LFO1, LFO2, LFO3) | song unchanged | song unchanged |
| LFO4's page | - | song unchanged |
| a track | song unchanged | song unchanged |
| a pattern | song unchanged | song unchanged |

**An LFO page pasted everywhere else** (TRIG 1..2, SYN 1..4, FLTR 1..2, AMP, FX, the other LFO pages, a track, a pattern; all sixteen songs read after each):

| copied | result |
|---|---|
| LFO1, stock and rivvi's set | no song byte changes anywhere; it pastes onto LFO2 and LFO3 only ("PASTE PAGE LFO2", 2 kit bytes) |
| LFO4, rivvi's set | no song byte changes anywhere; it pastes nowhere |

Found on the way: LFO4's page says "COPY PAGE LFO4" but its paste does nothing, onto LFO1..3 or elsewhere, and LFO1's page does not paste onto LFO4. Harmless, and a gap in the mod: the fourth page has no working copy and paste.

Not covered: any of this while the sequencer plays (it does not run in the emulator).

## rivvi's file beside the owner's damaged SKETCHPAD (2026-10-10)

`scripts/song_area_compare.py` on the decoded images: the 0xc00 bytes from image `0xc3ee04`, which is 0x200 before the 1.11 song table (`0xc3f004`) and so covers the start of song 1's rows.

| project | non-zero bytes there | extent | `3f ff ff ff` | what broke |
|---|---|---|---|---|
| 004 SKETCHPAD OS111 (owner, 2026-09-22) | 809 | +0x007..+0x8f6 | 19 | the field read as song 1's row count: 21,503, the halt on load (`docs/old-project-load.md`) |
| AM REBECCA (rivvi) | 440 | +0x007..+0x8af | 13 | song 1's rows 02 (tail) to 04, and unused rows after them |
| project 11 (owner, healthy, song 1 empty) | 606 | +0x002..+0x8f7 | present | nothing: no live field under it |

**It is the same data in the same place.** In all three: 4-byte words, `3f ff ff ff` every 0x30 to 0x90 bytes followed by small numbers (0x19, 0x20, 0x23, 0x43, 0x53, 0x59), and fragments such as `56 41 4c 31` ("VAL1") and `be 00 ba ce`. Songs 2 to 16 are clean in all three. rivvi's row 03 ends in `3f ff ff ff`, so the two rows are part of this run. The earlier reading of row 03 as floats and row 04 as LFO values is withdrawn: they are this leftover data.

**Where it is absent:** in all 54 exports written by 1.10E and in two fresh 1.11 projects, `3f ff ff ff` appears nowhere near song 1. In the used 1.11 projects it appears thousands of times image-wide (SKETCHPAD 3,706; AM REBECCA 7,442), mostly in unused storage.

So the two cases look like one thing: leftover working data lying over the start of song 1's storage, harmful only when song 1 holds something there. Not known: what writes it, and whether plain stock 1.11 does or only a modded unit (all three projects come from units that ran mods).

## The leftover data is LFO evaluator state (2026-10-10)

**What it is.** Stock 1.11's evaluator A, run 40 frames in the emulator, leaves its state block (`0x4463fc18`, 1,920 bytes) as 48 records of 40 bytes: `3f ff ff ff`, 0, a small number, a signed word, a value, 0, 0, three accumulators. The records in the project files have that shape and spacing. DNX's lattice walk: in rivvi's file, SKETCHPAD OS111, SKETCHPAD-repaired, projects_11 and the slot 25 reads, every record near song 1 sits on one 40-byte lattice whose origin is image `0xc3ee28` (RAM `0x4120c794` with the working image at `0x405cd96c`), 0x1d8 before song 1. The non-zero run is 54 records in rivvi's file and 57 in SKETCHPAD OS111 and projects_11. rivvi's row 03 is record 13. So LFO state lands at one fixed address, across projects and across builds from 2026-09-22 on.

**Stock or lfo4: not separated.** Stock has 16 x 3 = 48 records per array and three arrays back to back (backup `0x4463ed18`, second `0x4463f498`, live `0x4463fc18`). lfo4 moves them to `0x46702000`, `0x46701000`, `0x46700000` and makes each 64 records, 2,560 bytes. A run of 57 fits one lfo4 array or two adjacent stock arrays, so the width does not decide it. Every 1.11 project held comes from a unit that ran mods; no 1.10E export and no fresh 1.11 project has a single record there.

**Ruled out in the emulator:**

| question | result |
|---|---|
| does the evaluator on an lfo4 build write into the project image? (`scripts/emu_lfo_state_escape.py`: boot from reset, LFO4 on 16 sounds, backup flag 0, 1, 0xff, 0x100) | 0 writes in the image's 12.9 MB |
| the same on rivvi's full set with lfofix (`out/rivvi-lfo4reset1`), LFO1..3 on every track in ONE, then HALF, one trigger and 300 frames (a ONE cycle at MULT 8 is 47 frames, a HALF 24) | 0 writes in the image. The stop itself was not read back: the harness's destination cell saturates |
| does lfo4 leave a stock reference to the state arrays unmoved? | no: all 13 references are repointed or replaced, `0x401373b8` by a cave |
| does stock's allocator hand out memory at lfo4's arrays? | no: its arena ends at `0x4664abf0`, below the end of stock's data (`0x466b74d0`) |
| does stock touch memory above its data during SAVE PROJECT AS and LOAD PROJECT? (panel_drive, the card image) | no byte changes in `0x466b74d0..0x46700000`, and no access above it |
| does 1.11's conversion of an older project leave a hole there? (`0x400e0362`, version 4 to 5) | no: it is whole-block copies, songs moved up 0x200; it carries whatever the old image held |

rivvi moved from the build ending `lfo4_lfohold` to the one ending `lfo4_lfofix` (owner, 2026-10-10); whether the rows broke before or after is not known.

**Not found:** the write itself. The song watch on rivvi's set saw no change at stored song 1 through hours of playback, saves and reloads, so it is tied to an event not yet reproduced.

## The records are rivvi's own LFOs, and LFO4 is among them (2026-10-10)

The owner's question: do the records over song 1 match the LFO settings of a sound in the file? `scripts/lfo_state_match.py` on rivvi's decoded image.

**The record's fields**, measured on stock's evaluator A in the emulator by changing one setting at a time: phase (+0), output (+4), two random words (+8, +12), fade level (+16, `3f ff ff ff` once faded in), a word, **DEST as a mirror slot (+24)**, the output after DEP (+28), a phase copy (+32), flags (+36). The lattice of the section above therefore starts 16 bytes earlier, at image `0xc3ee18`: what was read as a record's first word is its fade level.

**The match.** 21 records name a destination. Every one of the five slots they name is the destination of an LFO stored in the file, and only tracks 9 to 12 of A01, A02, A03 and A09 use them:

| slot in the records | stored LFO | records |
|---|---|---|
| 89 | track 11 LFO1 (A01, A09), HOLD, RND, DEP 6937 | 7, outputs up to 12,564 |
| 35 | track 11 LFO2 and LFO3, HOLD, RND, DEP 4395 and 42af | 11, outputs up to 1,651 |
| 50 | tracks 9 and 10 LFO1, TRIG, DEP 3ff5 | 1, output 25 |
| 25 | track 11 **LFO4**, HOLD | 1 |
| 67 | track 12 **LFO4**, TRIG, waveform 10 | 1 |

The size of each record's output follows the stored DEP: large for 6937, small for 4395, 25 for 3ff5.

**Four records a group, not three.** Taking the record index modulo 4: position 0 holds only LFO4's destinations (25, 67), position 1 only LFO1's (89, 50), positions 2 and 3 only 35. Modulo 3 the same destinations fall on every position. Stock keeps three LFO records a track; a build with LFO4 keeps four. So the data was written by a build with LFO4, from this project.

**Not explained:** slots 89, 35, 35 repeat in at least seven groups, with different phases, while the stored kits hold those settings on track 11 only. Either several tracks held that sound when the data was written, or the groups are not one per track.

**TRIG MODE in the file:** no stored LFO is in ONE or HALF. Track 11's four LFOs are in HOLD; tracks 9, 10 and 12 use TRIG.

## The state is in every 64 KiB of the project, not at one address (2026-10-10)

Step 1 of the hunt (an agent's forensics on rivvi's image, SKETCHPAD OS111 of 2026-09-22, SKETCHPAD-repaired, project 11 and the slot 20 readback; scripts and outputs in the session scratchpad, `step1/`). It corrects three statements above.

- **Where.** LFO state sits at offset +0xed00..+0xf700 (2,560 bytes, 64 records) of every 64 KiB of the decoded image, in all 196 chunks that reach that offset. Song 1 is chunk 0xc3. Checked again here on rivvi's image: 7,243 of 7,442 `3f ff ff ff` fall in that window, in 196 of 196 chunks. The 1.10E exports and fresh 1.11 projects have none. So "one fixed address" and "mostly in unused storage" were wrong: about half of the project's own bytes under each window are overwritten.
- **The block** in the song chunk is image `0xc3ed00..0xc3f700`, 64 records in every file (not 54 or 57), and a group is LFO1, LFO2, LFO3, LFO4 from the window's first record. LFO4's record follows the track (rivvi: slot 25 only in group 10, slot 67 only in group 11); LFO1 to LFO3's content repeats across groups.
- **The owner's files match their own LFOs too.** SKETCHPAD OS111: slots 25, 5, 83, 32, 6, 26, 98, 89, each triple the LFO1..3 destinations of one stored sound of G01 (tracks 2, 3, 4), clean on a period of 4, the fourth position holding running phases with no destination. Project 11: slot 67, LFO3 of tracks 9 to 12.
- **It is written while the project passes.** One record followed through the 196 windows is a time series (SKETCHPAD record 3: 75 distinct phases, steps of about 9 to 10 evaluator updates a chunk). rivvi's "fragments" (`VAL1`, `be 00 ba ce`, `47 00 48 00 ...`) are stored-kit MIDI data of earlier chunks' windows, left in the fields the evaluator does not rewrite.
- **Reading.** 2,560 bytes and four records a track are lfo4's array (`0x46700000`, `0x46701000`, `0x46702000`). Something that handles the project stream uses a 64 KiB unit that one of those arrays lies inside; 64 KiB is two of the project file's 32,768-byte linked LZ4 blocks. Which routine, which direction (save or send, load or receive) and where the unit starts: not established. `ramcheck.py`'s premise, that stock uses no RAM above its data (`0x466b74d0`), is what step 2 tests.
- **Dating.** SKETCHPAD was clean in the 2026-09-06 export and affected on 2026-09-22 17:14; the arrays moved above the data in `5f8310c` (2026-09-17). The first fxmod build is 2026-09-22 20:26, after the damage, so fxmod is not needed to explain it.
- **Still seen on 2026-10-05:** SKETCHPAD-repaired against its readback from slot 20 differs in 354 window bytes over 43 chunks.
- **Not followed:** four more state blocks off the 64 KiB lattice in rivvi's A02, A03 and A09; address-shaped values in rivvi's settings at image `0xc3e080..0xc3e0f0`; 1,023 changed bytes outside windows in chunk 0x63 of the slot 20 readback.

## Earlier case

`docs/old-project-load.md`: SKETCHPAD's song 1 stored a row count of 21,503, entered
while the owner ran fxmod + lfo4 builds. rivvi runs both. A pattern of two, not a cause.

## Next

- rivvi's project on the songwatch build: a new song 2 with the same patterns, songs 1
  and 2 watched while it plays.
- Ask rivvi what rows 3 and 4 held before, and what they were doing when it happened.
- If a change shows up: take mods out one at a time; `stock-idle-usbprobe` is the
  control for a factory bug.
