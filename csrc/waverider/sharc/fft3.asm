// fft3.asm -- Waverider stage 3: the complex FFT on split arrays, two butterflies an issue.
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in) and the post-fixes in scripts/sharc_waverider_m3.py. Written from the
// SC58x/2158x PRM, for speed:
//
// - Split format: the real parts in one array, the imaginary parts in another, so a SIMD
//   access (PRM "DAG Transfers in SIMD Mode": the named word to PEx, the next one to PEy)
//   gives two neighbouring points. Butterflies k and k+1 of a stage sit next to each
//   other with their twiddles next to each other too, so PEx runs one and PEy the other.
// - The butterfly is the multifunction forms (PRM "Multifunction Computations"): a
//   multiply (F0-F3 by F4-F7) with an add, a subtract or both (F8-F11 with F12-F15), and
//   a DM and a PM transfer in the same instruction. The real parts move on DM (DAG1), the
//   imaginary on PM (DAG2). Four multiplies, two adds and two add/subtract pairs for
//   two butterflies: four instructions, software-pipelined three deep so no result feeds
//   the next instruction's compute (PRM Table 4-36: a float result used by the next
//   compute stalls 1). Each instruction's registers are read before any is written, so
//   a load and a use of one register share an instruction.
// - Twiddles per stage, contiguous: TWR[h + k] = cos(pi k / h), TWI[h + k] = -sin(pi k / h)
//   for a stage of half-width h, k = 0 .. h-1 (w = e^(-i pi k / h)).
// - Each stage runs its two loops whichever way round makes the inner one longer: over
//   the groups for a twiddle pair while h^2 <= M (four instructions), over the twiddle
//   pairs of a group after (five: the twiddles load too).
// - The first pass is the bit reversal and stages 0 and 1 (a radix-4 butterfly, its
//   twiddles 1 and -i: adds only), SISD, from the source arrays to the destination ones,
//   ten instructions a group of four. BITREV (PRM "Bit-Reverse Instruction") makes each
//   group's source address: a counter whose low bits are the reversed source base,
//   stepped 2^(32 - log2 M) a group.
// - Hardware loops; the inner ones F1-active (`(F)`: no flush on exit, PRM "Counter-
//   Based F1-Active Loop"). Every instruction is 48-bit (.NOCOMPRESS): a loop's last
//   eleven must be.
// - The inverse: swap the real and imaginary pointers of both source and destination
//   (i conj(.) on the way in and out); the result is unscaled.
//
// Parameter block at DM 0x2e4060 (byte addresses):
//   +0 source re  +4 source im  +8 dest re  +12 dest im  +16 M (complex points, 8 or
//   more, a power of two)  +20 log2 M  +24 TWR  +28 TWI
// The source re array must be aligned to 4 M bytes (the BITREV counter); the source im
// array is reached from it by a fixed offset, so any address. (The inverse passes the
// imaginary array as source re: align both.) Past the destination arrays
// up to 16 h + 32 bytes (h = sqrt M at most) and past the twiddle tables 32 bytes are read
// (a stage's last loads run ahead), never written.
// Scratch at DM 0x2e4080: +0 h, +4 log2 h.
//
// Clobbers R0-R15 and S0-S15, I0-I6, I8-I14, M0-M4, M8-M12, the loop counters; leaves
// MODE1's PEYEN clear. Not ABI-clean: the caller saves what it needs. It leaves the C
// runtime's constants alone (M5 = M13 = 0, M6 = M14 = 1, M7 = M15 = -1), and I7 and the
// L and B registers: code an interrupt can preempt must, as stock's interrupt entry
// pushes through DM(I7, M7) at once (sw 0x1c0ad9). SIMD is safe there: no stock code
// writes MMASK, whose default clears PEYEN when an interrupt pushes the status stack
// (PRM "Interrupt Mask Mode").
//
// PLACEMENT IS FIXED: this code loads at PM sw 0x171000 (DM 0x2e2000).

.SECTION/PM seg_pmco;
.NOCOMPRESS;

