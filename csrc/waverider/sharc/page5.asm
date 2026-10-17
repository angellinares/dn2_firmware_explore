// page5.asm -- Waverider page 5, the shape (docs/waverider-shape.md): FOLD, the shaper's
// TYPE (Ring, AM) with AMT, WARP and FM. (NPOS, noise into POS, waits on branch
// wip/waverider-npos: its DCLK crossfades cost a second table read on each oscillator, owner
// 2026-10-16.)
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in), run offline in digikit's SHARC executor inside the DN2 1.11 image and checked
// bit for bit against dnfw.waverider.live (fold, shaper; scripts/sharc_waverider_shape.py).
//
// The controls are frame words like the others, at 0x25c48c + 146t:
//   FOLD  sound slot 58, offset 284      WARP  slot 59, offset 286      FM  slot 60, offset 288
//   TYPE  slot 62, offset 292 (>> 8: 0 Off, 1 Ring, 2 AM; others Off)    AMT  slot 48, offset 264
// Each at 0 (every sound's default since page 5) skips its code, so the voice is
// bit-identical to the one before page 5.
//
// WARP and FM change where each sample is read: wr_p5_phase writes every sample's phase to
// PH (DM 0x2e6280), and phase.asm's readers read there in place of the running phase.
//
// wr_p5_voice (machine9_live.asm, before a voice's osc 1): with FM above 0, LEV2 above 0 and a
//   block of 128 or less, osc 2 plays first, into FMB (DM 0x2e6080, zeroed: osc 2 adds), with
//   osc 1's TUN1 as its tune base (as machine9_live.asm forms it). wr_p5_ran then sets up
//   osc 1, in the track buffer, and wr_p5_mid adds FMB in (keeping osc 1's copy for the
//   shaper). The mix is then o1 + o2, as osc 2 adds it when it plays second. FM state
//   (DM 0x2e6004): 0 none, 1 osc 2 playing first, 2 osc 1 playing second.
//
// wr_p5_phase (machine9_live.asm's CJUMP to the reader, R4 = I4 = the reader block): with
//   WARP above 0 (both oscillators) or FM (osc 1, FM state 2), PH[i] for each sample:
//     p = phase + i inc (+ TRUNC (FMB[i] x c) BY 24 << 8, c = FM x f32(1 / (0x7f00 T)))
//     WARP v = min(word >> 8, 127), (k1, k2) from the table at DM 0x2e6500:
//     q = (p >> 1) x 2^-31; p' = (TRUNC min(q k1, 1 - (1 - q) k2) BY 31) << 1
//   then PH[N] = phase + N inc (what the reader keeps), the level's increment
//   TRUNC ((inc + inc2 x FM x f32(2 pi / 0x7f00)) x k1) at DM 0x2e6018, and the PH flag
//   (DM 0x2e6014). Then on to wr_dclk_pre, as before. Clobbers R0-R15, I0-I2.
//
// Two more ways in, each by a JUMP another source sends here instead of where it went:
//
// wr_p5_mid (machine9_live.asm's JUMP to wr_t5v_osc once osc 1 is done): with TYPE 1 or 2
//   and AMT above 0, osc 1's samples are copied to DM 0x2e5e00 (128 floats), for the
//   shaper after osc 2. Clobbers R0-R3, R9-R12, I0, I1.
//
// wr_p5_ran / wr_p5_skip (machine9_live.asm's two ways to the sub, osc 2 run or skipped):
//   the shaper, then FOLD, on the track buffer, then formant.asm's wr_fm_post (TYPE Formant),
//   which goes on to sub.asm by the same way in.
//     Ring  y = b + a (o1 o2 / T - b)          AM  y = b + a (o1 (o2 / T + 1) 0.5 - b)
//     with b the buffer, o1 the copy, o2 = b - o1, a = AMT / 0x7f00, T = f32(10^(-11/20)).
//     FOLD  g = (1 + FOLD x f32(7 / 0x7f00)) x f32(1 / T); v = x g + 1; the phase
//           (TRUNC v BY 24) << 6; |w| = (ABS phase >> 1) x 2^-29, 0..2; y = |w| T - T.
//   An osc 2 skipped this block leaves b = o1: o2 is 0. Clobbers R0-R15, I0-I2, as sub.asm
//   does; I3 and I5 (the loop's pointers) are not touched.
//
// The sample loops are hardware loops with straight-line bodies (PRM: such a loop can run
// F1-active; a body under 11 instructions is all ISA, so each sits under .NOCOMPRESS), with
// each branch taken once outside them (one loop per type). Every float result feeds a
// two-operand compute or a store (anomaly 20000072: F0 then a single-operand compute).
//
// DM (byte addresses, after build3.asm):
//   0x2e5e00  osc 1's copy, 128 float32
//   0x2e6000  1 when osc 2 ran this block (which way to sub.asm)
//   0x2e6004  FM state;  0x2e6008 the track buffer while osc 2 plays into FMB
//   0x2e600c  FM's c;    0x2e6010 FM x f32(2 pi / 0x7f00), for the level
//   0x2e6014  1: the reader reads PH;  0x2e6018 the level's increment;  0x2e601c I3, kept
//   0x2e6020  WARP's v for this voice (wr_p5_voice)
//   0x2e6080  FMB, osc 2's samples under FM, 128 float32
//   0x2e6280  PH, 129 u32
//   0x2e6500  WARP's (k1, k2), 128 pairs of float32 (dnfw.waverider.live.warp_table)
//
// PLACEMENT IS FIXED at PM sw 0x172b00 (DM 0x2e5600): the absolute jumps below are written
// for it by scripts/sharc_resolve_jumps.py.

