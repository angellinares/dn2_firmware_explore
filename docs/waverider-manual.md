# Waverider, alpha

Documentation version 1.6, 2026-10-17. It describes Waverider 0.3.1 (alpha 5).

Waverider is a sixth synth machine for the Digitone II. A Waverider track plays two wavetable
oscillators, a sub-oscillator and a noise generator. Its own modulator (MOVE) sweeps each
oscillator through its table.

This is an alpha. Sounds that you save may not load the same way in a later version. Try it on a
new project. Back up the +Drive first, and keep the stock 1.11 firmware file for recovery.

## Before you start

- **Firmware:** use Digitone II OS 1.11 only.
- **Combining:** you can combine Waverider with the other mods. There are three exceptions: the LFO
  modulation of the FX, the fourth LFO and the FM drum transients. The pages refuse these three. You can patch a
  file that a different mod page made. We examined the combinations in the emulator, not on an
  instrument.
- **Try it alone first:** use a file patched with Waverider only. If a problem occurs, we then know
  that the cause is Waverider and not a combination of mods. When you report a problem, tell us
  which mods are in your file.
- **Wavetables:** Waverider has two built-in tables, Prim. and Harm. More tables come from DNX,
  which writes them to the +Drive. Each project has a pool of up to 128 tables.
- **Recovery:** if the unit does not start:
  1. Push and hold FUNC when you turn on the power.
  2. Open the Early Start-up Menu.
  3. Do an OS upgrade with the stock 1.11 file over MIDI DIN.

## Installing

1. Download the Digitone II OS 1.11 file of Elektron from elektron.se.
2. Open the Waverider page.
3. Load that file into the page.
4. Download the patched file that the page makes. The page patches the file in your browser and
   uploads nothing.
5. Back up the +Drive with DNX.
6. Open Elektron Transfer.
7. Connect the Digitone II to the computer with a USB cable.
8. Drag the patched file onto the Digitone II in Transfer. The unit updates and starts again.
9. Make sure that MACHINE SEL shows WAVERIDER after SWARMER.

No other steps are necessary. At first, the +Drive has no wavetables. When you add the first table
with DNX, the unit prepares the storage.

## Select Waverider

WAVERIDER is in MACHINE SEL, after SWARMER. A Waverider track has five SYN pages. The header shows
Waverider (1/5) to Waverider (5/5).

## Page 1 and page 2: the oscillators

Page 1 is for oscillator 1. Page 2 is for oscillator 2. The two pages have the same controls.

| Knob | Control | Function |
|---|---|---|
| A | TUNE (osc 1) / DETN (osc 2) | The pitch in semitones. TUNE changes the pitch of the two oscillators. DETN is the difference from oscillator 1 |
| B | LEV | The level, 0 to 127. At 100, the gain is 1 |
| C | POS | The position in the table, 0 to 120 |
| D | TBL | The table: Prim., Harm., then the pool tables from T:001 |
| E | RATE | The speed of MOVE, 0 to 100. When SYN1 or SYN2 is on, RATE shows a note length |
| F | MLEV | How much MOVE decreases the level, 0 to 127. At 0, MOVE does not change the level |
| G | MPOS | How much MOVE changes the position, 0 to 100. At 50, MOVE does not change the position |
| H | MOVE | The shape that MOVE follows. There are eleven shapes (below) |

The wave shows only one voice. Usually, this is the voice of the newest note. If not, it is the
first voice that the page selected. The unit calculates all the voices, and you hear all of them.

There are eleven MOVE shapes. These five shapes stop at their end: Ramp Up, Ramp Down, Exp Up,
Exp Down and Tri Once. These six shapes repeat: Up Loop, Down Loop, Tri Loop, Square, Rnd Hold and
Rnd Glide.

## Page 3: sub and noise

