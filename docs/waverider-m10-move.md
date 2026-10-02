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