.SECTION/PM seg_pmco;

.GLOBAL wr_p5_mid.;
wr_p5_mid.:
      R0 = DM(0x2e6004);
      R1 = 2;
      COMP(R0, R1);
      IF EQ JUMP 0x172d89;                   // -> wr_p5_fm_mix. (osc 1 after osc 2: add FMB in)
      CALL 0x172b32;                    // -> wr_p5_shaper_on.
      R0 = PASS R0;
      IF EQ JUMP 0x16ed86;              // -> wr_t5v_osc. (no shaper: nothing to keep)
      // osc 1's samples, two a pass (the block is even: 32)
      R0 = DM(0x2dde88);
      I0 = R0;                          // the track buffer
      R12 = 0x2e5e00;
      I1 = R12;
      R0 = DM(0x2dde24);
      R0 = LSHIFT R0 BY -1;
      LCNTR = R0, DO wr_p5_copy_end. UNTIL LCE;
.NOCOMPRESS;
      R1 = DM(I0, M6);
      R2 = DM(I0, M6);
      DM(I1, M6) = R1;
.GLOBAL wr_p5_copy_end.;
wr_p5_copy_end.:
      DM(I1, M6) = R2;
.COMPRESS;
      JUMP 0x16ed86;                    // -> wr_t5v_osc.

// R0 = the shaper's TYPE (1 Ring, 2 AM) when TYPE is 1 or 2 and AMT above 0, else 0;
// R1 = the AMT word; R9 = t. Clobbers R2, R3, R10-R12, I0.
.GLOBAL wr_p5_shaper_on.;
wr_p5_shaper_on.:
      R0 = DM(0x2dde80);
      R1 = 16;
      R9 = R1 - R0;                     // t
      R10 = LSHIFT R9 BY 7;
      R11 = LSHIFT R9 BY 4;
      R10 = R10 + R11;
      R11 = LSHIFT R9 BY 1;
      R10 = R10 + R11;                  // 146t
      R12 = 0x25c5b0;                   // 0x25c48c + 292: TYPE
      R2 = R12 + R10;
      R3 = -4;
      R3 = R2 AND R3;
      I0 = R3;
      R0 = DM(0, I0);
      R3 = 2;
      R3 = R2 AND R3;
      R3 = LSHIFT R3 BY 3;
      R12 = R12 - R12;
      R3 = R12 - R3;
      R0 = LSHIFT R0 BY R3;
      R12 = 0xffff;
      R0 = R0 AND R12;
      R0 = LSHIFT R0 BY -8;             // TYPE
      R12 = 0x25c594;                   // 0x25c48c + 264: AMT
      R2 = R12 + R10;
      R3 = -4;
      R3 = R2 AND R3;
      I0 = R3;
      R1 = DM(0, I0);
      R3 = 2;
      R3 = R2 AND R3;
      R3 = LSHIFT R3 BY 3;
      R12 = R12 - R12;
      R3 = R12 - R3;
      R1 = LSHIFT R1 BY R3;
      R12 = 0xffff;
      R1 = R1 AND R12;                  // AMT
      IF EQ JUMP 0x172b8f;              // -> wr_p5_off.
      R12 = 1;
      R12 = R0 - R12;
      R3 = 1;
      COMPU(R12, R3);
      IF LE JUMP 0x172b90;              // -> wr_p5_on. (TYPE - 1 in 0..1)
