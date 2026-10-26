// fsrc_mix.asm -- Waverider page 5 knob D, FSRC: the mix entries (fsrc.asm has the rest; its header
// says what FSRC does). Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and
// never linked in), checked bit for bit against dnfw.waverider.live.render_two.
//
// PLACEMENT IS FIXED at PM sw 0x16f910 (DM 0x2df220, in shapes.asm's slot after its code): the
// absolute jumps below are written for it by scripts/sharc_resolve_jumps.py.

.SECTION/PM seg_pmco;

// formant.asm's two ways to the sub: under FSRC SUB the sub has played; its level x FMB, then the noise.
.GLOBAL wr_fs_sub_ran.;
wr_fs_sub_ran.:
      R0 = DM(0x2e602c);
      R1 = 1;
      COMP(R0, R1);
      IF NE JUMP 0x171000;              // -> wr_sub_ran.
      JUMP 0x16f925;                    // -> wr_fs_sub_mix.
.GLOBAL wr_fs_sub_skip.;
wr_fs_sub_skip.:
      R0 = DM(0x2e602c);
      R1 = 1;
      COMP(R0, R1);
      IF NE JUMP 0x171008;              // -> wr_sub_skip.
.GLOBAL wr_fs_sub_mix.;
wr_fs_sub_mix.:
      R12 = 0x25c598;                   // 0x25c48c + 268: SUB
      CALL 0x16f94c;                    // -> wr_fs_level.
      IF EQ JUMP 0x171300;              // -> wr_noise. (SUB 0: the sub is not heard)
      CALL 0x16f962;                    // -> wr_fs_add.
      JUMP 0x171300;                    // -> wr_noise.

// sub.asm's two ways to the noise: under FSRC NOIS the noise has played; its level x FMB.
.GLOBAL wr_fs_noise.;
wr_fs_noise.:
      R0 = DM(0x2e602c);
      R1 = 2;
      COMP(R0, R1);
      IF NE JUMP 0x171300;              // -> wr_noise.
      R12 = 0x25c5a0;                   // 0x25c48c + 276: NOIS
      CALL 0x16f94c;                    // -> wr_fs_level.
      IF EQ JUMP 0x16eeb3;              // -> wr_t5v_next. (NOIS 0: the noise is not heard)
      CALL 0x16f962;                    // -> wr_fs_add.
      JUMP 0x16eeb3;                    // -> wr_t5v_next.

// R12 = a level's frame address at t 0: F6 = level x the trim's factor, as sub.asm and noise.asm form
// it. EQ at level 0, else NE (FLOAT's flags). Clobbers R0-R3, R6, R9-R12, I0.
.GLOBAL wr_fs_level.;
wr_fs_level.:
      CALL 0x172ca8;                    // -> wr_p5_t146.
      R2 = R12 + R10;
      CALL 0x172cbd;                    // -> wr_p5_word.
      R0 = PASS R0;
      IF EQ RTS;
      R12 = R12 - R12;
      F6 = FLOAT R0 BY R12;
      R12 = DM(0x2de6c8);               // the trim's factor for this voice (trim.asm)
      F6 = F6 * F12;
      RTS;

// b += F6 x FMB over the block, in the track buffer. Clobbers R0-R2, R13, I0, I1.
.GLOBAL wr_fs_add.;
wr_fs_add.:
      R0 = DM(0x2dde88);
      I0 = R0;
      R0 = 0x2e6080;
      I1 = R0;
      R13 = DM(0x2dde24);
      LCNTR = R13, DO wr_fs_add_end. UNTIL LCE;
.NOCOMPRESS;
      R1 = DM(0, I0);
      R2 = DM(I1, M6);
      F2 = F6 * F2;
      F1 = F1 + F2;
.GLOBAL wr_fs_add_end.;
wr_fs_add_end.:
      DM(I0, M6) = F1;
.COMPRESS;
      RTS;
.wr_fsm..end:
      .type wr_fs_sub_ran.,STT_FUNC;