.GLOBAL wr_fft3.;
wr_fft3.:
      // -- the first pass: SISD, bit reversal and stages 0 and 1, source -> destination.
      //    A group (4 points) a window of 10 instructions: its eight loads on DM through
      //    I6 (the real parts at bit-reversed 4g + 0, M/2, M/4, 3M/4, then on to the
      //    imaginary array), its stage-0 add/subtracts as they arrive, its stage-1 ones
      //    and its eight stores (on PM through I10) in the next window, beside the next
      //    group's loads. Two register banks, R0-R7 and R8-R15, take turns.
      R8 = DM(0x2e4070);                // M
      R9 = DM(0x2e4074);                // log2 M
      R10 = DM(0x2e4060);
      I1 = R10;                         // source re
      BITREV(I1, 0);                    // the counter: the reversed base
      R11 = DM(0x2e4064);
      R11 = R11 - R10;
      R11 = ASHIFT R11 BY -2;           // source im - re, in words
      R12 = LSHIFT R8 BY -2;            // M/4
      R13 = R12 + R12;
      R13 = R13 + R12;                  // 3M/4
      R11 = R11 - R13;
      M4 = R11;                         // re x3 (3M/4) to im x0
      R11 = -R12;                       // -M/4
      M3 = R11;
      R11 = LSHIFT R8 BY -1;
      M2 = R11;                         // M/2
      R11 = 32;
      R11 = R11 - R9;
      R13 = 1;
      R13 = LSHIFT R13 BY R11;
      M1 = R13;                         // 2^(32 - log2 M): a group's step of the counter
      R10 = DM(0x2e4068);
      I10 = R10;                        // destination re
      R11 = DM(0x2e406c);
      R11 = R11 - R10;
      R11 = ASHIFT R11 BY -2;           // destination im - re, in words
      M8 = 1;
      R13 = R11 - 1;
      R13 = R13 - 1;
      R13 = R13 - 1;
      M9 = R13;                        // re y3 to im y0
      R13 = 1;
      R13 = R13 - R11;
      M10 = R13;                        // im y3 to the next group's re y0
      R12 = LSHIFT R8 BY -3;
      R12 = R12 - 1;                    // the loop: M/8 - 1 pairs of windows after the first two
      M11 = R12;
      IF EQ JUMP wr_fft3_p1_small.;     // M = 8: two groups, no loop
      I6 = BITREV(I1, 0);
      R0 = DM(I6, M2);
      R1 = DM(I6, M3);
      F0 = F0 + F1, F1 = F0 - F1, R2 = DM(I6, M2);
      R3 = DM(I6, M4);
      F2 = F2 + F3, F3 = F2 - F3, R4 = DM(I6, M2);
      R5 = DM(I6, M3);
      F4 = F4 + F5, F5 = F4 - F5, R6 = DM(I6, M2);
      F0 = F0 + F2, F2 = F0 - F2, R7 = DM(I6, M2);
      F6 = F6 + F7, F7 = F6 - F7, MODIFY(I1, M1);
      I6 = BITREV(I1, 0);
      F1 = F1 + F7, F7 = F1 - F7, R8 = DM(I6, M2), PM(I10, M8) = R0;
      F4 = F4 + F6, F6 = F4 - F6, R9 = DM(I6, M3), PM(I10, M8) = R1;
      F8 = F8 + F9, F9 = F8 - F9, R10 = DM(I6, M2), PM(I10, M8) = R2;
      F5 = F5 + F3, F3 = F5 - F3, R11 = DM(I6, M4), PM(I10, M9) = R7;
      F10 = F10 + F11, F11 = F10 - F11, R12 = DM(I6, M2), PM(I10, M8) = R4;
      R13 = DM(I6, M3), PM(I10, M8) = R3;
      F12 = F12 + F13, F13 = F12 - F13, R14 = DM(I6, M2), PM(I10, M8) = R6;
      F8 = F8 + F10, F10 = F8 - F10, R15 = DM(I6, M2), PM(I10, M10) = R5;
      F14 = F14 + F15, F15 = F14 - F15, MODIFY(I1, M1);
      LCNTR = M11, DO wr_fft3_p1_end. UNTIL LCE (F);
      I6 = BITREV(I1, 0);
      F9 = F9 + F15, F15 = F9 - F15, R0 = DM(I6, M2), PM(I10, M8) = R8;
      F12 = F12 + F14, F14 = F12 - F14, R1 = DM(I6, M3), PM(I10, M8) = R9;
      F0 = F0 + F1, F1 = F0 - F1, R2 = DM(I6, M2), PM(I10, M8) = R10;
      F13 = F13 + F11, F11 = F13 - F11, R3 = DM(I6, M4), PM(I10, M9) = R15;
      F2 = F2 + F3, F3 = F2 - F3, R4 = DM(I6, M2), PM(I10, M8) = R12;
      R5 = DM(I6, M3), PM(I10, M8) = R11;
      F4 = F4 + F5, F5 = F4 - F5, R6 = DM(I6, M2), PM(I10, M8) = R14;
      F0 = F0 + F2, F2 = F0 - F2, R7 = DM(I6, M2), PM(I10, M10) = R13;
      F6 = F6 + F7, F7 = F6 - F7, MODIFY(I1, M1);
      I6 = BITREV(I1, 0);
      F1 = F1 + F7, F7 = F1 - F7, R8 = DM(I6, M2), PM(I10, M8) = R0;
      F4 = F4 + F6, F6 = F4 - F6, R9 = DM(I6, M3), PM(I10, M8) = R1;
      F8 = F8 + F9, F9 = F8 - F9, R10 = DM(I6, M2), PM(I10, M8) = R2;
      F5 = F5 + F3, F3 = F5 - F3, R11 = DM(I6, M4), PM(I10, M9) = R7;
      F10 = F10 + F11, F11 = F10 - F11, R12 = DM(I6, M2), PM(I10, M8) = R4;
      R13 = DM(I6, M3), PM(I10, M8) = R3;
      F12 = F12 + F13, F13 = F12 - F13, R14 = DM(I6, M2), PM(I10, M8) = R6;
      F8 = F8 + F10, F10 = F8 - F10, R15 = DM(I6, M2), PM(I10, M10) = R5;