.GLOBAL wr_p5_off.;
wr_p5_off.:
      R0 = R0 - R0;
.GLOBAL wr_p5_on.;
wr_p5_on.:
      RTS;

.GLOBAL wr_p5_ran.;
wr_p5_ran.:
      R0 = DM(0x2e6004);
      R1 = 1;
      COMP(R0, R1);
      IF EQ JUMP 0x172d6e;                   // -> wr_p5_fm_o1. (osc 2 played first: now osc 1)
      R0 = 1;
      DM(0x2e6000) = R0;
      JUMP 0x172bb1;                    // -> wr_p5_post.
.GLOBAL wr_p5_skip.;
wr_p5_skip.:
      R0 = DM(0x2e6004);
      R1 = 1;
      COMP(R0, R1);
      IF EQ JUMP 0x172d6e;                   // -> wr_p5_fm_o1.
      R0 = R0 - R0;
      DM(0x2e6000) = R0;

.GLOBAL wr_p5_post.;
wr_p5_post.:
      CALL 0x172b32;                    // -> wr_p5_shaper_on.
      R12 = DM(0x2dde88);
      I0 = R12;                         // the track buffer, read
      I2 = R12;                         // and written
      R12 = 0x2e5e00;
      I1 = R12;                         // osc 1's copy
      R13 = DM(0x2dde24);               // the block
      R12 = 0x406314a0;                 // f32(1 / T)
      R8 = PASS R12;
      R12 = R12 - R12;
      F9 = FLOAT R1 BY R12;
      R12 = 0x38010204;                 // f32(1 / 0x7f00)
      F9 = F9 * F12;                    // a
      R0 = PASS R0;
      IF EQ JUMP 0x172c2b;              // -> wr_p5_fold.
      R12 = 1;
      COMPU(R0, R12);
      IF NE JUMP 0x172bfa;              // -> wr_p5_am.
      // Ring
      LCNTR = R13, DO wr_p5_ring_end. UNTIL LCE;
.NOCOMPRESS;
      R4 = DM(I0, M6);                  // b
      R5 = DM(I1, M6);                  // o1
      F2 = F4 - F5;                     // o2
      F2 = F5 * F2;
      F2 = F2 * F8;                     // o1 o2 / T
      F2 = F2 - F4;
      F2 = F9 * F2;
      F2 = F4 + F2;
.GLOBAL wr_p5_ring_end.;
wr_p5_ring_end.:
      DM(I2, M6) = F2;
.COMPRESS;
      JUMP 0x172c2b;                    // -> wr_p5_fold.
.GLOBAL wr_p5_am.;
wr_p5_am.:
      R12 = 2;
      COMPU(R0, R12);
      IF NE JUMP 0x172c2b;              // -> wr_p5_fold.
      R10 = 0x3f800000;                 // 1.0
      R11 = 0x3f000000;                 // 0.5
      LCNTR = R13, DO wr_p5_am_end. UNTIL LCE;
.NOCOMPRESS;
      R4 = DM(I0, M6);                  // b
      R5 = DM(I1, M6);                  // o1
      F2 = F4 - F5;                     // o2
      F2 = F2 * F8;
      F2 = F2 + F10;                    // o2 / T + 1
      F2 = F5 * F2;
      F2 = F2 * F11;                    // o1 (o2 / T + 1) / 2
      F2 = F2 - F4;
      F2 = F9 * F2;
      F2 = F4 + F2;
