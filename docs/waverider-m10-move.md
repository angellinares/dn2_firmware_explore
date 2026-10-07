# Waverider M10a: MOVE, the per-oscillator modulator

Milestone 10a fills the last four places on each oscillator's page with a modulator.
MOVE is a shape that runs at its own rate and moves that oscillator's position (MPOS) and
level (MLEV). It also adds a third page with two switches, PRST and TRIG.

Page layout:
- Page 1 (OSC 1): TUNE LEV POS TBL / RATE MPOS MLEV MOVE.
- Page 2 (OSC 2): the same, with DETN in place of TUNE.
- Page 3: PRST TRIG.

Sources: `csrc/waverider/sharc/modulator.asm` (new), and `reader_m9.asm` and
`machine9_live.asm` (the DSP); `src/dnfw/waverider/pages.py`, `coldfire.py` and
`csrc/waverider/page.c` (the pages). The reference model is `live.render_two` with
`move_step`, `move_shape` and `move_apply`.

## The parameters

As in M9, every control is a WaveTone record that Waverider does not otherwise use, so
p-locks, LFO destinations, CC and SAVE/LOAD are WaveTone's own. A record can't be added
without relocating the parameter table: 321 fixed records and 56 references to it. The
SHARC reads slot s at frame offset `168 + 2s`.