.GLOBAL wr_fft3_p1_end.;
wr_fft3_p1_end.:
      F14 = F14 + F15, F15 = F14 - F15, MODIFY(I1, M1);
      F9 = F9 + F15, F15 = F9 - F15, PM(I10, M8) = R8;
      F12 = F12 + F14, F14 = F12 - F14, PM(I10, M8) = R9;
      PM(I10, M8) = R10;
      F13 = F13 + F11, F11 = F13 - F11, PM(I10, M9) = R15;
      PM(I10, M8) = R12;
      PM(I10, M8) = R11;
      PM(I10, M8) = R14;
      PM(I10, M10) = R13;
      JUMP wr_fft3_stages.;
.GLOBAL wr_fft3_p1_small.;
wr_fft3_p1_small.:
      I6 = BITREV(I1, 0);
      R0 = DM(I6, M2);
      R1 = DM(I6, M3);
      F0 = F0 + F1, F1 = F0 - F1, R2 = DM(I6, M2);
      R3 = DM(I6, M4);
      F2 = F2 + F3, F3 = F2 - F3, R4 = DM(I6, M2);
      R5 = DM(I6, M3);
      F4 = F4 + F5, F5 = F4 - F5, R6 = DM(I6, M2);
      F0 = F0 + F2, F2 = F0 - F2, R7 = DM(I6, M2);
      F6 = F6 + F7, F7 = F6 - F7, MODIFY(I1, M1);
      I6 = BITREV(I1, 0);
      F1 = F1 + F7, F7 = F1 - F7, R8 = DM(I6, M2), PM(I10, M8) = R0;
      F4 = F4 + F6, F6 = F4 - F6, R9 = DM(I6, M3), PM(I10, M8) = R1;
      F8 = F8 + F9, F9 = F8 - F9, R10 = DM(I6, M2), PM(I10, M8) = R2;
      F5 = F5 + F3, F3 = F5 - F3, R11 = DM(I6, M4), PM(I10, M9) = R7;
      F10 = F10 + F11, F11 = F10 - F11, R12 = DM(I6, M2), PM(I10, M8) = R4;
      R13 = DM(I6, M3), PM(I10, M8) = R3;
      F12 = F12 + F13, F13 = F12 - F13, R14 = DM(I6, M2), PM(I10, M8) = R6;
      F8 = F8 + F10, F10 = F8 - F10, R15 = DM(I6, M2), PM(I10, M10) = R5;
      F14 = F14 + F15, F15 = F14 - F15, MODIFY(I1, M1);
      F9 = F9 + F15, F15 = F9 - F15, PM(I10, M8) = R8;
      F12 = F12 + F14, F14 = F12 - F14, PM(I10, M8) = R9;
      PM(I10, M8) = R10;
      F13 = F13 + F11, F11 = F13 - F11, PM(I10, M9) = R15;
      PM(I10, M8) = R12;
      PM(I10, M8) = R11;
      PM(I10, M8) = R14;
      PM(I10, M10) = R13;

