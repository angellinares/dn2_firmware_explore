# Waverider stage 3: pool tables of any geometry, mip-mapped

**Goal (owner, 2026-10-09):** play larger tables from the pool (Tonverk's native
geometries: up to 64 waves of 64..4096 points) with the reader we keep, mip2h (mip levels +
fast Hermite, 28 kHz), at a load near today's ~64 % with the chord. Fewer frames is the
real compromise (the owner); points only matter for low notes.

## What is settled

- **Memory:** the DSP's DDR is 512 MB and ~507 MB of it is free, `0x80531000..0xa0000000`
  (`docs/sharc-ddr.md`, confirmed on the instrument). 127 tables of 64 x 2048 with levels is
  ~127 MB.
- **The store** already holds any geometry within its 512 KiB slots, at full resolution
  (`docs/waverider-store.md`); DNX writes `.raw` payloads, int16 big-endian, frame-major.
- **The model:** `dnfw.waverider.geometry` (levels for N points, the level choice, hermite2's
  reader; equal to `dnfw.waverider.mip` at 512 points).
- **The test set** (`scripts/waverider_geometry_set.py`): one generated table at 64x2048,
  64x512, 16x2048, 16x512, in the store at slots **78, 79, 80, 81** (DNX, 2026-10-09) and in
  the owner's working pool at pool slots 9..12. Renders: two formant peaks on 16 frames where
  64 have one; the 512-point tables carry only the box filter's folded images above
  harmonic 255. Sizes with levels and guards: 1026, 257, 256, 64 KB.
- **The model against the instrument** (2026-10-09, the owner's recording of pool slot 12,
  `WR test 16x512`, a manual POS sweep at 130.8 Hz, 42 s): each quarter second matched to
  the nearest POS of the model's render on harmonics 1..127 differs by a median 1.06 dB
  (90th percentile 3.39 dB); the other geometries fit worse (16x2048 1.17 / 6.66, 64x512
  2.27 / 5.94, 64x2048 3.17 / 8.31), and the matched POS traces the sweep 0 -> 0.93 -> 0.
  So `geometry` predicts what the instrument plays for the table it can play today.

## What has to change

1. **Who builds the levels: the DSP, when a table loads (owner, 2026-10-09).** The store keeps
   the original; the level design can change with a firmware update; a quarter of the bytes
   cross the link. The ADSP-21569 has no FFT accelerator (FIR/IIR only), so the core does it
   with the model's method: one forward FFT per frame, an inverse per level after level 0.
   **First measurement** (`csrc/waverider/sharc/fft.asm`, `scripts/sharc_fft_check.py`, the
   cycle model): a plain radix-2 complex FFT, correct to 2e-7 at N 16..2048; N 2048 is
   337,554 instructions, ~650k cycles in DDR and ~624k in L1 (memory costs 4 %: the
   instructions are the cost). A 2048-point frame's levels ~2.5 M cycles; **a 64 x 2048
   table ~160 M cycles, ~0.46 s** at the DSP's ~35 % idle (the guess was 30 ms). Next: the
   real-input packing (half the work), SIMD on the second processing element, radix 4.
2. **The load.** Today the pool copies 16 x 512 tables only (16 KB slots, 2 MB area at
   `0x807ff000`) through command 4's chunks. A table of any size needs a variable extent in
   the free DDR and a directory entry carrying its geometry.
3. **The reader.** reader_miph2 reads 16 frames and 512 points from fixed level records
   (`mip.level_records`); it needs per-table frames, points and level records.
4. **The gate.** `wr_store_playable` (16 x 512 only) decides both the slot and its **name**
   in the pool page (`csrc/waverider/pool.c:119`): a stored table the DSP can't play shows
   **no name**, which the owner saw on pool slots 9..11 (DNX, 2026-10-09). When the gate
   widens, a table that still can't play (too big, an odd geometry) must stay visibly
   different, not take a name and play Prim. under it. **DNX depends on this** (DNX,
   2026-10-09): a `/waverider` listing carries no geometry (every slot reports the fixed
   512 KiB extent), so DNX's pane can only judge a slot with a file read per slot; today its
   `unplayableReason` and the instrument's blank name agree on the one check. Widening the
   gate without a visible difference leaves DNX as the only warning, at 128 reads. (The
   automatic pool filters by geometry; the instrument's ADD does not.)
5. **The perf gate** (`perf-stability-gate`): runner worst case, instrument load and a soak
   against the factory machines, one variable per pair.
