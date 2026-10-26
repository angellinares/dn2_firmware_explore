// fsrc.asm -- Waverider page 5 knob D, FSRC: FM's modulator (dnfw.waverider.live, FSRC_NAMES).
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in), run offline in digikit's SHARC executor inside the DN2 1.11 image and checked
// bit for bit against dnfw.waverider.live.render_two (scripts/sharc_waverider_fsrc.py).
//
// FSRC is the frame word at 0x25c48c + 290 + 146t (sound slot 61, FM Tone's record 211, NPOS's
// place): >> 8, at most 2. OSC2 (0) is FM as page5.asm plays it, osc 2 first. SUB (1) and NOIS (2),
// with FM above 0 and a block of 128 or less:
//   - wr_fs_voice (page5.asm's wr_p5_voice): c = FM x f32(1 / 0x7f00), the level's FM factor as for
//     osc 2, and FM state 2, osc 1 first, in the track buffer.
//   - wr_fs_pre (page5.asm's wr_p5_phase, osc 1 under FM): the sub (sub.asm, following osc 1) or the
//     noise (noise.asm) plays into FMB, zeroed, at gain 1.0 (the flag at DM 0x2e24f8 or 0x2e3080
//     makes each return here). Its increment goes to osc 2's reader block, word 2, where taming and
//     the level read inc2: the sub's step, or osc 1's own for the noise. Then FM state 0, so osc 2 and
//     the mix go on as without FM, and on to wr_p5_ph_on, which reads FMB as it reads osc 2's.
//   - wr_fs_sub_ran / wr_fs_sub_skip (formant.asm's way to the sub) and wr_fs_noise (sub.asm's way to
//     the noise): the source that played first adds level x the trim's factor x FMB, the float32 its
//     own render adds, in place of that render; the other plays as before.
//
// DM: 0x2e602c FSRC for the voice in hand (wr_fs_check writes it for every voice); 0x2e6008 the
// track buffer while the source plays into FMB (osc 2's slot under FSRC OSC2).
//
// PLACEMENT IS FIXED at PM sw 0x16f220 (DM 0x2de440, after the increment table; the mix entries are
// fsrc_mix.asm, at sw 0x16f910): the absolute jumps
// below are written for it by scripts/sharc_resolve_jumps.py.

.SECTION/PM seg_pmco;

// wr_p5_voice calls this with R0 = FM and R10 = 146t: FSRC into DM 0x2e602c, 0 unless FM is above 0
// and the block is 128 or less. NE when it is SUB or NOIS. R0 and R10 are kept; clobbers R1-R4, R12, I0.
.GLOBAL wr_fs_check.;
wr_fs_check.:
      R1 = R1 - R1;
      R0 = PASS R0;
      IF EQ JUMP 0x16f23f;              // -> wr_fs_put. (FM 0)
      R4 = PASS R0;
      R2 = DM(0x2dde24);                // the block
      R3 = 128;
      COMP(R2, R3);
      IF GT JUMP 0x16f23f;              // -> wr_fs_put.
      R12 = 0x25c5ae;                   // 0x25c48c + 290: FSRC
      R2 = R12 + R10;
      CALL 0x172cbd;                    // -> wr_p5_word.
      R1 = LSHIFT R0 BY -8;
      R2 = 2;
      R1 = MIN(R1, R2);
      R0 = PASS R4;                     // FM, as it came
.GLOBAL wr_fs_put.;
wr_fs_put.:
      DM(0x2e602c) = R1;
      R1 = PASS R1;
      RTS;

// FSRC SUB or NOIS (R0 = FM): FM's c and the level's factor, then osc 1 first, under FM.
.GLOBAL wr_fs_voice.;
wr_fs_voice.:
      R12 = R12 - R12;
      F4 = FLOAT R0 BY R12;             // FM
      R12 = 0x38010204;                 // f32(1 / 0x7f00): a plain modulator, 1.0 at its peak
      F0 = F4 * F12;
      DM(0x2e600c) = R0;                // c
      R12 = 0x394aa525;                 // f32(2 pi / 0x7f00)
      F0 = F4 * F12;
      DM(0x2e6010) = R0;
      R0 = 2;
      DM(0x2e6004) = R0;                // FM state 2: osc 1 under FM
      JUMP 0x16ed86;                    // -> wr_t5v_osc.

// wr_p5_phase's way for osc 1 under FM (R5 = 2, I4 = the reader block): the modulator into FMB.
.GLOBAL wr_fs_pre.;
wr_fs_pre.:
      R0 = DM(0x2e602c);
      R0 = PASS R0;
      IF EQ JUMP 0x172df7;              // -> wr_p5_ph_on. (OSC2: osc 2 played first)
      R1 = DM(0x2dde88);
      DM(0x2e6008) = R1;                // the track buffer, kept
      R1 = 0x2e6080;
      DM(0x2dde88) = R1;                // FMB in its place
      I0 = R1;
      R1 = R1 - R1;
      R2 = DM(0x2dde24);
      R2 = LSHIFT R2 BY -1;             // two a pass (the block is even)
      LCNTR = R2, DO wr_fs_zero_end. UNTIL LCE;
.NOCOMPRESS;
      DM(I0, M6) = R1;
.GLOBAL wr_fs_zero_end.;
wr_fs_zero_end.:
      DM(I0, M6) = R1;
.COMPRESS;
      R1 = 1;
      COMP(R0, R1);
      IF NE JUMP 0x16f29d;              // -> wr_fs_pre_noise.
      R0 = R0 - R0;
      DM(0x2e24f0) = R0;                // osc 2 has not played: the sub follows osc 1
      R0 = 0x3f800000;
      DM(0x2e24f8) = R0;                // the sub at gain 1.0, back here
      CALL 0x17100c;                    // -> wr_sub_go.
      R11 = PASS R10;                   // inc2: the sub's step
      JUMP 0x16f2a8;                    // -> wr_fs_pre_end.
.GLOBAL wr_fs_pre_noise.;
wr_fs_pre_noise.:
      R0 = 0x3f800000;
      DM(0x2e3080) = R0;                // the noise at gain 1.0, at NOIS 0 too, back here
      CALL 0x171300;                    // -> wr_noise.
      R11 = DM(2, I4);                  // inc2: osc 1's own
.GLOBAL wr_fs_pre_end.;
wr_fs_pre_end.:
      R0 = R0 - R0;
      DM(0x2e24f8) = R0;
      DM(0x2e3080) = R0;
      DM(0x2e6004) = R0;                // FM state 0: osc 2 and the mix as without FM
      R1 = DM(0x2e6008);
      DM(0x2dde88) = R1;                // the track buffer back
      R0 = DM(0x2dde80);
      R1 = 16;
      R9 = R1 - R0;                     // t
      R1 = LSHIFT R9 BY 5;
      R12 = 0x2de808;                   // osc 2's reader block, word 2: inc2
      R1 = R12 + R1;
      I0 = R1;
      DM(0, I0) = R11;
      R5 = 2;                           // osc 1 under FM (wr_p5_ph_on)
      JUMP 0x172df7;                    // -> wr_p5_ph_on.

.wr_fs..end:
      .type wr_fs_check.,STT_FUNC;
