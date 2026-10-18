# Waverider: knob travel for the short lists (2026-10-18)

The owner, 2026-10-17: "Page 5 type and any other short selection param has to have a generous range to effect a change." The fix copies what stock does for its own short lists.

## How stock moves a value

1. The encoder filter `0x4011336e` turns raw encoder counts into units. It swallows the first counts after the knob rests.
2. The SYN page's encoder handler (`0x400674d6`) asks `0x400c2418(id)` for the record's knob descriptor, 68 bytes at `0x4243325c + 68 id`.
3. The handler scales the counts with the descriptor (`0x4011313e`: word `+4`, or word `+8` while the knob is pushed). It gives the filter the 28 bytes the descriptor's word `+16` points to.
4. The parameter set's turn (`0x40036adc`) adds the result to the value and clamps it.

The descriptor sets the travel. Stock's short lists, for example FM Tone's ALGO and WaveTone's WAV and PRST, have one kind of descriptor. Its 0..127 controls have another.

## Measured

Panel driver, 40 turns of 10 counts each, logging the turn's inputs at `0x40036af4`:

| Build, track, control | Moves | Units |
|---|---|---|
| stock, FM Tone, ALGO (record 200, 8 values) | 15 | 15 |
| stock, FM Tone, A Env Attack (record 212, 0..127) | 37 | 111 |
| midicc3, Waverider, TYPE (record 235, 4 values) | 37 | 111 |
| knob1, Waverider, TYPE | 15 | 15 |
| midicc3 and knob1, Waverider, FOLD (record 208) | 37 | 47.15 |
| knob1, FM Tone, KSA (record 235, 0..127) | 36 | 108 |

Waverider's short lists sit on records whose stock role is a 0..127 control. TYPE is FM Tone's KSA, so it had KSA's travel and jumped to its last value in about two moves.

## The change

`wr_knob_desc` replaces the handler's `jsr 0x400c2418` at `0x40067574`. On a Waverider track, a record in `pages.SHORT_LISTS` gets ALGO's descriptor. Every other record, and every other track, gets its own.

The short lists are the named lists (`pages.VALUE_NAMES`) and PRST:

- TYPE (page 5),
- OCT, WAVE, SRC and the noise TYPE (page 3),
- MOVE1, MOVE2, TRIG, PRST, SYN1 and SYN2.

TBL1 and TBL2 keep their own travel, because the pool holds up to 130 tables.

## Not covered

- The measurements are in the emulator. Whether a count there equals one on the unit's smooth encoders is not measured. The ratio to stock is the same on both, because the code is stock's.
- A pushed knob uses ALGO's pushed step too. The emulator run did not measure it.
