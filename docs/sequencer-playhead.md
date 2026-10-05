# The sequencer's playhead on DN2 1.11 (instrument, 2026-10-05/06)

Found for Waverider's SYNC (M10b-2: MOVE locked to the steps), by measurement on the
instrument over the USB probe. Everything here is [M]: measured on silicon, with the
note-on counter (`csrc/waverider/events.c`) as the reference for step 1.

## What is where

| address | what | notes |
|---|---|---|
| **`0x446483d0 + t`** | **track t's current step**, a byte, 0 = step 1 | 16 bytes, one per track |
| `0x446483e0 + t` | track t's next step | one ahead of the current step |
| `0x42c5aacd..`, `0x42c5a91c` | more copies of the step, 0..7 on an 8-step pattern | not yet identified |
| `0x42c5a9d0`, `0x4463ed14` | a step count, u32, 1 per step | grows while playing |
| `0x4058f198` | a 32nd-note clock in a 4/4 bar, 0..31 | **not** the playhead: see below |
| `0x4058f39c` | a 16th-note clock over two bars, 0..31 | likewise |

**The checks on `0x446483d0`:**
- **Step 1:** on an 8-step pattern with one trig, on step 1, the step wrapped from 7 to 0 exactly when that trig's note played. That held in all 40 timed readings and at all 12 wraps (`out/probe-frames/sweep.pkl`).
- **STOP and PLAY:** STOP on step 5 set it to 0 (step 1) and held it there. PLAY started from 0, with the note (`out/probe-frames/playhead_stopplay.json`).
- **Length:** it wraps at the pattern's length (8 here). All 16 tracks read the same with one length for the pattern; per-track lengths are not yet measured.

## What looked like it and wasn't

- **`0x4058f198` / `0x4058f39c`, the bar clocks:** they move in 32nds and 16ths, and freeze with a pause. But they wrap every bar whatever the pattern's length (8 or 16 steps), and they are **not reset by STOP and PLAY**. After a restart the pattern was on step 1 while the clock carried on from 29. Once, while the pattern played, the 32nd clock also stood still. So they are a beat grid, not the pattern's position.
- **`0x405cce5c` / `0x405c58d0`:** 30 a second on the instrument and in the emulator alike, the 120 Hz UI tick divided by 4. A UI timer.
- **The emulator:** it runs no audio interrupt, and its sequencer clock never moves. The step counters can only be measured on the instrument.

## How it was found, for 1.12 (`os-112-support`)

These are 1.11's addresses. To find them again:
1. `tools/dn2memsweep.py changed`: two passes over the whole SDRAM (7 min each), keeping the 1 KB chunks that change. Here that was 103 chunks, 0.1 MB of 128 MB.
2. `tools/dn2memsweep.py focus`: timed passes over just those chunks, with the step-rate test, while an 8-step pattern with a trig on step 1 plays at a known tempo. The note-on counter marks step 1.

`tools/dn2stepscan.py` does the step-rate test over one range. Scanning only the static data (`0x4030b980..0x40600000`), the kit and pattern area (`0x42000000..0x42500000`) and the SRAM missed the playhead: it lives at `0x4464xxxx`.