.GLOBAL wr_fft3_stages.;
wr_fft3_stages.:
      // -- the stages, h = 4 .. M/2, in SIMD
      R9 = DM(0x2e4074);                // log2 M (R8-R15 were the first pass's second bank)
      R10 = 4;
      DM(0x2e4080) = R10;               // h
      R10 = 2;
      DM(0x2e4084) = R10;               // log2 h
      M1 = 2;                           // a twiddle pair, in words
      M9 = 2;
      R10 = LSHIFT R9 BY -1;
      R10 = R10 - 1;                    // stages over the groups: floor(log2 M / 2) - 1
      R11 = R9 - R10;
      R11 = R11 - 1;
      R11 = R11 - 1;                    // the rest
      DM(0x2e4088) = R11;
      R10 = PASS R10;
      IF EQ JUMP wr_fft3_ki.;

      // -- over the groups for each twiddle pair (h^2 <= M)
      LCNTR = R10, DO wr_fft3_gi_stage_end. UNTIL LCE;
      R8 = DM(0x2e4070);                // M
      R10 = DM(0x2e4080);               // h
      R12 = DM(0x2e4084);               // log2 h
      R11 = R10 + R10;                  // the span, 2h points, in words
      M0 = R11;
      M8 = R11;
      R11 = LSHIFT R10 BY 2;            // h points in bytes: a to b
      M2 = R11;
      M10 = R11;
      R13 = DM(0x2e4078);
      R13 = R13 + R11;
      I4 = R13;                         // TWR + 4h
      R13 = DM(0x2e407c);
      R13 = R13 + R11;
      I12 = R13;                        // TWI + 4h
      R13 = DM(0x2e4068);
      I5 = R13;                         // pair 0's a, re
      R13 = DM(0x2e406c);
      I13 = R13;                        // and im
      R13 = R12 + 1;
      R13 = -R13;
      R14 = LSHIFT R8 BY R13;           // G = M / 2h: the groups
      R14 = R14 - 1;
      M3 = R14;                         // the loop runs G - 1 (three iterations peeled)
      R13 = LSHIFT R10 BY -1;           // h/2 pairs
      R10 = R10 + R10;
      DM(0x2e4080) = R10;
      R12 = R12 + 1;
      DM(0x2e4084) = R12;
      BIT SET MODE1 0x200000;           // PEYEN
      NOP;
      LCNTR = R13, DO wr_fft3_gi_pair_end. UNTIL LCE;
      R0 = DM(I4, M1), R1 = PM(I12, M9);                        // (wr, wr'), (wi, wi')
      I0 = I5;
      I2 = I5;
      I1 = I5;
      I3 = I5;
      I8 = I13;
      I10 = I13;
      I9 = I13;
      I11 = I13;
      MODIFY(I1, M2);
      MODIFY(I3, M2);
      MODIFY(I9, M10);
      MODIFY(I11, M10);
      MODIFY(I5, 8);                    // the next pair
      MODIFY(I13, 8);
      R4 = DM(I1, M0), R5 = PM(I9, M8);                         // y0
      F8 = F0 * F4;      // iteration 0, no stores
      F12 = F1 * F5;
      F9 = F0 * F5, R10 = DM(I0, M0);
      F13 = F1 * F4, F14 = F8 - F12, R4 = DM(I1, M0), R5 = PM(I9, M8);
      F8 = F0 * F4;      // iteration 1, no stores
      F12 = F1 * F5, F15 = F9 + F13;
      F9 = F0 * F5, F2 = F10 + F14, F3 = F10 - F14, R10 = DM(I0, M0), R11 = PM(I8, M8);
      F13 = F1 * F4, F14 = F8 - F12, R4 = DM(I1, M0), R5 = PM(I9, M8);
      F8 = F0 * F4, F6 = F11 + F15, F7 = F11 - F15, DM(I2, M0) = R2;      // iteration 2, a.re b.re b.im of 0
      F12 = F1 * F5, F15 = F9 + F13, DM(I3, M0) = R3, PM(I11, M8) = R7;
      F9 = F0 * F5, F2 = F10 + F14, F3 = F10 - F14, R10 = DM(I0, M0), R11 = PM(I8, M8);
      F13 = F1 * F4, F14 = F8 - F12, R4 = DM(I1, M0), R5 = PM(I9, M8);
      LCNTR = M3, DO wr_fft3_gi_end. UNTIL LCE (F);   // iterations 3 .. n+1
      F8 = F0 * F4, F6 = F11 + F15, F7 = F11 - F15, DM(I2, M0) = R2, PM(I10, M8) = R6;   // m1 = wr yr; xi +- ti (j-2); a.re (j-2), a.im (j-3)
      F12 = F1 * F5, F15 = F9 + F13, DM(I3, M0) = R3, PM(I11, M8) = R7;   // m2 = wi yi; ti (j-1); b.re, b.im (j-2)
      F9 = F0 * F5, F2 = F10 + F14, F3 = F10 - F14, R10 = DM(I0, M0), R11 = PM(I8, M8);   // m3 = wr yi; xr +- tr (j-1); xr (j), xi (j-1)
