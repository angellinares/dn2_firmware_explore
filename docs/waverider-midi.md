# Waverider: MIDI CC and NRPN (2026-10-18)

On a Waverider track, no knob CC or NRPN reached the sound. The owner found this while measuring the load: NRPN 1:77 changed nothing. The emulator shows the same on the formant2 build. This page says why, and what the mod does now.

## Why stock ignored them

- The incoming CC goes to the track's vtable +108 (`0x40038a8a`). That routine asks `0x400dc814(track, type, filter, cc)` for the parameter record. NRPN goes through vtable +104 (`0x40037456`) and `0x400dc8f6`.
- The machine type comes from the track's vtable +116 (`0x40036462`), which reads the sound's byte `+0xDE`. On a Waverider track that byte is 5.
- The lookup tests the type: 4 is MIDI, 0 to 3 read the machine's map, and anything above 4 skips to the filter and the sound maps.
- The machine maps are `std::map`s, 24 bytes a type: CC at `0x42c66a84`, NRPN at `0x42c66a0c`. The builder `0x400dc4d0` fills them from each record's `+0x18` (CC) and `+0x1c` (NRPN), for page ids 0 to 4 only.

Stock numbers a machine's knobs by place, not by parameter (DN2 manual, Appendix C):

| SYN page | CC | NRPN |
|---|---|---|
| 1 | 40 to 47 | 1:73 to 1:80 |
| 2 | 48 to 55 | 1:81 to 1:88 |
| 3 | 56 to 63 | 1:89 to 1:96 |
| 4 | 70 to 77 | 1:97 to 1:104 |

Waverider's pages hold WaveTone's records in its own order, and FM Tone's records on pages 3 and 5. A map by machine type cannot give them the numbers of their places.

## What the mod does

| Part | Where | What |
|---|---|---|
| Two bus events | `dnfw.mods.bus`: `ev_param_cc` at `0x400dc814`, `ev_param_nrpn` at `0x400dc8f6` | the platform owns the lookups' entries. A handler answers a record id, or 0 for stock's lookup |
| `wr_cc_id`, `wr_nrpn_id` | Waverider's pages chunk | on a track of type 5, the record on that knob place of Waverider's pages. Anything else: 0 |
| `wr_set` | the synth track's vtable +52 (`0x401db830`) | marks the type of the track being set for the whole setter call |
| `wr_range` | the limits getter `0x400dbff0` | reads that mark first. Outside a setter it answers for the active track, as before |
| `wr_out_nrpn`, `wr_out_cc`, `wr_out_lsb` | the three getter calls in the parameter send `0x400379dc` | a Waverider knob sends the number of its place, so a recording plays back to the same knob |

Waverider's numbers (the owner, 2026-10-18: every parameter takes both CC and NRPN):

| Page | CC | NRPN |
|---|---|---|
| 1 to 4 | as stock | as stock |
| 5: FOLD WARP FM FSRC | 12, 15, 35, 36 | 1:112 to 1:115 |
| 5: TYPE AMT P1 P2 | 37, 83, 93, 119 | 1:116 to 1:119 |

- **NRPN 1:105 to 1:111 are not used:** stock uses 1:108 for Mute and 1:110 for Track level.
- **Page 5's CCs are not in a row:** a track's channel has no eight free CCs in a row.
- **Each page 5 CC is free in four ways:**
  - No stock record carries it.
  - The CC switch `0x40122c0c` has no case for it. Its cases are 1, 2, 6, 33, 34, 38, 64, 66, 94, 98, 99, 110, 120, 121 and 123.
  - It is not a trig CC (3, 4, 5, 13, 14) or Track level (95).
  - A DAW or a keyboard does not send it unasked. Those numbers are bank select (0, 32), volume (7), pan (10), expression (11), the pedals (67 to 69), data and RPN (96 to 101) and channel mode (120 to 127).
- **`test/test_waverider_midi.py`** checks the map against the stock image.

## The setter and the limits

The setter `0x40038e88` asks the limits getter more than once. On formant2 `wr_range` answered for the active track. That caused two errors:

- **A CC to a Waverider track that is not on the screen** clamped to the stock record's limits. TYPE (record 235) took up to 127 instead of 3.
- **A CC to a WaveTone track while a Waverider is on the screen** clamped to Waverider's limits. SYN1 (record 248) stopped at 1 instead of 3.

`wr_set` fixes both. Region A is not cleared at power-on, so the mark at `0x46A60000` is one of two exact words. Any other value means that no setter is running.

## Checked in the emulator

`scripts/emu_waverider_midi.py BUILD` restores `ui1200M` twice, once with stock (the control) and once with BUILD. It calls stock's receive routines with each track's own object:

- every CC from 0 to 127, at 0 and at 127,
- every NRPN on MSB 1 to 3, at the top value.

Each call starts from the same sounds. The script records what the setter queues at `0x400f5098` (the record id and the value word), and every write into the 16 sounds.

| Rule | midicc3 | formant2 (the negative control) |
|---|---|---|
| a Waverider track, a number in the map: exactly one record, the map's, in Waverider's limits | PASS: 582 messages | FAIL: 250 findings |
| a Waverider track, any other number: what stock queues | PASS | |
| a WaveTone track, in both set-ups: what stock queues | PASS: 1,280 answers | |
| every call: at most one record, no direct write into a sound | PASS | |

Stock is the control. It queues nothing for the map's numbers on a Waverider track, and it queues CC 40 on a WaveTone track. A Waverider track is the active track in one set-up and off the screen in the other.

The send getters, called with each track (`scratchpad` probe, midicc3):

| Record | Waverider track: NRPN / CC | WaveTone track: NRPN / CC |
|---|---|---|
| 238 TUNE | 201 / 40 | 201 / 40 |
| 241 LEV | 202 / 41 | 204 / 43 |
| 208 FOLD | 240 / 12 | 225 / 70 (FM Tone's own) |
| 235 TYPE | 244 / 37 | 230 / 75 (FM Tone's own) |
| 66, a filter record | 162 / 88 | 162 / 88 |

Not checked in the emulator:

- the MIDI bytes that go out (MIDI out is off in the snapshot),
- the sound changing after the queue (the task that applies it does not run in a direct call).

The test on the unit covers both.

## On the unit

1. MIDI channel 10 (the auto channel), track 1 is Waverider, page 1 on the screen.
2. Send CC 42 = 0, then 127. POS on page 1 goes to 0, then 127.
3. Send NRPN 1:116 with data MSB 1, LSB 0. Page 5's TYPE reads Ring. The setter takes the 14-bit value times 2, so 128 is `0x100`, the second type.
4. Select track 2 (WaveTone). Send CC 42 on track 1's own channel (channel 1 by default), not on the auto channel. Track 1's POS moves, and track 2 does not change.
5. With MIDI out set to CC, turn page 3's SUB. The computer receives CC 56.
