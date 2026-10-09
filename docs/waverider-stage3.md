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
   table ~160 M cycles, ~0.46 s** at the DSP's ~35 % idle (the guess was 30 ms).
   **The real-input FFT** (`rfft.asm`: N reals as N/2 complex, a split step after the
   forward and before the inverse; `scripts/sharc_rfft_check.py`): correct to 1.7e-7 at
   N 16..2048, N 2048 ~344k cycles forward, ~341k inverse; a 2048-point frame's levels
   ~1.33 M cycles, **a 64 x 2048 table ~85 M cycles, ~0.24 s at ~35 % idle**.
   **SIMD with hardware loops** (`fft2.asm`, `scripts/sharc_fft2_check.py`; designed from
   the PRM, owner 2026-10-09: the manuals are the authority, stock a guide): PEx real,
   PEy imaginary, twiddles stored (sin, -sin, cos, cos) so w y is two multiplies and an
   add; post-modify walks (M registers in words: byte space scales them by the access
   size); the inner loop 10 instructions (25 before). Correct to 1.8e-7 at M 8..1024. At
   M 1024: 82,843 instructions (156,522 before); with a twiddle table for the transform's
   own size ~160k cycles (269k with the 4096 table, the read misses 134k -> 26k; data in
   L1 is worse in the model, 173k, same-block conflicts). Left: the bit reversal's
   branches (~35k: fold it into the int16 -> float conversion with BITREV), the E2-active
   loop exits (11k: set F1-active per PRM 4-37), multifunction packing and radix 4.
   Found on the way: selmap prints a Type 3a modifier wrongly (bit 40 ignored: M0 as m4;
   digikit and selas agree on the manual's field), digikit's Type 3a had no SIMD second
   transfer at 6f812e9 (fixed upstream, 277760a), and our two-pass SIMD merge lost a
   PEy-named load (fixed, sharc_dn2_fixups G11).
   **Split arrays, two butterflies an issue** (`fft3.asm`, `scripts/sharc_fft3_check.py`,
   2026-10-09): real and imaginary parts in separate arrays, so a SIMD access gives two
   neighbouring points and PEx and PEy each run a butterfly (k, k+1), their twiddles
   neighbours in per-stage tables; the butterfly in the multifunction forms (a multiply
   with an add or an add/subtract pair, a DM and a PM transfer in one instruction: real
   parts on DM, imaginary on PM): **four instructions for two butterflies**, pipelined so
   no float result feeds the next instruction's compute (PRM Table 4-36: 1 stall). Each
   stage runs its loops whichever way makes the inner one longer (over the groups while
   h^2 <= M, over the twiddle pairs after, five instructions there: the twiddles load
   too). The first pass is the bit reversal (BITREV on a counter whose low bits are the
   reversed source base) fused with stages 0 and 1 (radix 4, adds only), ten
   instructions a group of four, the next group's loads beside the last one's stores.
   Inner loops F1-active. The inverse is the same code with real and imaginary pointers
   swapped. Correct to 1.9e-7 at M 8..2048 both ways. **At M 1024: 13,401 instructions,
   ~13.7k cycles with the arrays in L1** (fft2 there: 82,843 and ~147k, so ~10.8x);
   ~54k in DDR from cold, the 405 line misses being the first touch of the 24 KB the
   transform reads and writes (the model has one 16 KB data cache where the core has a
   DM and a PM one). M 2048 ~28.5k cycles in L1. Left: the stage setups (~1.4k of the
   13.7k), and where the level builder keeps its arrays (L1 is scarce, block 2 is the
   PM cache's).
   **Two frames a transform** (`spec3.asm`, `scripts/sharc_levels3_check.py`, 2026-10-09):
   frame a as the real part and frame b as the imaginary part of one complex FFT; each
   frame's spectrum is Hermitian, so splitting Z into the two (2A[k] = Z[k] + conj Z[N-k],
   2B[k] = (Z[k] - conj Z[N-k]) / i) and joining a level's two band-limited spectra back
   into one (Z[k] = A[k] + i B[k], Z[L-k] = conj A[k] + i conj B[k], zeros between) are
   add/subtract pairs only, four instructions a bin; a level's inverse then gives frame
   a's level as its real part and frame b's as its imaginary part. This replaces the
   real-input split step (a twiddle multiply a bin) and its scheduling. Every level of
   two 2048-point frames matches `geometry.frame_levels` to 3e-7 (the DSP's output 2N
   times the model's: a power of two, for the int16 conversion's scale). **Two frames'
   levels ~142.5k cycles in L1, ~71k a frame, a 64 x 2048 table ~4.6 M cycles (~13 ms at
   ~35 % idle; ~85 M and ~0.24 s with fft.asm + rfft.asm).** Of the 142.5k: forward 28.5k,
   split 6.2k, joins 16.8k, inverses 91k; the split and joins run near twice their
   instructions in this test's L1 layout (arrays that move together share a block).
   **A table's levels, int16 to int16** (`mipb3.asm`, `scripts/sharc_mipb3_check.py`,
   2026-10-09): two pool-table frames (int16) to the split floats, and each level's
   floats to the row the reader reads, [last, x0 .. x(L-1), x0, x1] (dnfw.waverider.mip),
   rounded to nearest by `FIX .. BY -S` (S = log2 N + 1, the 2N above) and clipped by
   CLIP to +-32767, in SIMD (PEx the even sample, PEy the odd; 16-bit pair loads and
   stores, Type 3d). Every row of four 2048-point near-full-scale saws, all ten levels
   (the band-limited saws overshoot, so the clip works), within 1 LSB of the model's
   rint and clip (a float32 transform puts a value on the other side of .5 now and then).
   **~119k cycles a frame with the levels in DDR** (in 8.5k, forward 14.3k, split 3.1k,
   out 39.3k, joins 8.4k, inverses 45.5k): the 16 KB of levels a frame writes cost ~25k
   of the out in cold write misses. A 64-frame table ~7.6 M cycles, ~22 ms at ~35 % idle.
   **Passed on the instrument (2026-10-09, fftselftest3):** the fingerprint equals the
   emulator's (0xbc1bb056) and 0 of 891,280 runs differed while a busy project played;
   forward N = 256 8.8k cycles, a whole two-frame level run 49k (EMUCLK). The two builds
   before it found two things the emulator does not model: **the DM and PM data caches are
   not coherent for DDR** (fftselftest: every result 0, fft3 wrote on PM what it read on
   DM), so every array now moves on one bus only (real parts DM, imaginary parts PM; the
   inverse by spec3's join writing i conj Z, not a pointer swap) and
   `scripts/sharc_bus_check.py` fails any cross-bus read in the emulator; and in the idle
   task **L6 = L7 = 194 with CBUFEN on** (fftselftest2), so I6 and I7 are never walked.
   The idle task also runs on the secondary DAG and register sets (MODE1 0x1011cf8).
   **On the instrument** (`selftest.asm`, `scripts/build_selftest.py`,
   `tools/dn2selftest.py`): a diagnostic build runs the whole level build of two
   256-point frames in the DSP's idle task, over and over, and hashes every output word;
   the first run's hash must equal the emulator's (`scripts/sharc_selftest_check.py`:
   0xbc1bb056, the hash recomputed from the words read, every level matching the model
   to 2.2e-7), and later runs must not differ from it (an interrupt or a task switch that
   does not keep what the code uses would show there). EMUCLK gives the cycles on the
   silicon. Code the audio interrupt can preempt must leave the C runtime's constant
   registers alone: stock's interrupt entry pushes through `DM(I7, M7)` at once (sw
   0x1c0ad9), so fft3 now uses M0-M4 and M8-M12 only, and `sharc_fft3_check.py` fails a
   run that changes M5-M7, M13-M15, I7 or any L or B register. SIMD is safe there: no
   stock code writes MMASK, whose default clears PEYEN when an interrupt pushes the
   status stack (PRM "Interrupt Mask Mode").
   Found on the way, all fixed in `scripts/sharc_waverider_m3.py` and checked with
   `scripts/selas_roundtrip.py` (selas's output read back by digikit's decoder): selas
   swaps Type 19a's g and bit-reverse bits; emits a garbage 48-bit Type 7a (`MODIFY(Ia,
   Mb)`); drops the subtract of a dual add/subtract or adds a phantom multiply; leaves g
   0 on a single PM transfer (`PM(I10, M12) = R6` ran as `DM(I2, M4) = R6`); writes ASHIFT
   by an immediate with opcode 100000 (PRM: 000001); drops the F1-active bit of `DO ..
   UNTIL LCE (F)`; drops the width of a 16-bit store (`DM(Ia, Mb) = Rn (SW)` came out
   32-bit); rejects ROT by an immediate; and leaves relocations for `JUMP label`, `CALL
   label`, `Ib = MODIFY(Ia, ..)` and a compute with MODIFY. In digikit's runner: BITREV is
   decoded but not executed (sharc_dn2_fixups G12), Type 1a's SIMD PM companion is not
   modelled (G13), and the fixed-point CLIP has no handler (G14); fixes for all three are
   in m-dwyer/digikit#58 (BITREV, the PM companion) and #59 (CLIP). The cycle model now
   prices F1-active exits at 0 and counts a SIMD pair as one L1 access.
2. **The load (built, 2026-10-10).** The pool sends each table as stored and the DSP
   builds its levels in its idle time (`csrc/waverider/sharc/build3.asm`,
   `dnfw.waverider.table3`):
   - **DDR.** The load area grows to `0x807ff000..0x84800000`: the request directory's 4 KB,
     then entry j's table as stored (int16, frame-major) at `0x80800000 + j x 512 KiB`.
     build3's arrays at `0x84800000` (32 KB apart), entry j's levels at `0x84900000 + j x
     0x201000` (2 MB + 4 KB each, enough for 64 x 4096) to `0x94980000`, all in the free DDR
     (`docs/sharc-ddr.md`). The templates (a header and build rows per N), S per F and the
     4096-point twiddles (which serve every smaller transform) load with the boot stream
     at `0x80700000`.
   - **The protocol** (`pool.c`): clear the request directory's magic, send the tables,
     then the directory body (count, generation, each entry's `frames | points << 16`),
     its magic `'WRP3'` last. The DSP builds nothing while the magic is clear, starts
     again at entry 0 on a new generation, and names an entry for `pool.asm` (its L1
     directory `BUILT[j]`, `0x2e4100`) only once every pair of frames is done: an entry
     being rebuilt plays Prim., never half a table. A refill no longer leaves a voice on a
     table being rewritten.
   - **One idle call, one pair of frames.** fft3, spec3 and mipb3 moved to free L1 above the
     reader (`0x2e3800..0x2e4b00`, their jumps PC-relative); build3 at `0x2e4b00`. The idle
     loop's back edge goes to build3, which goes on to idle_load.asm; a call that builds
     sets idle_load's previous-pass time to now, so it counts as neither idle time nor one
     long busy stretch (the load meter reads high while tables build, and no false
     overrun). It keeps every register the idle loop could hold (checked per call).
   - **Checked** (`scripts/sharc_build3_check.py`, the shipped section 7, in the runner):
     16 x 512, 5 x 64, 3 x 256, 2 x 4096, 1 x 4096 and the four test geometries: every
     header equal to `table3`'s, every row within 1 LSB of the model; an empty entry and
     7 x 100 stay 0; nothing built with the magic clear; a new generation rebuilds, the
     entry reading 0 meanwhile; no cross-bus read. The DSP pool gate
     (`scripts/sharc_waverider_pool.py`, 13 checks): load frames through command 4, the
     levels built, slot 2 (16 x 512) and slot 3 (5 x 1024, POS scaled) bit-exact to the
     reference reader on the levels the DSP built, the 128th entry plays. The ColdFire
     pool test (`scripts/emu_waverider_pool.py`, 10/10 on the build): the frames are
     `loadframes`' byte for byte, the display spans of a 5 x 1024 table are the model's.
   - **Cost, the cycle model** (now with separate DM and PM data caches, as the core has):
     a table 64 x 2048 ~55 M cycles (32 calls, ~1.7 M each: ~0.16 s at ~35 % idle), 64 x 512
     ~13 M, 16 x 2048 ~14 M, 16 x 512 ~3.4 M; a 4096-point pair ~6.3 M, nearly all DDR
     misses: a 16 KB array per bus streams through a 16 KB cache once per FFT stage. To
     measure on the instrument and to improve (stages blocked to fit the cache) under the
     perf gate.
   - **Found on the way:** digikit's `_dm_read` read a word only partly written as 0 under
     `explicit_memory_model` (m-dwyer/digikit#60).
3. **The reader (built, 2026-10-10).** A table with the flag is a `table3` table: a 1 KB
   header (F, the position's scale S = (F - 1) / 15 rounded up, F - 1, the thresholds T[k]
   for its N, the level records), then the rows. reader_miph2 reads its level choice,
   records and last frame from the header and scales POS: pos = trunc(POS x S) (exact for
   F = 16; POS 15 lands on frame F - 1). The baked tables carry the same header, so every
   gate on them is unchanged; `table3.read` is the model, equal to `mip.read` at 16 x 512.
4. **The gate (built, 2026-10-10).** `wr_store_playable` now takes 1..64 waves of 64..4096
   points (a power of two), length 2 x waves x points, in the slot's own extent; anything
   else still shows no name in the pool page. DNX told (2026-10-10): its
   `unplayableReason` should follow the same rule on a stage 3 build. The pool page shows
   16 frames of any table, frame d the table's frame nearest d (F - 1) / 15
   (`wave.pool_spans`).
5. **The perf gate** (`perf-stability-gate`): runner worst case, instrument load and a soak
   against the factory machines, one variable per pair.