.GLOBAL wr_fft3_gi_end.;
wr_fft3_gi_end.:
      F13 = F1 * F4, F14 = F8 - F12, R4 = DM(I1, M0), R5 = PM(I9, M8);   // m4 = wi yr; tr (j); y (j+1)
      PM(I10, M8) = R6;                // a.im of the last
.GLOBAL wr_fft3_gi_pair_end.;
wr_fft3_gi_pair_end.:
      NOP;
      BIT CLR MODE1 0x200000;
      NOP;
.GLOBAL wr_fft3_gi_stage_end.;
wr_fft3_gi_stage_end.:
      NOP;

      // -- over the twiddle pairs of each group (h^2 > M)
.GLOBAL wr_fft3_ki.;
wr_fft3_ki.:
      R10 = DM(0x2e4088);
      M0 = 2;                           // a pair of points, in words
      M8 = 2;
      LCNTR = R10, DO wr_fft3_ki_stage_end. UNTIL LCE;
      R8 = DM(0x2e4070);                // M
      R10 = DM(0x2e4080);               // h
      R12 = DM(0x2e4084);               // log2 h
      R11 = LSHIFT R10 BY 2;            // 4h bytes: a to b
      M2 = R11;
      M10 = R11;
      R13 = R11 + R11;                  // 8h bytes: a group
      M3 = R13;
      M11 = R13;
      R13 = DM(0x2e4078);
      R13 = R13 + R11;
      I6 = R13;                         // TWR + 4h
      R13 = DM(0x2e407c);
      R13 = R13 + R11;
      I14 = R13;                        // TWI + 4h
      R13 = DM(0x2e4068);
      I5 = R13;
      R13 = DM(0x2e406c);
      I13 = R13;
      R13 = LSHIFT R10 BY -1;           // h/2 pairs
      R13 = R13 - 1;
      M4 = R13;                         // the loop runs h/2 - 1 (three iterations peeled)
      R13 = R12 + 1;
      R13 = -R13;
      R14 = LSHIFT R8 BY R13;           // G = M / 2h
      R10 = R10 + R10;
      DM(0x2e4080) = R10;
      R12 = R12 + 1;
      DM(0x2e4084) = R12;
      BIT SET MODE1 0x200000;           // PEYEN
      NOP;
      LCNTR = R14, DO wr_fft3_ki_group_end. UNTIL LCE;
      I0 = I5;
      I2 = I5;
      I1 = I5;
      I3 = I5;
      I8 = I13;
      I10 = I13;
      I9 = I13;
      I11 = I13;
      I4 = I6;
      I12 = I14;
      MODIFY(I1, M2);
      MODIFY(I3, M2);
      MODIFY(I9, M10);
      MODIFY(I11, M10);
      MODIFY(I5, M3);                   // the next group
      MODIFY(I13, M11);
      R0 = DM(I4, M1), R1 = PM(I12, M9);                        // w0
      R4 = DM(I1, M0), R5 = PM(I9, M8);                         // y0
      F8 = F0 * F4;      // iteration 0, no stores
      F12 = F1 * F5;
      F9 = F0 * F5, R10 = DM(I0, M0);
      F13 = F1 * F4, F14 = F8 - F12, R4 = DM(I1, M0), R5 = PM(I9, M8);
      R0 = DM(I4, M1), R1 = PM(I12, M9);
      F8 = F0 * F4;      // iteration 1, no stores
      F12 = F1 * F5, F15 = F9 + F13;
      F9 = F0 * F5, F2 = F10 + F14, F3 = F10 - F14, R10 = DM(I0, M0), R11 = PM(I8, M8);
      F13 = F1 * F4, F14 = F8 - F12, R4 = DM(I1, M0), R5 = PM(I9, M8);
      R0 = DM(I4, M1), R1 = PM(I12, M9);
      F8 = F0 * F4, F6 = F11 + F15, F7 = F11 - F15, DM(I2, M0) = R2;      // iteration 2, a.re b.re b.im of 0
      F12 = F1 * F5, F15 = F9 + F13, DM(I3, M0) = R3, PM(I11, M8) = R7;
      F9 = F0 * F5, F2 = F10 + F14, F3 = F10 - F14, R10 = DM(I0, M0), R11 = PM(I8, M8);
      F13 = F1 * F4, F14 = F8 - F12, R4 = DM(I1, M0), R5 = PM(I9, M8);
      R0 = DM(I4, M1), R1 = PM(I12, M9);
      LCNTR = M4, DO wr_fft3_ki_end. UNTIL LCE (F);   // iterations 3 .. n+1
      F8 = F0 * F4, F6 = F11 + F15, F7 = F11 - F15, DM(I2, M0) = R2, PM(I10, M8) = R6;   // m1 = wr yr; xi +- ti (j-2); a.re (j-2), a.im (j-3)
      F12 = F1 * F5, F15 = F9 + F13, DM(I3, M0) = R3, PM(I11, M8) = R7;   // m2 = wi yi; ti (j-1); b.re, b.im (j-2)
      F9 = F0 * F5, F2 = F10 + F14, F3 = F10 - F14, R10 = DM(I0, M0), R11 = PM(I8, M8);   // m3 = wr yi; xr +- tr (j-1); xr (j), xi (j-1)
      F13 = F1 * F4, F14 = F8 - F12, R4 = DM(I1, M0), R5 = PM(I9, M8);   // m4 = wi yr; tr (j); y (j+1)
.GLOBAL wr_fft3_ki_end.;
wr_fft3_ki_end.:
      R0 = DM(I4, M1), R1 = PM(I12, M9);   // w (j+1)
      PM(I10, M8) = R6;                // a.im of the last
.GLOBAL wr_fft3_ki_group_end.;
wr_fft3_ki_group_end.:
      NOP;
      BIT CLR MODE1 0x200000;
      NOP;
.GLOBAL wr_fft3_ki_stage_end.;
wr_fft3_ki_stage_end.:
      NOP;
      RTS;
