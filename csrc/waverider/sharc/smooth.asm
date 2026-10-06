// smooth.asm -- Waverider M10b-2: SMTH, a glide on each oscillator's POS.
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in), run offline in digikit's SHARC executor and checked bit for bit against
// dnfw.waverider.live.smooth (scripts/sharc_waverider_m5.py).
//
// Entered by `JUMP` from machine9_live.asm in place of its `DM(3, I4) = R4` (the reader
// block's pos), once per voice and oscillator, after MOVE and the clamp; left by `JUMP`
// back to wr_t5v_smoothed. SMTH is osc 1's DEC (slot 42, frame offset 252 + 146t) and
// osc 2's WDTH (45, 258 + 146t), 0..127, default 127: a one-pole glide per block,
//
//   s = s + (POS - s) x k[SMTH]     (float32, k from the table at DM 0x2e0c00)
//
// with k[127] = 1.0 exactly, so SMTH 127 -- every sound saved before SMTH -- plays POS
// itself, bit for bit. A note on this voice (the frame's note mask, offset 34, bit t)
// snaps s to POS. The state, a float per voice and oscillator, is at DM 0x2e1200 +
// 4 (2t + osc), zeros at boot.
//
// In: R4 = POS (Q16 frames), R9 = t, I4 = the reader block. Out: DM(3, I4) = trunc(s).
// Clobbers R0-R3, R10-R12, I0. Keeps R5-R9, R13-R15 (machine9_live.asm's TUN1 is in
// R13), I1-I5. Only forms the firmware itself uses, and every add has R8-R15 first
// (see reader_m5.asm).
//
// PLACEMENT IS FIXED at PM sw 0x170300 (DM 0x2e0600).

.SECTION/PM seg_pmco;

.GLOBAL wr_smooth.;
wr_smooth.:
      // SMTH: the voice's frame, 0x25c48c + 146t, + 252 + 6 x osc
      R10 = LSHIFT R9 BY 7;
      R11 = LSHIFT R9 BY 4;
      R10 = R10 + R11;
      R11 = LSHIFT R9 BY 1;
      R10 = R10 + R11;                  // 146t
      R0 = DM(0x2de6c4);                // the oscillator
      R1 = LSHIFT R0 BY 1;
      R2 = LSHIFT R0 BY 2;
      R12 = PASS R2;
      R1 = R12 + R1;                    // 6 x osc
      R12 = 0x25c588;                   // 0x25c48c + 252
      R1 = R12 + R1;
      R1 = R10 + R1;
      R2 = -4;
      R2 = R1 AND R2;
      I0 = R2;
      R2 = DM(0, I0);                   // the word holding SMTH
      R3 = 2;
      R3 = R1 AND R3;
      IF EQ JUMP 0x170330;              // -> wr_smooth_low. (2 mod 4: the high half)
      R2 = LSHIFT R2 BY -16;
.GLOBAL wr_smooth_low.;
wr_smooth_low.:
      R3 = 0xffff;
      R2 = R2 AND R3;
      R2 = LSHIFT R2 BY -8;
      R3 = 127;
      R2 = MIN(R2, R3);
      R2 = LSHIFT R2 BY 2;
      R12 = 0x2e0c00;                   // k[0..127], float32
      R2 = R12 + R2;
      I0 = R2;
      R2 = DM(0, I0);                   // k

      // the state: 0x2e1200 + 4 (2t + osc)
      R3 = LSHIFT R9 BY 1;
      R12 = PASS R0;
      R3 = R12 + R3;
      R3 = LSHIFT R3 BY 2;
      R12 = 0x2e1200;
      R3 = R12 + R3;
      I0 = R3;
      R12 = R12 - R12;
      F1 = FLOAT R4 BY R12;             // POS, exact in float32

      // a note on this voice snaps the glide to POS
      R0 = DM(0x25c4ac);                // the frame's offset 32..35: the note mask high
      R0 = LSHIFT R0 BY -16;
      R3 = R3 - R3;
      R3 = R3 - R9;
      R0 = LSHIFT R0 BY R3;             // >> t
      R3 = 1;
      R0 = R0 AND R3;
      IF NE JUMP 0x170371;              // -> wr_smooth_set.
      R0 = DM(0, I0);                   // s
      F3 = F1 - F0;                     // POS - s
      F3 = F3 * F2;                     // x k
      F1 = F0 + F3;                     // s + (POS - s) x k
.GLOBAL wr_smooth_set.;
wr_smooth_set.:
      DM(0, I0) = R1;
      R4 = TRUNC F1;
      DM(3, I4) = R4;                   // the reader block's pos
      JUMP 0x16ee23;                    // -> wr_t5v_smoothed.
.wr_smooth..end:
      .type wr_smooth.,STT_FUNC;