| control | osc 1 | osc 2 | range |
|---|---|---|---|
| RATE | 240 (slot 29) | 244 (slot 35) | 0..100; one cycle a second at 50, twice as fast every +10 |
| MPOS | 246 (slot 28) | 250 (slot 34) | 50 = none; above 50 adds the shape to POS, below subtracts |
| MLEV | 252 (slot 38) | 256 (slot 43) | 0 = none; 127 = the shape gates the level fully |
| MOVE | 253 (slot 40) | 257 (slot 44) | five bands: ramp down, ramp up, triangle once (0..76, one-shots); triangle loop, square loop (77..127) |
| TRIG | 259 (slot 46, both) | | 0 = MOVE restarts on each note; 1 or 2 = free-running |
| PRST | 249 (slot 39, both) | | Off / On / Random (RSET's own names); default On |

**The default sound is unchanged.** With MPOS at 50 and MLEV at 0, the modulator skips the
arithmetic, so a default Waverider sound is bit-identical to M9's.

**PRST** restarts both oscillators' phase on a note:
- On (the default): phase 0, so the same note sounds the same every time. Before PRST, the
  oscillators ran freely, and a repeated note varied from hit to hit (owner, on
  `waverider-m10a2`, 2026-10-02).
- Random: a random phase. A generator at DM `0x2ddea0` mixes in `EMUCLK` each note. On its
  own `EMUCLK` would do, but it reads 0 in the emulator, so the gate saw phase 0.
- Off: free-running, as M9.

## The DSP

The modulator runs once per oscillator per block, before the reader, from the loop's
`JUMP 0x16f700`. It returns at `wr_t5v_modded`.
- **Front half:** `modulator.asm` at sw `0x16f700`. It reads the six controls through a
  per-oscillator row of frame offsets at DM `0x2de780` (RATE MPOS MLEV MOVE TRIG PRST),
  and computes the trigger bit (the note mask at frame offset 34, bit t). It restarts the
  phase if TRIG is 0, steps it by `F[r mod 10] << (r div 10)` (the table F at DM
  `0x2de7d8`), and picks the band.
- **Back half:** `wr_mod_b` in the reader's span, because the modulator did not fit in
  one. It computes the shape's value, applies MPOS and MLEV in float32 as
  `live.move_apply` does, then runs the PRST block.

The per-voice phases sit at DM `0x2de700`: 16 voices × 2 oscillators, a u32 each. A
one-shot band stops at its end, while a loop band wraps.

## The pages

Page 3 is WaveTone's page id 9, which the stock code sends to its own grid at
`0x400175e4`. So a hook at `0x40018208` (`wr_grid9`) draws Waverider's grid instead. The
C renderer moved to `LOAD + 0x500` to make room. The wave on pages 1 and 2 does **not**
follow MOVE yet, because the modulator runs on the DSP. In M10b, the DSP will report each
voice's offset in its reply.

## The gate

`scripts/sharc_waverider_m5.py`, 37/37 on `waverider-m10a5`:
- `move_pos`: POS swept by a fast ramp;
- `move_lev`: LEV shaped by a looping triangle;
- `move_free`: TRIG 1 not restarted by a note;
- `move_osc2`: osc 2's own modulator;
- `prst_off` and `prst_random`;
- the default sound bit-identical.

Each run is bit-exact against `live.render_two`.

## On the instrument

`waverider-m10a5-usbprobe`, 2026-10-03, all steps passed:
- the same note sounds the same with PRST On;
- PRST Off and Random behave as described;
- MOVE sweeps POS, loops, and gates the level;
- the other tracks are unchanged.

TRIG 1 was checked with a level gate: a square MOVE at RATE 30 (a 4 s cycle, 2 bars at
120) with MLEV 127 turned the sound on and off in bars, while TRIG 0 kept every note
whole.

**Known: a free square clicks mid-note.** With TRIG 1, the square's edge falls wherever
play started relative to the grid, and it jumps between silent and full within one
32-sample block. An edge inside a trig is a click: around trig 10 in the owner's run,
gone with TRIG 0. For M10b:
- a beat-synced RATE, so edges land on steps;
- a few milliseconds of smoothing on the square's edges.

# M10b-1: MOVE as named shapes

Owner, on M10a: a 0..127 control with no feedback was "quite hard to use and remember".
So MOVE is now a stepped control of five shapes, and the header names the one chosen:
0 Ramp Down, 1 Ramp Up, 2 Tri Once, 3 Tri Loop, 4 Square. TRIG reads Retrig (0, the
default) or Free (1). The DSP reads MOVE as the shape's index, and any value past 4 is
the last shape, so an LFO's overshoot and a sound saved under M10a (0..127) read as
Square.

**Only on a Waverider track.** The records stay WaveTone's: MOVE1 is its Noise Attack,
MOVE2 the noise filter Base, and TRIG the Noise Type. So nothing in a record changes.
Three hooks answer for these ids, and only when the active track is a Waverider (`is_wr`):

| hook | site | what it answers |
|---|---|---|
| `wr_range` | the entry of `0x400dbff0(id)`, which every clamp asks for {min, max, default} (the knob turn `0x40036adc` among 14 callers) | MOVE 0..`0x400`, TRIG 0..`0x100` |
| `wr_fmt` | `0x400c2464`, in `0x400c243c(id, value)`: the call of the record's naming routine (table + 60 id + `0x34`) | the shape name, Retrig / Free |
| `wr_vfmt` | `0x40036708`, the tail call of the same routine in the parameter set's value text (vtable `+0x5c`, `0x40036692`) | the same |

The two value-text paths were found in the emulator. Turning PRST, a read watch on
RSET's Off / On / Random strings found the first. A register trace at the SYN page's
readout found the second: every value text in that trace went through `0x40036692`.
The page (`csrc/waverider/page.c`) draws MOVE and TRIG from the same limits
(`pages.RANGES`, via `wr_gen.h`), as five and two segments.

**Checked in the emulator.** Direct calls of both value-text routines give the
following on a Waverider:
- MOVE 3: "Tri Loop";
- MOVE `0x7f00`: "Square";
- MOVE2 1: "Ramp Up";
- TRIG 1: "Free", TRIG 0: "Retrig".

PRST and LEV print as stock. The same calls on another machine give the stock numbers.
The knob routine clamps MOVE to our maximum, the same way it clamps PRST to its own. One
shape per detent can't be shown in the emulator, which delivers a detent as a delta of
4 steps to every stepped control.

**On the instrument** (`waverider-m10b1b-usbprobe`, 2026-10-03), all five steps passed:
- MOVE goes one shape per detent, with the shape named in the header;
- the five shapes sound as in the reference WAV;
- osc 2's MOVE behaves the same;
- TRIG reads Retrig / Free;
- WaveTone's Noise controls are unchanged.

Owner's follow-up: "Osc1 Move Shape" was too long for the header, so the long names are
Osc1 / Osc2 M.Shape, and likewise M.Rate, M.Pos and M.Level.

Still to come in M10b:
- page-3 options for a beat-synced RATE and for smoothing the square's edges (M10b-2);
- ~~the page's wave following MOVE~~: M10b-3, below.

# M10b-3: the page's wave follows MOVE

MOVE runs on the SHARC (`modulator.asm`), so the value array the page reads never sees
it. The page drew POS where the knob was while the sound moved.

## The report

After every MOVE block (`reader_m9.asm`, `wr_mod_done`) the DSP writes the shape's high
byte for that voice and oscillator into the reply's last 32 bytes (`+0xa9c`), byte
`2t + osc`, in the page `DM(0x2c0450)` selects. The DMA delivers those bytes every frame,
and no stock ColdFire code reads them (zero on the instrument in every state measured).
The ColdFire sees them at `0x80005e40`. To make room, M10a's PRST block moved unchanged
into `idle_load.asm`'s span. The SHARC gate checks every byte against the phase the DSP
stored, for every voice and oscillator it ran.

The page (`csrc/waverider/page.c`, `move_offset`) applies the DSP's own arithmetic,
`(MPOS - 0x3200) x shape x 0x7800 / (0x3200 x 0xffff)`, and adds it to the offset its
markers already use. So the drawn wave, the position cursor, the swept range and the
redraws all follow MOVE. A MOVE pushed past either end of the table holds the end frame
in the sound, and the cursor pins at that end too (owner: keep it that way).

## Which voice the page follows

The page draws one voice. Getting that right took five rounds on the instrument:

| build | owner's report | cause | fix |
|---|---|---|---|
| m10b3b | a one-shot animated once, then stood still on later trigs | each trig plays on the next voice (the probe: 15, 3, 5, 4, 8, 9, 10, 13 for one Ramp Up); the page kept its first voice, standing at its ramp's end | follow the voice whose report moves after standing still for 0.5 s (a new note) |
| m10b3d | the first lap of trigs after arriving on a page did not animate | a voice reads as Waverider (its machine word) only once it has played a Waverider note, which comes after its report has begun to move | a voice that is not yet the track's keeps its start pending |
| m10b3e | page 1 followed only every other note while osc 2 ran a Tri | either oscillator's byte counted, and osc 2's loop kept every voice from standing still | judge each voice by the shown oscillator's byte only |
| m10b3f/g | irregular jumps with unison, 3-note chords and a Tri restarting on each note | a looping shape never stands still, so the page kept an old voice and jumped when the rotation retriggered it | a jump of more than 96 steps between polls is a restart, so a new note (not for Square, which jumps by design, nor past RATE 60, where motion could pass for a jump) |
| m10b3g | the wave stepped visibly, even with the pattern stopped | the page redrew only when the offset moved by `QUANT`, half a pixel of the cursor but 37 % of a frame of the wave's morph: about 7 redraws a second for a slow Tri | POS redraws on a 1/16-frame step (`POS_QUANT`); the 24-a-second cap stays |

At high RATE the page draws the band between the sweep's two ends. Those ends were
sampled at the redraw rate and wandered, so the end waves changed for a fixed sweep. In
m10b3h a fast MOVE's ends are computed: shape 0 and 255 through the same arithmetic,
plus whatever the LFOs add at that moment.

The emulator checks poke the report bytes and capture the screen
(`out/m10b3_follow*.sh`): the rotation case, a voice's first note, and a note on the
shown oscillator while the other one keeps moving. Each was run beside the previous
build as a control that has to fail. The restart rule's own check did not discriminate
(both builds switched on the first movement after a long still); the instrument settled
it.

## What the page costs

`m10b3h-prof` (the page's draw timers, `WR_PROBE`), with Waverider on every track and all
voices busy:

| state | redraws | ColdFire CPU | longest audio interrupt (share of a frame) |
|---|---|---|---|
| stock FILTER page, hands off | about 1 every 2 s | 58.9 % | 112 % every other second |
| our page, wave still | about 1 every 2 s | 58.8 % | the same |
| our page, animating | 18 a second | 61-63 % | 112 % most seconds |
| stock FILTER page, a knob turning | about 26 a second | 65 % | 112 % every second |

- A draw takes 1.84 ms, 0.63 ms of it our wave; the page costs 3.3 % of the ColdFire
  while animating.
- **The 112 % peak is the stock UI's.** Every redraw of any page lengthens one audio
  interrupt to just over a frame; our page matches the stock one at rest, and causes
  fewer peaks than a stock page while a knob turns. No audio frame was lost in any state
  (1,500 a second).

## On the instrument

`waverider-m10b3h-usbprobe` / `-prof` (2026-10-03), the owner: the wave follows MOVE on
both pages, from the first trig after a reboot, on every note under unison and chords,
with loops restarting cleanly and no hopping on Square.

# The tables in DDR

The two wavetables (32 KB: 16 frames x 512 int16 each) moved from L1 block 1's free
tail (`0x2df000`, `0x2e3000`) to the SHARC's DDR (`0x80600000`, `0x80604000`). L1 is the
fast memory; its free tail was about 43 KB in all, and the modulator's 512-byte slot
before table 0 was full. Now L1 holds only code and state, and the modulator's span runs
to the region's end (about 33 KB). The reader is unchanged: the loop takes each table's
address from the directory (`machine9_live.asm`, `0x2de608`), so only `dsp.py` moved.

**Why that DDR is free.**
- The stock stream's last DDR byte is `0x8052fbe0` (`dnfw ldr`).
- No aligned data word in L1, L2 or DDR names DDR above it. The 24 hits are pairs of
  negative int16 samples, and the control finds 36 words naming the image's own DDR.
- No code immediate does either, in selmap's disassembly of every code region. The
  control finds 73 naming the image's own DDR; the few hits are absolute operands of
  data read as code.
- `0x80600000` sits 720 KB above the image and below `0x80a00000`, where the Digitakt II,
  on the same board, keeps its 32 MiB sample pool. So the memory exists, and a ported
  pool would not collide.
- DDR has no `0x28` load alias, so a table's boot block targets its own address.

Limit, as for the block-1 region: this cannot exclude an address computed at run time.
The instrument is the check.

**On the instrument** (2026-10-03, A: `m10b3h-prof`, tables in L1; B:
`waverider-ddr-usbprobe`, identical but for the table addresses; Waverider on every
track). `dn2sharc_load.py --idle`, 10 intervals each:

| state | A: L1 | B: DDR | change |
|---|---|---|---|
| heavy chords, all voices | 51.8 % (C 48.3) | 52.5 % (C 49.0) | +0.7 |
| one note | 51.6 % (held) | 52.7 % held, 52.3 % sequenced | +0.7 to +1.1 |
| silent | 51.6 % | 52.3 % (C 48.9) | +0.7 |

- It sounds the same (owner).
- DDR costs about 0.7 points of the SHARC, about 4,700 cycles a frame, nearly constant,
  and all of it in part C, where the reader runs. With Waverider on every track the
  reader runs each block whether or not a note sounds, so silence still reads the tables.
- Decision (owner): keep the tables in DDR. The 32 KB of L1 goes to code and per-voice
  state (M10b-4's shapes first), and tables loaded from the +Drive will live in DDR
  anyway.

# M10b-4: eleven shapes

MOVE now has eleven shapes, sorted by nature (owner, 2026-10-03). Index 0..10 is what
the DSP reads; any value past 10 is the last shape.

| index | shape | value at x = phase >> 16 |
|---|---|---|
| 0 | Ramp Up | x |
| 1 | Ramp Down | 0xffff - x |
| 2 | Exp Up | x^3 / 2^32, float32 |
| 3 | Exp Down | (0xffff - x)^3 / 2^32 |
| 4 | Tri Once | up to 0xffff at half the cycle, then down |
| 5 | Up Loop | as 0, looping |
| 6 | Down Loop | as 1, looping |
| 7 | Tri Loop | as 4, looping |
| 8 | Square | 0xffff for the first half, then 0 |
| 9 | Rnd Hold | b, held for the cycle |
| 10 | Rnd Glide | a + (b - a) u^2 (3 - 2u), u = x / 2^16, float32 |

Shapes 0..4 stop at their end (the phase saturates); 5..10 wrap.

**The random shapes.** Each voice and oscillator keeps the value before (a) and the
value now (b) at DM `0x2df400 + 8 (2t + osc)`. A new value is drawn on a cycle's wrap,
and on a note when TRIG is Retrig: a takes b, and b the generator's high half. All the
voices share one generator at `0x2df500`: x = rotate(x, 7) + 0x6d2b79f5. That's PRST
Random's step without the cycle counter, so a render repeats and the gate can check it.
In tests it doesn't repeat within 5M draws, its buckets are even, and its lag-1
correlation is -0.01. The page's names avoid "&": no stock UI string uses it, so the
font may not draw it.

**Where it runs.** `csrc/waverider/sharc/shapes.asm`, at sw `0x16f800` (DM `0x2df000`),
in the L1 the tables left when they moved to DDR. `wr_mod_b` hands it the phase and
gets the value back at `wr_mod_have`. That shortened the reader's span by 112 bytes.
`scripts/sharc_resolve_jumps.py` now resolves a jump into another of our sources from
that source's own layout.

**The page.** The restart rule leaves out every shape whose report jumps by itself: Up
Loop and Down Loop at each wrap, Square, and Rnd Hold at each new value. Before, it
left out only Square. Known: at a slow RATE, Rnd Hold stands still and then changes,
which the stillness rule can take for a new note on another voice.

**The gate.** `scripts/sharc_waverider_m5.py`, 43/43 on `waverider-m10b4`: Exp Up, Down
Loop, Rnd Hold, Rnd Glide, and both random shapes at once. Every run is bit-exact
against `live.render_two`, and the report check reads the DSP's random pair. Its first
run failed on Rnd Glide alone: the code kept b in R0 and then wrote F0, which is the
same register. A probe of just that case showed the DSP's position pinned at the top
from block 0.

Sounds saved with M10b-1's five shapes read the new order: old 0 Ramp Down reads Ramp
Up, 1 Ramp Down, 2 Exp Up, 3 Exp Down and 4 Tri Once.

**On the instrument** (2026-10-04, `waverider-driveread-usbprobe`, whose section 7 is
m10b4's), all four steps passed:
- every shape is named in the header, one per detent, and sounds as in
  `m10b4_shapes.wav`;
- osc 2's MOVE does the same;
- with 3 voices on Up Loop, Down Loop, Square or Rnd Hold, the page stays on one voice.

## Clicks at a looping shape's reset (owner, instrument, 2026-10-05; measured in the reference)

The owner hears a click at each reset of a fast repeating MOVE shape, on every table.
It comes from the POS jump at the reset, not from the oscillator's phase or a zero
crossing.
- POS changes once per 32-sample block. At a reset it goes from (say) frame 15 to
  frame 0 between two samples.
- The oscillator's phase runs on, but the output steps from one frame's value to the
  other's at that phase.

The measurement, in `dnfw.waverider.live`, which the runner matches bit for bit. Prim.,
2 s, RATE 0x6400, MPOS 0x6400. A boundary counts when its step exceeds both in-block
steps beside it by more than 0.05:

| MOVE | jumps per cycle | boundaries that step |
|---|---|---|
| none | — | 0 |
| Tri Loop | 0 | 0 |
| Up Loop / Down Loop | 1 | 43 / 45 |
| Square | 2 | 90 |

**Decided (owner, 2026-10-05): fold a declick into M10b-2.** When POS jumps further
than a threshold, crossfade from the old position to the new over about 1 ms; the same
short fade applies to LEV for a Square on LEV.
- It removes the click and keeps the jump.
- The cost is a second table read during the fade.
- It gets an on/off option on page 3, so the hard edge stays available.

The fast-knob crackle the owner heard on sharp tables (POS stepping once per block) is
a separate fix: POS smoothing, or POS interpolated sample by sample. It stays with
M10b-2's glide and is not decided yet.

# M10b-2: SYNC, MOVE locked to the tempo

Each oscillator's MOVE can follow the project tempo and start its cycle on step 1. Page 3's
E and F are SYN1 and SYN2, Off or On.

## The controls

| control | record | slot | why this record |
|---|---|---|---|
| SYN1 | 248, Osc Mod | 37 | its default is 0, so every sound saved before SYNC reads Off |
| SYN2 | 260, Noise Character | 47 | the same |

The other three spare records (254 HOLD, 255 DEC, 258 WDTH) default to `0x7f00`, and every
Waverider sound saved so far holds that value. A control on them must read 127 as "off".
That rules them out for SYNC, and it decides how SMTH and DCLK work.

**RATE with SYNC on** keeps its 0..100 range, and plays one of 24 note lengths: 1/32 to 4 bars,
each also as a triplet and dotted (owner, 2026-10-06). The mapping picks the length closest to
RATE's own free cycle at 120 BPM (`live.SYNC_INDEX`), so a sound keeps about its speed when SYNC
turns on: RATE 50 is a second free and a half note synced. Straight lengths get 5 values of
RATE, dotted ones 3 and triplets 2. The header names the length ("Osc1 M.Rate=1 bar T"). With
SYNC off it shows the stock number.

## How it works

**The ColdFire** (`csrc/waverider/sync.c`, in the +Drive chunk; model `dnfw.waverider.songpos`)
writes the song position into every frame, at frame bytes 2644..2647 (unused in the tail):
- **The steps:** track 1's current and next step (`docs/sequencer-playhead.md`). Both 0 for 8
  frames in a row is STOP, which resets the position to step 1 and holds it there. A torn read
  shows them equal for one frame at most.
- **Between steps:** the frame's tempo (+0xd8, BPM x 120) summed each frame, against 2,700,000
  a sixteenth. It holds just short of the next step during a pause.
- **The scale:** 2^32 is 384 sixteenths, 24 bars. That is the least common multiple of every
  length, the triplets and the dotted ones included, so each length's phase is the position
  times a whole number `a << k` (a = 1, 3 or 9), exact in 32 bits, and continuous where the
  position wraps.

**The DSP** (`csrc/waverider/sharc/sync.asm`, sw `0x170000`; its table, a word per RATE, at DM
`0x2e0400`) is entered from `modulator.asm` in place of RATE's arithmetic. It reads SYNC
through the offset row's seventh word.
- **SYNC off:** back to the free RATE, untouched.
- **TRIG Free:** the phase becomes position x (a << k): the cycle starts on step 1 after every
  PLAY, and stays on the grid.
- **TRIG Retrig:** the step per block is tempo x (a << k) x 2^32 / (384 x 2,700,000), in
  float32: the length holds from each note, and the note itself is on a step.

**Limits:**
- Track 1's steps are the clock. With one length and one scale for the pattern, every track
  reads the same (measured). Per-track lengths and scales are not handled.
- A one-step pattern reads as stopped.
- A frame the loader replaces with a table chunk carries no new position, so a synced MOVE
  stands still for that block (0.7 ms, only while tables load).

## The gates

- `test/test_waverider_songpos.py`: the position's arithmetic, STOP, PLAY, a pause, a torn
  read, and sync.c's constants against the model.
- `scripts/sharc_waverider_m5.py`, four new runs, each bit-exact against `live.render_two`:
  Free (the phase equals position x 1152 for 1/32 T after every block, across the position's
  wrap), Retrig (a half note at 120 BPM steps 2^32 / 1500 a block), osc 2's own SYNC, and SYNC
  off with a position present (identical to the run without one). A check also confirms the
  DSP's frame copy holds the position and tempo the frames carried.
- The emulator (`waverider-sync1`): page 3 shows SYN1 and SYN2 as two segments; turning SYN1
  reads "Osc1 M.Sync=On"; RATE 47 then reads "Osc1 M.Rate=1 bar T", and "48%" with SYN1 off.
- The reference: `scripts/waverider_sync_preview.py` writes three WAVs with a click track. In
  the gate WAV, the level opens at PLAY and then every 250 ms (1/8 at 120 BPM).

# M10b-2: SMTH and DCLK

Page 3 is now complete, as the owner laid it out (2026-10-06):
- top row (the shared controls): PRST, TRIG, **DCLK**, -;
- bottom row (per oscillator): SYN1, SYN2, **SMT1**, **SMT2**.

**The records, and why 127 means "leave it alone".** These go on the three spare records whose
default is `0x7f00`: DCLK on 254 HOLD (slot 41), SMT1 on 255 DEC (42), SMT2 on 258 WDTH (45). Every
Waverider sound saved so far holds 127 there. So 127 must sound exactly as before SMTH and DCLK
existed:
- DCLK reads any value but 0 as On (its range is Off/On, default On);
- SMTH 127 is no glide, and lower values glide more slowly, like a cutoff for POS.

The header shows SMTH as the glide's time constant: 1000 ms at 0, halving every 14 steps, 2.0 ms at
126, and "Off" at 127. A SMTH whose 0 meant "sharp", as first planned, would have made every saved
sound glide at its slowest.

## SMTH, the glide (`smooth.asm`, sw `0x170300`)

The loop's store of the reader block's pos now goes through `wr_smooth`, after MOVE and the clamp.
Each block, per voice and oscillator:
- `s = s + (POS - s) x k[SMTH]`, in float32;
- k is from a 128-entry table at DM `0x2e0c00`;
- `k[127] = 1.0` exactly, so POS passes bit for bit;
- a note on the voice snaps s to POS.

The state is at DM `0x2e1100`. The page's wave still draws the unsmoothed position.

## DCLK, the crossfade (`dclk.asm`, sw `0x170400`)

**First built as a 1 ms offset declick.** At each block boundary, it added the difference between
what the old settings would have played and what the new ones did, decaying over 1 ms. The owner
heard that it helped but didn't fully solve the click. Measured (a scratch prototype, the Up Loop
test, energy above 6 kHz, where the table holds nothing at note 48):

| technique | click vs no declick | reset vs the rest of the cycle |
|---|---|---|
| none | 0 dB | +32 dB |
| offset, 1 ms (as first built) | -23.6 dB | +9.5 dB |
| offset, 5 / 20 / 100 ms | -22.8 / -22.6 / -22.6 dB | +10.5 dB at 100 ms |
| crossfade, 3 / 10 / 30 ms | -31.7 / -39.5 / -48.8 dB | +0.7 / -7 / -16 dB |
| switch at the oscillator's cycle start | -28.8 dB | +3.6 dB |
| POS per sample | -25.2 dB | +7.9 dB |
| POS glide, 2 / 5 ms | -7 / -11 dB | a "zip" instead |

The offset only joins up the *value*: the wave still changes shape between two samples, and a
longer decay does nothing for that. A true crossfade does. **Decided (owner, 2026-10-06):** the
crossfade, with its time as the control, from 1 to 100 ms (long ones are for expressive use).

**The control:**
- DCLK (HOLD, slot 41): 0 Off, 1..127 = 1..100 ms, x10 every 63 steps.
- A new or cleared sound starts at 31 = 3.0 ms, `live.DCLK_DEFAULT`. It reaches a cleared sound
  through `wr_range`'s default. In the emulator, CLEAR TRK PRESET on a Waverider track set slot 41
  to `0x1f00` while SMTH came back as the record's 127.
- Sounds saved before this build read 127, 100 ms (owner: fine).

**How it works:**
- **Detection:** `wr_dclk_pre` sits in the loop's reader call, per voice and oscillator. It compares
  the block's table, pos and gain with the last block's. A jump is another table, POS by more than
  2 frames, or the gain by more than 0.1. Smaller moves pass through untouched.
- **The fade:** on a jump, the last settings become the fade's old ones. While a fade lasts, the
- **A jump during a fade waits** (2026-10-07). The owner heard clicks with an LFO on TBL.
  - **Why:** a table change faster than the fade restarted it, so the old wave was cut off mid-fade. In the reference, TBL switching every block under DCLK 3 ms gave sample steps of 0.74, against the wave's own 0.11. Under 18 ms, every switching period shorter than the fade clicked.
  - **The fix:** while a fade runs, the new side holds the fade's target (the last block's table, pos and gain), and the next jump starts once the fade ends. A long DCLK therefore makes a fast TBL LFO step at the fade's pace.
  - **Measured in the reference:** no step larger than the wave's own, at any period, at 3 and 18 ms.
  - **Gates:** `scripts/sharc_waverider_dclk_hold.py` checks it bit for bit in the runner, and `test_dclk_holds_a_jump_until_the_fade_ends` checks the reference.
  oscillator is rendered twice into scratch buffers, new and old from the same phase and increment.
  It is mixed as `y = n + (o - n) x (left - i) / length`, linear, with the inverse from a table:
  the DSP has no divide. The mix replaces osc 1's output and is added for osc 2.
- **No fade under way:** the call goes straight to the reader as before, so a sound with nothing
  jumping is bit for bit unchanged.
- **Notes:** a note cancels a fade and starts none (PRST may have restarted the phase).
- **A new jump mid-fade** restarts the fade from the last settings.
- **The cost:** one more reader pass per oscillator, only during a fade.

**The page's value text** for RATE (synced), SMTH and DCLK comes from C formatters. `wr_fmt` calls
the pair's function when its count is negative. That replaced three name tables, 357 pointers,
which no longer fit below `0x46710000`.

## The gates

- `test/test_waverider_dclk.py`:
  - SMTH 127 is exact;
  - SMTH glides, and a note snaps it;
  - an unchanged block is untouched by DCLK;
  - a POS jump ramps in from where the old frame would have gone on.
- `scripts/sharc_waverider_m5.py`, five runs with a POS jump at block 3 and no note (and one without it), each
  bit-exact against `live.render_two`:
  - SMTH 127 jumps;
  - SMTH 60 glides and stays below the target;
  - DCLK 3 ms: identical to Off before the jump, its first sample still the old frame's, and
    bit-identical to Off from 144 samples on;
  - DCLK Off is the control.

  The other runs carry the frame's DCLK 127 (100 ms), so any jump in them crossfades, and all stay bit-exact.
- The emulator: page 3's layout and "Osc1 Smooth=2.2 ms" at 124 (`waverider-sync2`); "Declick=17 ms"
  at 79, and CLEAR TRK PRESET giving DCLK 3 ms (`waverider-sync3`).

## On the instrument (`waverider-sync3-usbprobe`, 2026-10-06)

**The owner's five steps all passed:**
1. page 3, and DCLK 3.0 ms after CLEAR TRK PRESET;
2. SYNC: note names, gates on the eighths that follow the tempo, the first gate on step 1 after
   STOP + PLAY;
3. the reset click of an Up Loop, gone at 3 ms;
4. a 100 ms morph on a Square, hardening back to a hard switch at Off;
5. SMTH's glide, and Off as before.

The probe read `wr_sync` alive: 4,282 steps and 2 STOPs counted.

**The SHARC's load** (`tools/dn2sharc_load.py --idle`, 10 intervals each). Track 1 held one chord
with the same voices throughout; each pair differs only in the thing measured:

| state | load |
|---|---|
| Waverider, MOVE Up Loop on POS at RATE 70 (4 resets a second), DCLK Off | 53.6 % (53.5..53.7) |
| the same, DCLK 100 ms (each voice mid-fade about 40 % of the time) | 58.5 % (58.4..58.7) |
| factory WaveTone, the same chord | 57.1 % (57.1..57.2) |

- Waverider costs 3.5 points less than factory WaveTone.
- Even this harsh DCLK case costs 1.4 points more.
- At the 3 ms default a fade lasts 1/33 as long.

**Soak:** the 100 ms case, 10 minutes, 600 one-second intervals:
- the load stayed at 58.0..58.8 %, with no drift;
- 1,505..1,526 frames per interval, at 0.99..1.01 blocks a frame, symmetric (the interval edges;
  a lost frame would only pull it down);
- the instrument kept answering over USB throughout;
- the owner heard nothing wrong.

**The runner** (`scripts/sharc_waverider_stress.py`, 16 voices, instructions a block; the DCLK pair
differs only in DCLK): DCLK Off 231,338, 100 ms 308,010, factory WaveTone 293,546, FM Tone 331,212.
