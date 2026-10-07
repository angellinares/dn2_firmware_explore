# Waverider's pages 3 and 4: the sub-oscillator, the noise, and the options with a scope

**The owner's plan (2026-10-07):**
- a fourth SYN page takes today's page 3 options and an oscilloscope;
- page 3 becomes the sub-oscillator and a noise generator, sharing one page.

Layouts are in review: https://claude.ai/artifact/42jRjbDAnT2MKYKLRHFWPJ (three for each page).

## Where eight new controls can be stored

**Measured 2026-10-07, emulator, stock 1.11 after boot:** each machine type's parameter list is a RAM table at `0x42c64d18`. It holds 40 record ids per type, for sound slots 25..64, and 0 where the type has none. `param_set_slot_to_id(slot, type, filter)` (`0x400dc02a`) reads it for types 0..4, so every per-machine list does: the p-lock list, the LFO destinations, the CC map.

| type | machine | records | slots used | free slots |
|---|---|---|---|---|
| 0 | FM Tone | 200..237 | 38 | 34, 49 |
| 1 | WaveTone (Waverider's records) | 238..262 | 25 (25..49) | **50..64** |
| 2 | (the next machine) | 263..291 | 30 | 55..64 |
| 3 | (FM Drum?) | 293..299 | 8 | 33..64 |
| 4 | (no slots) | none | 0 | 25..64 |

**What Waverider uses:**
- 23 of WaveTone's 25 records (238..260, slots 25..47);
- the other two are WaveTone's master tuning, 261 MAST (slot 48) and 262 FINE (slot 49), so they're not free.

**What's free for a WaveTone-type sound:** slots **50..64**, 15 of them.
- **They reach the DSP:** the control frame carries every track's parameter indices 25..99, all but 93 and 94 (`dnfw.waverider.frame`), so a value in slot 50..57 arrives with the voice's other parameters.
- **They're saved:** the sound object stores every slot, so a value there saves and loads with the sound.

**The candidate: borrow FM Tone's records 227..234, which sit in slots 50..57, eight in a row.**
- Waverider already renames WaveTone's records on a Waverider track: their labels, long names, ranges and value text (`wr_label`, `wr_long`, `wr_range`, `wr_fmt`). The borrowed eight would get the same treatment.
- Through those records, p-locks, LFO destinations and CC come from the stock code.

| record | its FM Tone name | slot | Waverider's (proposed) |
|---|---|---|---|
| 227 | Pitch All | 50 | SUB, the sub level |
| 228 | Pitch A and B2 | 51 | OCT |
| 229 | Ratio All | 52 | WAVE |
| 230 | AB Level | 53 | SRC |
| 231 | AB Attack | 54 | NOIS, the noise level |
| 232 | AB Decay | 55 | TYPE |
| 233 | AB End | 56 | COLR |
| 234 | AB Delay | 57 | DEC |

**What it needs:**
1. **A hook at `0x400dc02a`'s entry:** on a Waverider track, slots 50..57 answer these ids. WaveTone's row stays as it is, so a real WaveTone track gains nothing. The DT2 machine-port work used the same entry (`docs/dt2-machine-port.md`, row 5).
2. **Their defaults for a new Waverider sound,** where CLEAR TRK PRESET already sets Waverider's (`events.c`).
3. **The DSP reading slots 50..57** for a Waverider voice (`sharc/`), and the sound they make: the sub and the noise, per voice.

**Not yet known:**
- whether anything else lists parameters per type outside this table (to find with a watch on the table's reads);
- whether FM Tone's records carry flags that matter here: their scale, and whether a CC is assigned.

## The scope's data (first note)

The samples come from the DSP, in the reply it sends the ColdFire every frame. Its free words are few (`docs/drive-load-command.md`: word 6 is load.asm's answer). A 96-point trace at 8 bits is 96 bytes. How often it can refresh, and what it costs the DSP, is the first thing to measure on page 4.

## Prototype (2026-10-07, emulator; not flashed)

Branch `feature/waverider-pages34-ui`, build `out/wt128/waverider-pages34b-usbprobe`. The screens only:

- **Four SYN pages.** The SYN key steps "Waverider (1/4)" to "(4/4)" and back to 1.
  - **Page 3:** SUB, OCT, WAVE, SRC / NOIS, TYPE, COLR, DEC on records 227..234.
  - **Page 4:** the options that were page 3, unchanged.
- **Page 3's controls turn and store** in their slots 50..57. The knob turn takes the page's records directly, without the per-type list.
- **The header names them in Waverider's terms:** "Sub Octave=-2", "Noise Type=DIG", "Sub Level=74", "Noise Colour=-10", "Noise Decay=74". SUB and NOIS read 0..127, COLR -64..+63, DEC 0..126 then Inf, and OCT, WAVE, SRC and TYPE by name.
- **Room:** the pages chunk moved from `0x4670C000` to `0x4670A000` (RAM above BSS, clear of every declared range; bootscreen's stamp ends at `0x46708140`), and the renderer to `LOAD + 0xB00`. The assembly is 2,662 B, the renderer 14,044 B.

- **The per-type list (`wr_slot_id` at `0x400dc02a`):** slots 50..57 of a Waverider sound answer records 227..234. A Waverider sound is type 5, or type 1 on a Waverider track, since the UI reports it as WaveTone. Every other answer is stock's; the hook chains with the type-5 shim at `0x400dc032`.
  - **Emulator:** the LFO destination list on a Waverider track offers Sub Level, Sub Octave, Sub Wave, Sub Source, Noise Level, Noise Type, Noise Colour and Noise Decay, in their own SYN group before the oscillators', ordered by record id.
  - **The control:** on a WaveTone track the list is stock's (Osc1 Tune, Osc1 Waveform, Osc1 Phase Dist...), none of the eight.

## The sub-oscillator on the DSP (2026-10-07, SHARC runner; not flashed)

**`csrc/waverider/sharc/sub.asm`**, at sw `0x171000` (DM `0x2e2000`), with 16 phases and three scratch words at DM `0x2e2400`, in L1 block 1's free tail after DCLK's state.
- **Where it runs:** machine9_live.asm's two exits for a type-5 track whose oscillators are done now go to it: `wr_sub_ran` (osc 2 ran) and `wr_sub_skip` (osc 2 skipped at LEV2 0). Then it goes on to `wr_t5v_next`.
- **What it reads:** SUB, OCT, WAVE and SRC (params 50..53) from the frame copy at `0x25c48c + 268 + 146t`, four half-words.
- **What it does:** with SUB above 0, it adds SUB/100 × shape(phase) into the track buffer the oscillators wrote. Its phase steps at the followed oscillator's increment >> (1 + OCT). That's osc 2's reader block when SRC is 1 and osc 2 ran, else osc 1's.
- **The shapes:** SIN is two parabolas; TRI; SQR; PLS a 25 % pulse at +1 / −1/3, so no DC. All are float32 arithmetic `live.sub_value` mirrors, and need no table.
- **Instruction forms:** as reader_m9.asm's. Two constants are written signed (`-0x41555555` for f32(−1/3)), as dclk.asm does, so the decoders' texts agree.

**The gate: `scripts/sharc_waverider_sub.py`, 5/5 bit for bit against `live.render_two` with the sub:**
- the control, SUB 0: the reference without a sub;
- SIN, −1 octave, following osc 1;
- TRI, −2;
- SQR following osc 2 a fifth up;
- PLS with SRC OSC2 while osc 2 is off, which follows osc 1.

The sub changes 255..256 of 256 samples in every case it's on. It writes `out/waverider/sub_*.wav`.

**Not yet:**
- the sub on the instrument, and its DSP load against the factory machines (the perf gate);
- p-locks for the eight, tried on the instrument (they go through the same list);
- the destinations' order: the eight come first, in a group of their own;
- a new sound's defaults for them;
- the oscilloscope;
- the middle strips of the chosen layouts (both pages draw oscillator 1's wave meanwhile).

## The noise on the DSP (2026-10-07, SHARC runner; not flashed)

**`csrc/waverider/sharc/noise.asm`**, at sw `0x171300` (DM `0x2e2600`). sub.asm's exits now go to it instead of `wr_t5v_next`, including the SUB 0 one, so the chain is oscillators, then the sub, then the noise, then the next track.

**What it reads:** NOIS, TYPE, COLR and DEC (params 54..57) at `0x25c48c + 276 + 146t`, the same half-word pattern as the sub's. It also reads the frame's note mask (offset 34, bit t).

**What it does, per sample, in float32, as `live.NoiseVoice` does:**
- **The generator:** xorshift32 (<< 13, >> 17, << 5); w = x as a signed int × 2^-31.
- **TYPE:**
  - WHT is w;
  - PNK is P. Kellet's economy filter (three one-poles plus w × 0.1848, × 0.25);
  - BRN is a leaky integrator, 0.98 b + 0.15 w;
  - DIG is ±0.5 by the generator's top bit.
- **COLR:** a one-pole low-pass lp (coefficient 0.125, about 1 kHz), and out = n − c × lp, with c = (COLR − 64) / 64. So +63 is close to a high-pass and −64 boosts the lows.
- **DEC:** a note on the voice restarts the envelope at 1.0, whatever NOIS is. Then each sample is y × env, and env × the table's factor (5 ms at 0, 10 s at 126, `live.noise_decay_table`). Inf (127) skips the envelope. At boot env is 0, so with a finite DEC the noise is silent until the first note.
- **The gain:** NOIS/100, as the sub's; the result adds into the track buffer.

**State:** 16 voices × 32 B at DM `0x2e2e00`: x, three pink filters, brown, lp, env. The image seeds each x (`live.noise_seeds`: odd, distinct, never xorshift's fixed point 0). The decay table is at `0x2e2c00`.

**The gate: `scripts/sharc_waverider_noise.py`, 5/5 bit for bit against `live.render_two(noises=...)`:**
- the control, NOIS 0, is the reference without noise;
- WHT at COLR 0, DEC Inf;
- PNK at COLR −64;
- BRN at COLR +63, DEC 40: silent until the note at block 1;
- DIG at DEC 0 with the sub on.

The noise changes 224..256 of 256 samples in every case it's on. Rerun after the change: `sharc_waverider_sub.py` still 5/5. The runner renders 8 blocks, so the gate also writes `out/waverider/noise_reference_tour.wav`: 6 s of the matched reference, each type with two notes, then the tilt both ways.

**Levels:** at NOIS 100, RMS WHT 0.58, PNK 0.43, BRN about 0.46, DIG 0.5. With COLR −64 the peak can exceed 1, as two oscillators at 100 already can.

## Page 3's screen (2026-10-07, emulator)

**The owner's pick:** layout A without the sub's wave, the four sub controls as full-size stock cells, two by two in the left half, the noise picture on the right, and the noise controls on the bottom row.

**Measured on stock FM Tone (emulator):** a cell is 26 px wide, with a 17 px knob and its label under it, on a 27 px row pitch. Two rows of cells fill y 13..63. Two cells stacked therefore run into the bottom row the noise keeps (canvas y 1..10), and in a 2×2, WAVE and SRC sit over encoders E and F, which turn NOIS and TYPE.

**What the screen does:**
- **The stock cell, called directly:** the grid `0x40017428` calls `view->vtable[180](view, canvas, x, y, id, value, a, locked, held, 0, 0)` per cell. Its arguments:
  - x = 24 + 26 col;
  - y = 27 for the top row, 0 for the bottom;
  - a = `0x40113346(view + 148, cell)`;
  - locked is the value getter's flag;
  - held is 1 when locked, else `0x40113558(view + 148, cell)`.

  `page.c` (`stock_cell`) makes the same call for records 227..230, which gives stock knobs with Waverider's labels (SUB, OCT, WAVE, SRC: wr_label answers).
- **Two layouts built** (`SUB_LAYOUT` in page.c), both framed in the emulator:
  - **3, the default:** the four cells as a stock grid row over A..D, the noise field a strip under them (x 24..121), the noise's four on the bottom row over E..H. Every cell sits over its encoder.
  - **1, the 2×2 as picked:** the field top right with "NOISE" over it, and the noise's four two by two below it. It's cramped, and the cells don't sit over their encoders.
- **The noise glyph** (`noise_field`), a short trace of the noise's own generator. It replaced a field of seeded dots on 2026-10-07: measured in the emulator, the dots told NOIS and DEC apart but not TYPE or COLR. At COLR −64 every type lit the same 484 pixels. PNK and BRN only looked like WHT turned down, and COLR read only as density, the wrong way for loudness: a brighter PNK or BRN is 10..16 dB quieter.
  - **What it draws:** the DSP's steps (`live.NoiseVoice`: xorshift32, TYPE's filter, COLR's tilt, NOIS's gain) in Q16 integers, one sample a column after 256 samples of warm-up, from a fixed seed so it stands still. Full scale is 4 px, clipped to the strip.
  - **How it reads:** WHT is jagged, PNK wanders, BRN drifts slowly and DIG steps between two levels. A brighter COLR flattens PNK and BRN, as their level falls. DEC is the trace's outline: column x is x / 98 s after the note (`noise_env.h`, generated by `scripts/gen_noise_env.py`), so the decay shows at DEC's own time constant, and DEC 90 still visibly shrinks.
  - **The mirror:** `dnfw.waverider.noise_glyph` does the same integer steps. Its samples are within 0.002 of the reference's (peak 1.5), and its spectrum per TYPE × COLR is within 0.3 % in centroid and 0.1 dB in level. It predicts every pixel of the strip: 30 of 30 emulator frames match (the TYPE × COLR grid, a DEC row, a NOIS row). The control, the same check against altered settings, fails on all 23 altered frames (`test/test_waverider_noise_glyph.py`).
  - **Weak spot:** COLR on WHT and DIG barely changes the trace. The tilt is a gentle shelf around 1 kHz, and the sound changes little too (centroid 10.7 → 12.8 kHz).
  - In layout 1 the strip is 42 columns, so it shows the first 0.43 s.
  - **The sub joins it** with SUB above 0 (owner, 2026-10-07). It's drawn at its own scale: WAVE's shape (`live.sub_value` in Q16), SUB's height, and OCT as cycles across the strip (−1 oct two, −2 one). The pitch it follows (SRC) isn't drawn. `SUB_GLYPH` picks the layering, and both are built for the owner to compare on the instrument:
    - **3, the default (`p3subdot1`):** the sub solid, with the noise dotted on every other column under it.
    - **4 (`p3subsum1`):** one line, the sum, as the track adds the two.

    The mirror's `strip` predicts both: 25 of 25 emulator strips each, over WAVE × OCT by TYPE, with SUB 0 and NOIS 0 rows. As a control, each build's frames checked against the other's rule match only the 5 with SUB 0, where the two rules coincide.

**Layout 4, labels and bars (the default since 2026-10-07):** the owner, on `p3subdot2`: the knobs at the top looked odd and took the waveform's room, and OCT, WAVE and SRC barely moved from the left across all their values (a stock knob draws a few-valued record near its minimum).
- Page 3 now has the oscillator pages' layout: both rows are labels with bars. OCT, WAVE and SRC are segmented bars, one segment per value, as TYPE already was. The stock cells (`stock_cell`) remain only for `SUB_LAYOUT` 1 and 3.
- The strip takes the wave's place: x 24..121, y 15..39, full scale 10 px (`noise_glyph.LAYOUT4`).
- Emulator, builds `p3bardot1` / `p3barsum1`: 25 of 25 strips match the mirror for each `SUB_GLYPH`. As a control, each build's frames against the other glyph's rule match only the 5 with SUB 0, and the OCT −3 frame doesn't match the −2 rule.

**OCT −3 (owner, 2026-10-07):** OCT is −1, −2, −3 (`live.SUB_OCTAVES`).
- On the DSP, sub.asm clamps OCT at 2 (was 1), so the step is the followed increment >> (1 + OCT).
- `sharc_waverider_sub.py` passes 7 of 7 bit for bit. The new cases are SIN at −3, and OCT 3, which the DSP clamps to −3. `out/waverider/sub_sin__oct__3.wav` is the −3 case.
- **The strip's cycles changed with it:** −1 four, −2 two, −3 one (until now −1 two, −2 one), so each shape shows whole at every octave.

**The strip as reusable modules (owner, 2026-10-07: new code in parts any machine can reuse):**
- `csrc/synth/`: `fixq16.h` (Q16 multiply and level), `noise_q16` (the generator), `sub_q16` (the shapes).
- `csrc/ui/`: `canvas.h` (pixels), `noise_strip` (the strip, from plain values and a box), and `noise_env.h`.
- `page.c` only reads page 3's eight values and calls `noise_strip_draw`.
- `cpage.MODULES` compiles them beside page.c. `test/test_csrc_modules.py` fails if anything in `synth/` or `ui/` includes a machine's headers or names a Waverider symbol.
- The rest of `page.c` hasn't been split yet.

**Open:**
- the owner's choice between `SUB_GLYPH` 3 and 4, now on layout 4;
- the defaults after CLEAR TRK PRESET for slots 50..57, which come from `wr_range` (SUB, NOIS 0; COLR centred; DEC Inf) and aren't checked yet.

## What the sub and the noise cost (2026-10-07, SHARC runner)

`scripts/sharc_waverider_p3_cost.py` puts Waverider on track 0 (osc 1, a note at block 1) and MIDI on the others, and runs 4 blocks. Each case differs from the control in one thing. These are instructions, not cycles; our code runs from L1, where the two are close.

| case | per voice and block | × 16 voices, share of a frame |
|---|---|---|
| sub SIN | +742 | 1.8 % |
| noise WHT, DEC Inf | +905 | 2.2 % |
| noise PNK, DEC 40 (the longest path) | +2,022 | 4.9 % |
| both | +2,764 | 6.6 % |

- **The two add up:** 742 + 2,022 = 2,764, with nothing shared.
- **The 16-voice column is an extrapolation:** the per-voice figure × 16, over the 666,667 cycles of a frame. It isn't a run.
- **Against the factory machines** (`docs/sharc-load.md`): an idle FM Tone track costs +11,113 instructions a block over MIDI, and WaveTone +8,177. A Waverider voice with both on is about 1,825 + 2,764.
- **Still owed for the perf gate:** the instrument's load (`tools/dn2sharc_load.py --idle`) and a soak, against factory WaveTone with the same chord.

## The scope's data: what the reply carries (2026-10-07)

- **The reply already holds per-track audio:** 32 records of 84 B (`+0x1c..+0xa9c`), read as 28 channels of 24 bits per sample. On the instrument they change with a held note (`docs/for-digikit-coldfire-sharc-link.md` §8).
- **If one channel is a track's own output, page 4's scope needs no DSP change.** The ColdFire's frame hook would keep the shown track's samples in a ring, and the page would draw from a rising zero crossing.
- **The runner can't say which channel it is.** After 6 blocks with a note on track 0 (`scripts/sharc_reply_channels.py`, peak 0.09 in the track buffer), every record on both reply pages is 0. The records are filled outside the render call the runner emulates.
- **The mapping needs the instrument:** PEEK the reply at `0x800053a4` while a single track plays, a different track each time, and correlate the 28 channels.

## The reply's audio records, mapped on the instrument (2026-10-07)

Measured with the USB probe on `p3subdot2`/`p3subsum2`-era firmware (`tools/dn2reply_audio.py`, read-only PEEK of the 32 records × 84 B at `0x800053a4 + 0x1c`; each record 28 channels of 24 bits). One note held at a time, 10–20 readings each. Readings saved in `out/reply-audio/`.

| Held | Channels with signal |
|---|---|
| nothing (control) | 26/27 only, RMS ≈ 17: idle noise in every state |
| track 9, Waverider, unison 2 voices (×3, the last a positive control after the track 6 runs) | 4/5 strong (RMS 490k..704k), 20–25 weaker |
| track 9, unison off | 4/5 at about half (313k, L ≈ R), 20–25 halved |
| track 10 (effects on) | 6/7 (panned right: 192k / 731k), 20–25 |
| track 16 | 18/19 (556k, L = R); 20/21 ≈ 1 |
| track 6, FM Tone default, audible (×2) | nothing |
| track 6, Waverider (×1) | nothing |

**The layout:**
- **Channels 0–19 are tracks 7–16, one stereo pair each:** track t on 2(t − 7) and 2(t − 7) + 1. Three points (9, 10, 16) fit, and 16 was predicted before it was read.
- **20–25: three stereo buses,** most likely the effects (they follow the sends: strong for tracks 9 and 10, about 1 for track 16).
- **26–27: idle noise,** never silent, never louder.
- **Tracks 1–6 are not in this record.** The control (track 9 again, after the track 6 runs) lit as before, so the read worked.

**Repeated on a clean project (CREATE NEW, stock sounds):** tracks 1 and 2 nothing; track 7 on channels 0/1 (548k, L = R), as predicted, so the block starts at track 7. The ColdFire receives both reply pages into the one buffer at `0x800053a4`, alternately, so a page carrying tracks 1–6 would have shown in about half the readings: none of 80 did. Tracks 1–6 travel by another route, still to find.

**Tracks 1–6 ride the other link: the SSI0 TDM stream** (2026-10-07, the same session, `tools/dn2tdm_audio.py`). The ColdFire receives the SHARC's SSI0 stream into the double-buffered window at `0x4E6DF100` (eDMA 48; `docs/audio-dma.md`): 2 × 32 frames of 64 bytes, 16 longword slots each. The stock engine hands that window and the reply records (`0x800053c0`) to the same routine, `0x40138460`.

| Held | SSI0 slots with signal |
|---|---|
| nothing (control) | none, all 16 zero |
| track 1 | 0/1, 2/3 |
| track 9 (whose audio is in the reply records) | 0/1 only |
| track 2 | 0/1, 4/5 (predicted) |
| track 6 | 0/1, 12/13 (predicted) |

- **Slots 0/1: the main mix**, which every track reaches.
- **Slots 2..13: tracks 1–6, one pair each:** track t on slots 2t and 2t + 1.
- **Slots 14/15:** zero in every state read.
- The levels read about 250× lower than the reply's when each longword is taken as a left-justified 24-bit sample, so the slot format (likely right-justified) is still to settle. For a scope only the shape matters.

**So every track reaches the ColdFire:** tracks 1–6 in SSI0 slots 2t / 2t + 1, tracks 7–16 in the reply records' channels 2(t − 7) / 2(t − 7) + 1, and the main mix in SSI0 slots 0/1.

**For page 4's scope:** no DSP change for any track. The ColdFire keeps the shown track's samples in a ring from whichever link carries it, and the page draws them from a rising zero crossing.

## Page 4's scope (built 2026-10-08, emulator; not on the instrument)

**What it shows:** the active track's own sound, in the wave's place on page 4 (the owner's option A): triggered on a rising zero crossing, so a steady tone stands still; scaled to its own peak, so it shows the shape, not the level; each column the min..max of its 8 samples, so a high note reads as a band instead of aliasing. The strip spans 98 columns, 16 ms at 48 kHz. Silence draws the centre line.

**The modules (reusable, owner 2026-10-07):**
- `csrc/dn2/audio_tap`: a track's last 32 samples as int16, mono (L + R) / 2: tracks 1..6 from the SSI0 window (the half the stock ISR's rule picks, `0x400d0f98`: 1 while eDMA 50's source is below `0x4E6E0900`), 7..16 from the reply records. The OS addresses are in `dn2_111.h`.
- `csrc/ui/trace_ring.h`: a 2,048-sample ring, one writer (the ISR), readers looking back from its write count.
- `csrc/ui/scope`: the trigger, the scaling and the drawing, in a `ui/box.h` box (shared with the noise strip).
- Waverider's glue: `csrc/waverider/scope_feed.c` (in the drive chunk, called from `wr_frame_src` every frame) feeds the ring from `wr_events.scope_track`, which page.c sets to the active track on page 4 and to 0xFF on any other page. While page 4 is shown, `wr_poll` asks for a redraw every frame tick (at most 24 a second, the panel's rate).

**Checked:**
- **Drawing:** samples poked into the ring (the emulator runs no audio ISR, so they stay), frames against `dnfw.waverider.scope_glyph`: 5 of 5 pixel for pixel (two sines, a saw, a high note, a square, silence); against the other cases' predictions, 0 of 20 match. The page names track 1 (index 0) to capture.
- **Capture:** `dn2_track_block` called directly in the ui1200M snapshot (WSL `~/dn2-emu-venv`) with injected link memory: 32 of 32 blocks as expected (16 tracks, both SSI0 halves); the half the rule doesn't pick never matches; an out-of-range track returns 0.
- **Not checkable in the emulator:** the audio frame function (`0x40025e0a`) never runs there (0 hits), so the ISR feeding the ring, the half rule's timing, and the SSI0 sample format are for the instrument.

**Cost:** the ISR reads 32 samples and writes 32 a frame, while a track is named (from page 4 until another SYN page is drawn). The drive chunk grew 4.4 KB (the ring), 25 KB of its 64 KB still free.