.GLOBAL wr_p5_am_end.;
wr_p5_am_end.:
      DM(I2, M6) = F2;
.COMPRESS;

.GLOBAL wr_p5_fold.;
wr_p5_fold.:
      // FOLD: 0x25c48c + 284 + 146t
      R0 = DM(0x2dde80);
      R1 = 16;
      R9 = R1 - R0;                     // t
      R10 = LSHIFT R9 BY 7;
      R11 = LSHIFT R9 BY 4;
      R10 = R10 + R11;
      R11 = LSHIFT R9 BY 1;
      R10 = R10 + R11;                  // 146t
      R12 = 0x25c5a8;                   // 0x25c48c + 284
      R2 = R12 + R10;
      R3 = -4;
      R3 = R2 AND R3;
      I0 = R3;
      R0 = DM(0, I0);
      R3 = 2;
      R3 = R2 AND R3;
      R3 = LSHIFT R3 BY 3;
      R12 = R12 - R12;
      R3 = R12 - R3;
      R0 = LSHIFT R0 BY R3;
      R12 = 0xffff;
      R0 = R0 AND R12;                  // FOLD
      IF EQ JUMP 0x172ca5;              // -> wr_p5_out.
      // g / T = (1 + FOLD x f32(7 / 0x7f00)) x f32(1 / T)
      R12 = R12 - R12;
      F1 = FLOAT R0 BY R12;
      R12 = 0x3961c387;                 // f32(7 / 0x7f00)
      F1 = F1 * F12;
      R12 = 0x3f800000;
      F1 = F1 + F12;
      R12 = 0x406314a0;                 // f32(1 / T)
      F8 = F1 * F12;                    // g / T
      R9 = 0x3f800000;                  // 1.0
      R10 = 24;
      R11 = -29;
      R12 = 0x3e904d1c;                 // T = f32(10^(-11/20))
      R0 = DM(0x2dde88);
      I0 = R0;
      I2 = R0;
      R13 = DM(0x2dde24);
      LCNTR = R13, DO wr_p5_fold_end. UNTIL LCE;
.NOCOMPRESS;
      R4 = DM(I0, M6);
      F1 = F4 * F8;                     // x g / T
      F1 = F1 + F9;                     // v = u + 1
      R1 = TRUNC F1 BY R10;
      R1 = LSHIFT R1 BY 6;              // (v / 4 mod 1) x 2^32
      R1 = ABS R1;
      R1 = LSHIFT R1 BY -1;
      F1 = FLOAT R1 BY R11;             // |w|, 0..2
      F1 = F1 * F12;
      F1 = F1 - F12;                    // |w| T - T
.GLOBAL wr_p5_fold_end.;
wr_p5_fold_end.:
      DM(I2, M6) = F1;
.COMPRESS;

.GLOBAL wr_p5_out.;
wr_p5_out.:
      // the Formant (formant.asm) takes the way to the sub from here; the three after it are
      // the way it was, kept so nothing after them moves (they no longer run)
      JUMP 0x1739cb;                    // -> wr_fm_post.
      R0 = PASS R0;
      IF NE JUMP 0x171000;              // -> wr_sub_ran. (sub.asm)
      JUMP 0x171008;                    // -> wr_sub_skip. (sub.asm)
// R9 = t, R10 = 146t. Clobbers R0, R1, R11.
.GLOBAL wr_p5_t146.;
wr_p5_t146.:
      R0 = DM(0x2dde80);
      R1 = 16;
      R9 = R1 - R0;                     // t
      R10 = LSHIFT R9 BY 7;
      R11 = LSHIFT R9 BY 4;
      R10 = R10 + R11;
      R11 = LSHIFT R9 BY 1;
      R10 = R10 + R11;                  // 146t
      RTS;

// R0 = the 16-bit frame word at byte R2 (2-aligned). Clobbers R3, R12, I0.
.GLOBAL wr_p5_word.;
wr_p5_word.:
      R3 = -4;
      R3 = R2 AND R3;
      I0 = R3;
      R0 = DM(0, I0);
      R3 = 2;
      R3 = R2 AND R3;
      R3 = LSHIFT R3 BY 3;
      R12 = R12 - R12;
      R3 = R12 - R3;
      R0 = LSHIFT R0 BY R3;
      R12 = 0xffff;
      R0 = R0 AND R12;
      RTS;

