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
