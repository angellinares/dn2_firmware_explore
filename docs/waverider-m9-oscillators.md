# Waverider M9: the level and the second oscillator

Milestone 9 gives Waverider WaveTone's two-oscillator shape: each oscillator has its own
tune, position, table and level, and the two are mixed into the track's buffer. Page 1
is OSC 1 (TUNE LEV POS TBL), page 2 is OSC 2 (DETN LEV POS TBL). The other four places
on each page stay "-" until M10.

Sources: `csrc/waverider/sharc/reader_m9.asm` and `machine9_live.asm` (the DSP);
`src/dnfw/waverider/pages.py` and `csrc/waverider/page.c` (the page). The M5 sources stay
beside them; `sharc_code.json` records which ones ship.

## The parameters

Every control is a WaveTone record, so p-locks, LFO destinations, CC and SAVE/LOAD are
WaveTone's own. The SHARC reads them from the frame copy the unpack makes at `0x25c48c`,
slot s of track t at `168 + 2s + 146t` (16-bit, little-endian):

| control | record | slot | frame offset | default |
|---|---|---|---|---|
| TUNE (osc 1) | 238 TUN1 | 25 | 218 + 146t | 0x4000 (0 st) |
| POS (osc 1) | 239 WAV1 | 26 | 220 + 146t | 0 |
| TBL (osc 1) | 247 TBL1 | 27 | 222 + 146t | 0 |
| LEV (osc 1) | 241 LEV1 | 30 | 228 + 146t | 0x6400 (100) |
| DETN (osc 2) | 242 TUN2 | 31 | 230 + 146t | 0x4000 |
| POS (osc 2) | 243 WAV2 | 32 | 232 + 146t | 0 |
| TBL (osc 2) | 251 TBL2 | 33 | 234 + 146t | 0 |
| LEV (osc 2) | 245 LEV2 | 36 | 240 + 146t | 0x6400 (100) |

Osc 2's four are osc 1's plus 12 bytes. 12 is 0 mod 4, so each one sits in the same half
of its 32-bit word as its osc-1 twin. The loop's half-word choices are therefore the same
for both oscillators, and only the base offset changes.

DETN is TUN2 at full range (±60 semitones, the same scale as TUNE). The name is the
owner's layout's.

## M9a: the level

The gain is LEV × f32(1/25600), computed in float32. That is exactly 1.0 at the default
100, so a default sound is bit-identical to M5's. It is 1.27 (+2.1 dB) at 127 and 0 at 0.
The loop writes it to DM `0x2de6c0` before each reader call, and the reader multiplies
every sample by it.

On the instrument (`waverider-m9a-usbprobe`, 2026-10-02): 100 sounded unchanged, turning
it down made the track quieter, 0 was silent, 127 was slightly louder; the header showed
the Osc1 long names; a WaveTone/FM control kept its stock names and sound.

## M9b: the second oscillator

**One body, run twice.** The loop's 1 KB span had 126 bytes left, so osc 2 cannot be a
copy of osc 1's code. Each type-5 track runs the per-oscillator body twice. The body is
everything from "t and the reader block" to the reader call. It is driven by three DM
words, set at the track's start (osc 1) and by `wr_t5v_osc_next` (osc 2):

| DM | osc 1 | osc 2 | |
|---|---|---|---|
| `0x2de6c4` | 0 | 1 | the reader replaces (0) or adds (1) |
| `0x2dde90` | 0 | 0x900 | reader-block offset: osc 2's blocks are `0x2de800 + 32t` |
| `0x2dde94` | 0 | 12 | frame offset |

The track buffer is kept at `0x2dde88`, because the reader clobbers R0–R15.

**Osc 2 adds, osc 1 replaces.** Osc 1 never reads the buffer, since the dispatch may leave
anything there, NaN included. Multiplying by 0 is not a way to clear it, because
NaN × 0 is NaN. So the reader tests `0x2de6c4` and branches: it either stores y or adds
the buffer's word to it. That is a load, a test, a branch and an add per sample, for osc
2 only.

**Osc 2 at level 0 is not run at all.** That saves the whole second reader pass. Osc 1 is
always run, because it is the one that writes the buffer.

**Room.** With the second pass, the loop was 1,020 B, and the build wants 64 B of NOP
padding after every code span. The register restore and the way back (`wr_t5v_exit`, 31
instructions) moved into the reader's span, after `wr_render5`. After that the loop is
844 B of 1,024 and the reader span is 560 B of 1,024.

**DM used, all inside spans the build already writes as zeros:**
- `0x2dde88..0x2dde97`: the state block's free words after the counters.
- `0x2de6c4`: the directory block's tail, next to M9a's gain.
- `0x2de800..0x2dea00`: osc 2's 16 reader blocks, the end of the directory block's tail.

`0x2de100` stays `idle_load`'s.

**The default sound gets louder.** WaveTone's default LEV2 is 100, so a default
Waverider sound now plays two identical oscillators in phase. That is exactly 2× the
M9a output, +6 dB. Turning LEV2 to 0 restores the one-oscillator sound bit for bit.

**The page.** Page 2's DETN, LEV, POS and TBL are records 242, 245, 243 and 251, with the
long names Osc2 Detune, Osc2 Level (stock), Osc2 Position and Osc2 Table. The wave
follows the page: osc 1's frame on page 1, osc 2's on page 2. Each oscillator's POS and
TBL keep their own sweep, and `wr_poll` watches only the shown page's two places.

## The gate

`scripts/sharc_waverider_m5.py` runs the image's own unpack and dispatch in digikit's
SHARC executor and compares the machine tap with `live.render_two`, bit for bit. Its
M9b checks:
- with LEV2 0, osc 2's reader is never called (every osc-1 run sets LEV2 0);
- the default sound's tap is exactly 2× its LEV2-0 tap;
- osc 2 alone (LEV1 0, WAV2 at the top) is bit-identical to osc 1 alone at POS 120;
- osc 2's own block, read on the reader's entry, has TBL2 1 → table 1, TUN2 +12 → twice
  the increment, and WAV2 0x4000 → its position. Osc 1's block keeps table 0 and POS 120.