// machine9_live.asm's way into a voice's osc 1 comes here: FM's order, or osc 1 as before.
.GLOBAL wr_p5_voice.;
wr_p5_voice.:
      CALL 0x172caf;                         // -> wr_p5_t146.
      R12 = 0x25c5aa;                   // 0x25c48c + 286: WARP, read once a voice for both oscillators
      R2 = R12 + R10;
      CALL 0x172cc4;                         // -> wr_p5_word.
      R0 = LSHIFT R0 BY -8;
      R1 = 127;
      R0 = MIN(R0, R1);
      DM(0x2e6020) = R0;                // v
      R12 = 0x25c5ac;                   // 0x25c48c + 288: FM
      R2 = R12 + R10;
      CALL 0x172cc4;                         // -> wr_p5_word.
      R4 = PASS R0;
      IF EQ JUMP 0x16ed86;                   // -> wr_t5v_osc. (FM 0: osc 1 first, as before)
      R12 = 0x25c57c;                   // 0x25c48c + 240: LEV2
      R2 = R12 + R10;
      CALL 0x172cc4;                         // -> wr_p5_word.
      R0 = PASS R0;
      IF EQ JUMP 0x16ed86;                   // -> wr_t5v_osc. (osc 2 off: nothing to modulate with)
      R0 = DM(0x2dde24);                // the block
      R1 = 128;
      COMP(R0, R1);
      IF GT JUMP 0x16ed86;                   // -> wr_t5v_osc. (longer than PH and FMB)
      R12 = R12 - R12;
      F4 = FLOAT R4 BY R12;             // FM
      R12 = 0x38e4de5d;                 // f32(1 / (0x7f00 T))
      F0 = F4 * F12;
      DM(0x2e600c) = R0;                // c
      R12 = 0x394aa525;                 // f32(2 pi / 0x7f00)
      F0 = F4 * F12;
      DM(0x2e6010) = R0;
      // osc 2's tune base: osc 1's TUN1 in semitones, frame word / 256 - 64, as the loop forms it
      R12 = 0x25c566;                   // 0x25c48c + 218: TUN1
      R2 = R12 + R10;
      CALL 0x172cc4;                         // -> wr_p5_word.
      R12 = -8;
      F13 = FLOAT R0 BY R12;
      R12 = 0x42800000;                 // 64.0
      F13 = F13 - F12;
      DM(0x2dde98) = R13;
      // osc 2 into FMB, zeroed, two a pass (the block is even)
      R0 = DM(0x2dde88);
      DM(0x2e6008) = R0;                // the track buffer, for osc 1
      R0 = 0x2e6080;
      DM(0x2dde88) = R0;
      I0 = R0;
      R1 = R1 - R1;
      R0 = DM(0x2dde24);
      R0 = LSHIFT R0 BY -1;
      LCNTR = R0, DO wr_p5_zero_end. UNTIL LCE;
.NOCOMPRESS;
      DM(I0, M6) = R1;
.GLOBAL wr_p5_zero_end.;
wr_p5_zero_end.:
      DM(I0, M6) = R1;
.COMPRESS;
      R0 = 1;
      DM(0x2de6c4) = R0;                // osc 2: adds (into the zeros)
      DM(0x2e6004) = R0;                // FM state 1
      R0 = 0x900;
      DM(0x2dde90) = R0;
      R0 = 12;
      DM(0x2dde94) = R0;
      JUMP 0x16ed86;                         // -> wr_t5v_osc.

// FM state 1, osc 2 done: osc 1, in the track buffer.
.GLOBAL wr_p5_fm_o1.;
wr_p5_fm_o1.:
      R0 = DM(0x2e6008);
      DM(0x2dde88) = R0;
      R0 = R0 - R0;
      DM(0x2de6c4) = R0;                // osc 1: replaces
      DM(0x2dde90) = R0;
      DM(0x2dde94) = R0;
      DM(0x2dde98) = R0;                // osc 1 adds no tune base (+0.0)
      R0 = 2;
      DM(0x2e6004) = R0;                // FM state 2
      JUMP 0x16ed86;                         // -> wr_t5v_osc.