| Knob | Control | Function |
|---|---|---|
| A | SUB | The level of the sub-oscillator, 0 to 127. At 0, the sub-oscillator is off |
| B | OCT | -1, -2 or -3 octaves below the oscillator that it follows |
| C | WAVE | The wave: SIN, TRI, SQR or PLS (a 25 % pulse) |
| D | SRC | The oscillator that the sub-oscillator follows: OSC1 or OSC2 |
| E | NOIS | The level of the noise, 0 to 127. At 0, the noise is off |
| F | TYPE | The noise type: WHT, PNK, BRN or DIG |
| G | COLR | The tilt of the spectrum, -64 to +63. A negative value adds low frequencies. A positive value removes them |
| H | DEC | The decay of the noise after each note, 0 to 126 (5 ms to 10 s). At Inf, the noise stays at full level |

The middle of the page shows the sub-oscillator and the noise.

## Page 4: sound options

| Knob | Control | Function |
|---|---|---|
| A | PRST | The phase of the oscillators at the start of a note: Off, On or Random. With On, the phase starts at 0 and the same note has the same sound each time |
| B | TRIG | With Retrig, MOVE starts again on each note. With Free, MOVE does not start again on a note |
| C | DCLK | A crossfade when TBL or POS changes suddenly: Off, or 1 to 100 ms. A new sound starts at 3 ms |
| D | TRIM | The output level of the whole machine, -15.0 to 0.0 dB. The default is -11.0 dB. At this value, the level is the same as a default WaveTone. When you turn TRIM, the level moves to the new value over up to 0.1 s |
| E | SYN1 | Off or On. With On, the MOVE of oscillator 1 follows the tempo. SYN does not change the LFOs, which have their own tempo settings |
| F | SYN2 | The same as SYN1, for oscillator 2 |
| G | SLW1 | Slew: the slew time of POS on oscillator 1. It slews the POS that you hear: the knob, p-locks, LFOs and MOVE together. A new note starts at its POS without a slew. At 0, the slew is off. The slew gets longer as you turn the knob to the right, up to 1 s at 127. The Technical tab of the Waverider page has the details |
| H | SLW2 | The same as SLW1, for oscillator 2. Before version 0.1.1, SLW1 and SLW2 were called SMT1 and SMT2. Before version 0.3.1, Off was at 127. A sound saved with an earlier version plays its SLW value the other way round, so set SLW1 and SLW2 again on it |

The middle of the page shows the sound of the track as a scope.

## Page 5: Shape

FOLD, WARP, FM, TYPE, AMT, P1 and P2 change the sound. NPOS is for a future version: you can set and
p-lock it, but it does not change the sound yet.

| Knob | Control | Function |
|---|---|---|
| A | FOLD | Folds the wave of the two oscillators back on itself. 0 is off. A higher value gives more folds and a brighter sound |
| B | WARP | Bends the phase of the two oscillators. The first half of each wave plays in a shorter part of the cycle, and the second half in a longer part. 0 is off. A higher value gives a brighter sound |
| C | FM | Osc 2 changes the phase of osc 1 (frequency modulation). 0 is off. A higher value gives more overtones and a brighter sound |
| D | NPOS | No effect yet |
| E | TYPE | The shaper: Off, Ring, AM or Formant. Ring multiplies the two oscillators. AM uses osc 2 to change the level of osc 1. Formant filters the mix of the two oscillators so that it sounds like a voice that sings a vowel |
| F | AMT | With Ring and AM: how much of the shaper you hear, 0 is none and 127 is the shaper only. With Formant: the vowel, from A at 0 through E, I and O to U at 127 |
| G | P1 | With Formant: moves all the formants up, from no shift at 0 to one octave at 127. No effect with the other types |
| H | P2 | With Formant: the dry part. At 0 you hear only the filtered sound, and at 127 only the dry sound. No effect with the other types |

- **Ring and AM need osc 2.** On page 2, set LEV2 above 0. With osc 2 off, Ring makes the sound
  quieter and AM halves it.
