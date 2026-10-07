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

## The scope's data

The samples come from the DSP, in the reply it sends the ColdFire every frame. Its free words are few (`docs/drive-load-command.md`: word 6 is load.asm's answer). A 96-point trace at 8 bits is 96 bytes. How often it can refresh, and what it costs the DSP, is the first thing to measure on page 4.

## Prototype (2026-10-07, emulator; not flashed)

Branch `feature/waverider-pages34-ui`, build `out/wt128/waverider-pages34b-usbprobe`. The screens only:

- **Four SYN pages.** The SYN key steps "Waverider (1/4)" to "(4/4)" and back to 1.
  - **Page 3:** SUB, OCT, WAVE, SRC / NOIS, TYPE, COLR, DEC on records 227..234.
  - **Page 4:** the options that were page 3, unchanged.
- **Page 3's controls turn and store** in their slots 50..57. The knob turn takes the page's records directly, without the per-type list.
- **The header names them in Waverider's terms:** "Sub Octave=-2", "Noise Type=DIG", "Sub Level=74", "Noise Colour=-10", "Noise Decay=74". SUB and NOIS read 0..127, COLR -64..+63, DEC 0..126 then Inf, and OCT, WAVE, SRC and TYPE by name.
- **Room:** the pages chunk moved from `0x4670C000` to `0x4670A000` (RAM above BSS, clear of every declared range; bootscreen's stamp ends at `0x46708140`), and the renderer to `LOAD + 0xB00`. The assembly is 2,662 B, the renderer 14,044 B.

**Not yet:**
- the sound, on the DSP;
- p-locks and LFO destinations for the eight (the hook at `0x400dc02a`);
- a new sound's defaults for them;
- the oscilloscope;
- the middle strips of the chosen layouts (both pages draw oscillator 1's wave meanwhile).