// FM state 2, osc 1 done: b = o1 + FMB (osc 1's copy kept when the shaper is on), then page 5.
.GLOBAL wr_p5_fm_mix.;
wr_p5_fm_mix.:
      R0 = R0 - R0;
      DM(0x2e6004) = R0;
      R0 = 1;
      DM(0x2e6000) = R0;                // osc 2 ran
      CALL 0x172b32;                    // -> wr_p5_shaper_on.
      R12 = DM(0x2dde88);
      I0 = R12;                         // the track buffer: o1, then the mix
      R12 = 0x2e6080;
      I1 = R12;                         // FMB: o2
      R12 = 0x2e5e00;
      I2 = R12;                         // osc 1's copy
      R13 = DM(0x2dde24);
      R0 = PASS R0;
      IF EQ JUMP 0x172dc0;                   // -> wr_p5_fm_add.
      LCNTR = R13, DO wr_p5_fmc_end. UNTIL LCE;
.NOCOMPRESS;
      R1 = DM(0, I0);
      R2 = DM(I1, M6);
      DM(I2, M6) = R1;
      F1 = F1 + F2;
.GLOBAL wr_p5_fmc_end.;
wr_p5_fmc_end.:
      DM(I0, M6) = F1;
.COMPRESS;
      JUMP 0x172bb1;                    // -> wr_p5_post.
.GLOBAL wr_p5_fm_add.;
wr_p5_fm_add.:
      LCNTR = R13, DO wr_p5_fma_end. UNTIL LCE;
.NOCOMPRESS;
      R1 = DM(0, I0);
      R2 = DM(I1, M6);
      F1 = F1 + F2;
.GLOBAL wr_p5_fma_end.;
wr_p5_fma_end.:
      DM(I0, M6) = F1;
.COMPRESS;
      JUMP 0x172bb1;                    // -> wr_p5_post.

// machine9_live.asm's CJUMP to the reader comes here: PH for WARP and FM, then wr_dclk_pre.
.GLOBAL wr_p5_phase.;
wr_p5_phase.:
      R0 = R0 - R0;
      DM(0x2e6014) = R0;                // the reader's own phase, unless PH is written below
      R5 = DM(0x2e6004);
      R1 = 2;
      COMP(R5, R1);
      IF EQ JUMP 0x172de7;                   // -> wr_p5_ph_on. (osc 1 under FM)
      R5 = R5 - R5;
      R0 = DM(0x2e6020);                // WARP's v (wr_p5_voice)
      R0 = PASS R0;
      IF EQ JUMP 0x172ec1;                   // -> wr_p5_ph_go. (no WARP, no FM)
.GLOBAL wr_p5_ph_on.;
wr_p5_ph_on.:
      R13 = DM(4, I4);                  // N
      R1 = 128;
      COMP(R13, R1);
      IF GT JUMP 0x172ec1;                   // -> wr_p5_ph_go. (longer than PH)
      CALL 0x172caf;                         // -> wr_p5_t146. (R9 = t, for inc2)
      R0 = DM(0x2e6020);                // v
.GLOBAL wr_p5_ph_fm.;
wr_p5_ph_fm.:
      R1 = LSHIFT R0 BY 3;
      R12 = 0x2e6500;
      R1 = R12 + R1;
      I1 = R1;
      R6 = DM(0, I1);                   // k1
      R7 = DM(1, I1);                   // k2
      R8 = DM(1, I4);                   // phase
      R11 = DM(2, I4);                  // inc
      R12 = 0x2e6280;
      I2 = R12;                         // PH
      R12 = 0x2e6080;
      I1 = R12;                         // FMB
      R3 = 0x3f800000;                  // 1.0
      R14 = -31;
      R15 = 31;
      R10 = 24;
      R12 = DM(0x2e600c);               // c
      R5 = PASS R5;
      IF EQ JUMP 0x172e70;                   // -> wr_p5_ph_warp.
      R0 = PASS R0;
      IF EQ JUMP 0x172e58;                   // -> wr_p5_ph_fmonly.
      // FM and WARP
      LCNTR = R13, DO wr_p5_phb_end. UNTIL LCE;
