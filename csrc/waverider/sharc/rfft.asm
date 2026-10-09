// rfft.asm -- Waverider stage 3: the real-input FFT's split steps, around fft.asm.
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in). A frame of N real floats is M = N/2 complex ones, z[n] = x[2n] + i x[2n+1],
// so one M-point complex FFT does the work of an N-point real one:
//
// - forward: fft.asm on z (M points), then wr_rfft_post turns Z into the spectrum
//   X[0..M] in place, packed: slot 0 holds (X[0], X[M]) (both real), slot k X[k];
// - inverse: wr_rfft_pre turns a packed X back into Z in place, then fft.asm with SIGN
//   -1 (M points) gives z, whose (re, im) pairs are x times N (unnormalised).
//
// With W = e^(-2 pi i k / N), for k = 1 .. M/2 (k and M - k together, in place):
//   post: A = Z[k], B = conj Z[M-k], E = (A + B)/2, O = -i (A - B)/2,
//         X[k] = E + W O, X[M-k] = conj(E - W O)            (written in that order)
//   pre:  A = X[k], B = conj X[M-k], E = A + B, O = (A - B) conj W,
//         Z[M-k] = conj(E - i O), Z[k] = E + i O             (written in that order)
//   slot 0, both: (a, b) -> (a + b, a - b).
// At k = M/2 both slots are one; the order leaves the right value (the Python model in
// scripts/sharc_rfft_check.py matches numpy to 1e-14).
//
// Parameter block at DM 0x2e4020 (byte addresses): +0 data, +4 M, +8 TW (fft.asm's
// table), +12 the twiddle stride for N, NMAX * 8 / N bytes, +16 0.5 (float32).
// The forms are fft.asm's. Clobbers R0-R14, I0-I2.
//
// PLACEMENT IS FIXED: this code loads at PM sw 0x16f900 (DM 0x2df200).

.SECTION/PM seg_pmco;

.GLOBAL wr_rfft_post.;
wr_rfft_post.:
      R8 = DM(0x2e4020);                // data
      I0 = R8;
      R0 = DM(0, I0);
      R1 = DM(1, I0);
      F2 = F0 + F1;                     // X[0]
      F3 = F0 - F1;                     // X[M]
      DM(0, I0) = R2;
      DM(1, I0) = R3;
      R13 = 8;
      R9 = R8 + R13;                    // pa = &Z[1]
      R10 = DM(0x2e4024);               // M
      R10 = LSHIFT R10 BY 3;
      R10 = R8 + R10;
      R10 = R10 - R13;                  // pb = &Z[M-1]
      R11 = DM(0x2e4028);               // TW
      R12 = DM(0x2e402c);               // the stride
      R11 = R11 + R12;                  // W^1
      R14 = DM(0x2e4030);               // 0.5

.GLOBAL wr_rfft_post_k.;
wr_rfft_post_k.:
      I0 = R9;
      I1 = R10;
      I2 = R11;
      R0 = DM(0, I0);                   // ar
      R1 = DM(1, I0);                   // ai
      R2 = DM(0, I1);                   // br (B is its conjugate)
      R3 = DM(1, I1);                   // bi
      R4 = DM(0, I2);                   // wr
      R5 = DM(1, I2);                   // wi
      F6 = F0 + F2;
      F6 = F6 * F14;                    // Er
      F7 = F1 - F3;
      F7 = F7 * F14;                    // Ei
      F0 = F0 - F2;                     // Dr
      F1 = F1 + F3;                     // Di
      F1 = F1 * F14;                    // Or = Di/2
      F0 = F0 * F14;                    // Dr/2 = -Oi
      F2 = F4 * F1;
      F3 = F5 * F0;
      F2 = F2 + F3;                     // (W O)r = wr Or + wi Dr/2
      F3 = F5 * F1;
      F0 = F4 * F0;
      F3 = F3 - F0;                     // (W O)i = wi Or - wr Dr/2
      F0 = F6 + F2;
      DM(0, I0) = R0;
      F1 = F7 + F3;
      DM(1, I0) = R1;                   // X[k] = E + W O
      F0 = F6 - F2;
      DM(0, I1) = R0;
      F1 = F3 - F7;
      DM(1, I1) = R1;                   // X[M-k] = conj(E - W O)
      R9 = R9 + R13;
      R10 = R10 - R13;
      R11 = R11 + R12;
      COMPU(R9, R10);
      IF LE JUMP 0x16f928;              // -> wr_rfft_post_k.
      RTS;

.GLOBAL wr_rfft_pre.;
wr_rfft_pre.:
      R8 = DM(0x2e4020);                // data
      I0 = R8;
      R0 = DM(0, I0);
      R1 = DM(1, I0);
      F2 = F0 + F1;
      F3 = F0 - F1;
      DM(0, I0) = R2;
      DM(1, I0) = R3;                   // Z[0] = (X0 + XM, X0 - XM)
      R13 = 8;
      R9 = R8 + R13;
      R10 = DM(0x2e4024);
      R10 = LSHIFT R10 BY 3;
      R10 = R8 + R10;
      R10 = R10 - R13;
      R11 = DM(0x2e4028);
      R12 = DM(0x2e402c);
      R11 = R11 + R12;

.GLOBAL wr_rfft_pre_k.;
wr_rfft_pre_k.:
      I0 = R9;
      I1 = R10;
      I2 = R11;
      R0 = DM(0, I0);
      R1 = DM(1, I0);
      R2 = DM(0, I1);
      R3 = DM(1, I1);
      R4 = DM(0, I2);
      R5 = DM(1, I2);
      F6 = F0 + F2;                     // Er
      F7 = F1 - F3;                     // Ei
      F0 = F0 - F2;                     // Dr
      F1 = F1 + F3;                     // Di
      F2 = F0 * F4;
      F3 = F1 * F5;
      F2 = F2 + F3;                     // Or = Dr wr + Di wi
      F3 = F1 * F4;
      F0 = F0 * F5;
      F3 = F3 - F0;                     // Oi = Di wr - Dr wi
      F0 = F6 + F3;
      DM(0, I1) = R0;
      F1 = F2 - F7;
      DM(1, I1) = R1;                   // Z[M-k] = conj(E - i O)
      F0 = F6 - F3;
      DM(0, I0) = R0;
      F1 = F7 + F2;
      DM(1, I0) = R1;                   // Z[k] = E + i O
      R9 = R9 + R13;
      R10 = R10 - R13;
      R11 = R11 + R12;
      COMPU(R9, R10);
      IF LE JUMP 0x16f98e;              // -> wr_rfft_pre_k.
      RTS;