- **AMT starts at 64** on a new sound. With TYPE at Off, AMT changes nothing.
- **Formant filters the oscillators only.** The sub-oscillator and the noise are added after the
  filter. Only AMT can take an LFO, so an LFO on AMT sweeps the vowels.
- **FOLD follows the level.** A higher LEV1, LEV2 or TRIM gives more folds.
- **FM and LEV2 are separate.** FM sets how much osc 2 changes osc 1. LEV2 on page 2 sets only how
  loud osc 2 is. With LEV2 at 0 you hear osc 1 alone, changed by FM.
- **FM and DETN:** the interval between the two oscillators sets the overtones. DETN at 0, +12, +19 or
  +24 semitones gives a harmonic sound. Most other values give a metallic sound.
- **WARP and FM change where the oscillator reads its wave.** They do not change POS or the table.
- **WARP and FM get softer on high notes.** There they would add harsh tones that do not belong to the
  note. The higher the value, the lower the note where this starts. At 127, WARP starts to get softer at about
  D#4 and is off from about D#7. FM starts at about G#4 and is off from about G#7.

## The wavetable pool

- **Tables:** each table has 1 to 64 frames. Each frame has 64 to 4096 points, in powers of two.
- **Names:** when you turn TBL, the header shows the table name, for example "T:004 name".
- **Add and remove tables:** use DNX, or use the wavetable page on the unit. To open the wavetable
  page, push PRESET/KIT two times. Each project has its own pool.
- **An empty pool:** a project with no pool has no pool tables. Its Waverider tracks play Prim.
  until you add tables. A new project (CREATE NEW) has an empty pool. A project that you saved
  before you installed Waverider also has an empty pool.
- **Your project file is a normal project:** the pool is on the +Drive, next to the project and not
  in it. Because of this, the stock firmware can load a project that you saved. Its Waverider tracks
  show as FM Tone, and the stock firmware reads their settings as FM Tone settings. Thus they have a
  different sound. We examined this in the emulator only, not on an instrument.
- **A deleted table:** its pool slot shows MISSING and plays Prim. The slot stays until you clear it
  with CLEAR SLOT. Because the slot stays, a sound that uses the slot does not change to a different
  table.
- **When you replace a table that plays:** the old table continues to play until the new table is
  ready. Then the old table crossfades into the new table, in the DCLK time. If the first table of a
  slot is not ready, the slot plays Prim. until the table is ready.

### The wavetable page

Push PRESET/KIT two times. The left column has three lists: LOAD, MANAGE and POOL. The right
column shows the pool of this project. IN POOL is the number of tables in the pool. FREE is the
number of empty slots. +DRIVE is the number of tables on the +Drive. The site's manual has
screen captures of the page and its lists.

- **Move:** push UP or DOWN, or turn LEVEL/DATA. Hold FUNC and push UP or DOWN to move 7 rows.
- **Open and close:** push YES to open a list. Push NO to go back. Push PRESET/KIT or NO on the
  wavetable page to close it.
- **Operations:** in a list, push RIGHT. Push UP or DOWN to select an operation, then push YES. An
  operation applies to the ticked rows. If no row is ticked, it applies to the highlighted row.
  Push NO or LEFT to close the operations.
- **LOAD:** the slots of the pool. Select a slot and push YES. If the last SYN page that you saw is
  page 2, the table goes to TBL2. If not, it goes to TBL1. RIGHT shows LOAD TO TBL1 and LOAD TO
  TBL2. On a track that is not a Waverider track, LOAD changes nothing.
- **MANAGE:** all the tables on the +Drive. A + shows a table that is in the pool. Push YES to tick
  a table. ADD TO POOL puts the ticked tables in empty slots. DELETE removes the ticked tables from
  the +Drive, after you confirm with YES.
- **POOL:** the slots of the pool. CLEAR SLOT empties the ticked slots. A MISSING slot stays until
  you clear it.
- **Empty slots** show a line of slashes.

## P-locks, LFOs and SAVE