.NOCOMPRESS;
      R4 = DM(I1, M6);                  // o2
      F4 = F4 * F12;                    // cycles
      R4 = TRUNC F4 BY R10;
      R4 = LSHIFT R4 BY 8;              // mod 2^32
      R0 = R8 + R4;                     // p
      R0 = LSHIFT R0 BY -1;
      F0 = FLOAT R0 BY R14;             // q
      F1 = F0 * F6;                     // q k1
      F2 = F3 - F0;
      F2 = F2 * F7;
      F2 = F3 - F2;                     // 1 - (1 - q) k2
      F1 = MIN(F1, F2);
      R1 = TRUNC F1 BY R15;
      R1 = LSHIFT R1 BY 1;
.GLOBAL wr_p5_phb_end.;
wr_p5_phb_end.:
      R8 = R8 + R11, DM(I2, M6) = R1;
.COMPRESS;
      JUMP 0x172e91;                         // -> wr_p5_ph_end.
.GLOBAL wr_p5_ph_fmonly.;
wr_p5_ph_fmonly.:
      LCNTR = R13, DO wr_p5_phf_end. UNTIL LCE;
.NOCOMPRESS;
      R4 = DM(I1, M6);
      F4 = F4 * F12;
      R4 = TRUNC F4 BY R10;
      R4 = LSHIFT R4 BY 8;
      R1 = R8 + R4;
.GLOBAL wr_p5_phf_end.;
wr_p5_phf_end.:
      R8 = R8 + R11, DM(I2, M6) = R1;
.COMPRESS;
      JUMP 0x172e91;                         // -> wr_p5_ph_end.
.GLOBAL wr_p5_ph_warp.;
wr_p5_ph_warp.:
      LCNTR = R13, DO wr_p5_phw_end. UNTIL LCE;
.NOCOMPRESS;
      R0 = LSHIFT R8 BY -1;
      F0 = FLOAT R0 BY R14;
      F1 = F0 * F6;
      F2 = F3 - F0;
      F2 = F2 * F7;
      F2 = F3 - F2;
      F1 = MIN(F1, F2);
      R1 = TRUNC F1 BY R15;
      R1 = LSHIFT R1 BY 1;
.GLOBAL wr_p5_phw_end.;
wr_p5_phw_end.:
      R8 = R8 + R11, DM(I2, M6) = R1;
.COMPRESS;
.GLOBAL wr_p5_ph_end.;
wr_p5_ph_end.:
      DM(0, I2) = R8;                   // PH[N]: the phase the reader keeps
      // the level's increment: (inc + inc2 x FM x 2 pi / 0x7f00) x k1
      R12 = R12 - R12;
      F0 = FLOAT R11 BY R12;
      R2 = DM(0x2e6010);                // (a load between: no single-operand compute after a float one)
      R5 = PASS R5;
      IF EQ JUMP 0x172eae;                   // -> wr_p5_sel_warp.
      R1 = LSHIFT R9 BY 5;
      R12 = 0x2de808;                   // osc 2's reader block, word 2: inc2
      R1 = R12 + R1;
      I0 = R1;
      R1 = DM(0, I0);
      R12 = R12 - R12;
      F1 = FLOAT R1 BY R12;
      F1 = F1 * F2;
      F0 = F0 + F1;
.GLOBAL wr_p5_sel_warp.;
wr_p5_sel_warp.:
      R1 = DM(0x2e6020);                // v
      R1 = PASS R1;
      IF EQ JUMP 0x172eb6;                   // -> wr_p5_sel_put. (no WARP: k1 is 1)
      F0 = F0 * F6;
.GLOBAL wr_p5_sel_put.;
wr_p5_sel_put.:
      R12 = R12 - R12;
      R0 = TRUNC F0 BY R12;
      DM(0x2e6018) = R0;
      R0 = 1;
      DM(0x2e6014) = R0;                // the reader reads PH
.GLOBAL wr_p5_ph_go.;
wr_p5_ph_go.:
      R4 = DM(0x2dde84);
      JUMP 0x170400;                    // -> wr_dclk_pre.
.wr_p5..end:
      .type wr_p5_mid.,STT_FUNC;