- **P-locks:** you can p-lock all the controls on pages 1 to 5. The p-locks stay after a reboot, and
  after SAVE and LOAD.
- **LFO destinations:** all the controls except TYPE, P1 and P2 on page 5 are in the DEST list of
  the LFO. The controls are in two groups. Each group has the header SYN.

## Modulation on the page

When an LFO or MOVE changes POS or TBL, the page shows the value that you hear next to the value
that you set. Only POS and TBL show this, on the two oscillators. All other controls show only the
value that you set. When a control does not move, the page shows nothing more. The page removes the
range about two seconds after the movement stops.

- **Slow, less than 3 Hz:** a dot under POS shows the value that you hear. A dotted line shows the
  range of the sweep. A dotted cursor is under the position bar. The wave is the frame that you hear.
- **Medium, 3 to 12 Hz:** the dot is on a grey band. The wave shows the two frames at the ends of the
  sweep.
- **Fast, more than 12 Hz:** the page shows the band and the two frames, but no dot. The symbol ≈ is
  next to POS.
- **TBL:** the wave shows the table that you hear. The label shows the table that you set.

The reason for 3 Hz and 12 Hz: the page updates the screen up to 24 times a second. Up to 3 Hz
(1/8 of that rate), the dot moves smoothly. Up to 12 Hz (1/2 of that rate), the dot moves in steps.
Above 12 Hz, a dot that moves would show an incorrect, slower movement. For this reason, above 12 Hz the
page shows only the range.

## Going back to stock

Before you start, check these three conditions in DNX:

- You use Chrome or Edge. DNX needs one of them to save files into a folder.
- A DNX folder is set. To set it, click **settings** in the tool row, then **DNX folder**, then
  **Choose…**. DNX saves one file for each table there. Without a folder, DNX does not start the
  erase.
- **WRITE** is on, in the tool row at the top.

Then:

1. In DNX, click **settings** in the tool row. Back up and Erase work from every tool except the probe.
2. Under **Back up the +Drive**, click **Back up…**. This backup holds your projects, sounds and
   kits. It does not hold the wavetables.
3. Under **Erase the wavetable region**, click **Erase…**.
4. DNX asks "Save a copy of N wavetable(s) first?". Click **Save the copies**. On an empty store,
   the button reads **Carry on**.
5. Wait while DNX saves each table as a file in the DNX folder. On a full store, this takes
   minutes. These files are the backup of your wavetables.
6. DNX shows the counts and the names of what it will erase. Click **Erase the region**. DNX erases
   all the stored tables and all the pools, then reads the instrument again.
7. Flash the stock 1.11 file over MIDI, as in "Before you start".

Do steps 1 to 6 before step 7. Stock 1.11 cannot get access to the wavetable region. If you flash
the stock firmware first, the data stays on the +Drive. To remove it, flash this build again, do
steps 1 to 6, and then flash stock once more. The erase does not change your projects, presets,
kits and samples. A project that you saved with Waverider tracks stays on the unit.

To put a saved table back later, with Waverider on the unit:

1. In DNX, open the library.
2. In the list next to **Browse**, select **Wavetables**.
3. Drag the saved file onto a free slot in the **+Drive wavetables** list. This only stages the
   table. DNX does not send it yet.
4. Make sure that **WRITE** is on.
5. Click **Write staged tables**.

## Known limits in this alpha

- NPOS on page 5 does not change the sound yet.
- A click may occur if the pool loads again while a note plays on a pool table. Nobody has measured
  this on the unit. If you hear a click, tell us.
- We did not measure 4096-point tables on the unit.
- In a sound from a build before page 5, FOLD, WARP, FM and NPOS show 64. FOLD, WARP and FM then
  change the sound. To get the sound from before, set them to 0.
- With a 16-note chord and page 5 on all 16 voices, the DSP worked at most 76.3 % of a frame on the
  unit. No frame was missed in 10 minutes (2026-10-19).
  Refer to `docs/waverider-performance.md`.
