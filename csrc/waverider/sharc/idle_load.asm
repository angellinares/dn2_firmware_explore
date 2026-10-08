// idle_load.asm -- the SHARC's idle time, and how its busy time falls around the dispatch.
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in).
//
// The SHARC runs FreeRTOS, and its idle task (prvIdleTask, sw 0xb88aa6: created by
// vTaskStartScheduler at sw 0xb887db with the name "IDLE", 0x2d0760) spins:
//
//   b88aab  call prvCheckTasksWaitingTermination
//   b88ab2  if more than one task is ready at the idle priority, yield
//   b88abb  jump b88aab                      <- the build makes this `JUMP 0x16f500`
//
// so this runs once a pass. It reads EMUCLK; d = the cycles since the previous pass.
//
// - d < THRESHOLD: the idle task going round. d is added to the idle total, which goes
//   (halves swapped, as the per-frame handler stores reply word 0, so the ColdFire reads
//   a big-endian u32) to reply word 1 of both reply pages.
// - d >= THRESHOLD: the idle task was preempted, and a busy stretch of d cycles ran
//   from the previous pass to now. (frame-max, 2026-10-08: this replaces the A/C split
//   of busy time that reply words 3 and 4 carried; entry_mark.asm's and block_count.asm's
//   MARK0 and MARK are still written, just no longer read here.)
//   - OVERRUNS: a stretch of a frame or more (666,667 cycles at 1 GHz, 1,500 frames/s)
//     means the DSP worked through a frame boundary without idling once. The count,
//     cumulative, goes to reply word 3.
//   - MAX: the longest stretch of each window of 1,500 stretches (about a second at one
//     stretch a frame) goes to reply word 4 when the window closes, so it stays readable
//     for the whole next window. Stretch-level, not per frame: the idle loop's own pass
//     (under 4,096 cycles) is the resolution.
//
// Reply words 1-4 (bytes 4..0x13) are bytes the ColdFire never reads
// (docs/for-digikit-waverider-dsp-stop.md); word 5 is not used, since +0x16 is the
// compressor's gain reduction. The host differences readings (tools/dn2sharc_load.py).
//
// It uses R8-R11, saved to its own area (the render loop's save area is not shared: the
// audio task can preempt the idle task at any instruction), and leaves ASTAT to the idle
// loop, which recomputes what it tests.
//
// PLACEMENT IS FIXED: this code loads at PM sw 0x16f500 (L1 block 1, byte 0x2dea00).
//
// DM (byte addresses, in the state block the build zero-fills):
//   0x2de100  save: R8, R9, R10;  0x2de134  save: R11
//   0x2de10c  EMUCLK at the previous pass
//   0x2de110  idle cycles, cumulative (mod 2^32)
//   0x2de114  passes, cumulative
//   0x2de124  MARK (written by block_count.asm);  0x2de13c  MARK0 (entry_mark.asm)
//   0x2de140  OVERRUNS, cumulative;  0x2de144  the window's longest stretch so far
//   0x2de148  stretches in the window
//   0x2c49d4 / 0x2c59d4, 0x2c49dc / 0x2c59dc, 0x2c49e0 / 0x2c59e0  reply words 1, 3, 4

.SECTION/PM seg_pmco;

.GLOBAL wr_idle.;
wr_idle.:
      DM(0x2de100) = R8;
      DM(0x2de104) = R9;
      DM(0x2de108) = R10;
      DM(0x2de134) = R11;

      R9 = DM(0x2de114);
      R10 = 1;
      R9 = R9 + R10;
      DM(0x2de114) = R9;                // passes

      R8 = EMUCLK;                      // now
      R9 = DM(0x2de10c);                // last
      DM(0x2de10c) = R8;
      R10 = R8 - R9;                    // d
      R11 = 4096;                       // THRESHOLD
      COMPU(R10, R11);
      IF GE JUMP 0x16f53d;              // -> wr_idle_busy.

      R9 = DM(0x2de110);
      R9 = R9 + R10;                    // idle cycles, cumulative
      DM(0x2de110) = R9;
      R10 = LSHIFT R9 BY 16;
      R9 = LSHIFT R9 BY -16;
      R9 = R9 OR R10;                   // halves swapped, as reply word 0
      DM(0x2c49d4) = R9;                // reply word 1, both pages
      DM(0x2c59d4) = R9;
      JUMP 0x16f58a;                    // -> wr_idle_out.

.GLOBAL wr_idle_busy.;
wr_idle_busy.:
      R11 = 666667;                     // a frame, in cycles
      COMPU(R10, R11);
      IF LT JUMP 0x16f55b;              // -> wr_idle_max. (shorter than a frame)
      R9 = DM(0x2de140);
      R11 = 1;
      R9 = R9 + R11;                    // OVERRUNS, cumulative
      DM(0x2de140) = R9;
      R8 = LSHIFT R9 BY 16;
      R9 = LSHIFT R9 BY -16;
      R9 = R9 OR R8;                    // halves swapped, as reply word 0
      DM(0x2c49dc) = R9;                // reply word 3, both pages
      DM(0x2c59dc) = R9;

.GLOBAL wr_idle_max.;
wr_idle_max.:
      R9 = DM(0x2de144);                // the window's longest so far
      COMPU(R10, R9);
      IF LT JUMP 0x16f566;              // -> wr_idle_count. (not longer)
      DM(0x2de144) = R10;

.GLOBAL wr_idle_count.;
wr_idle_count.:
      R9 = DM(0x2de148);
      R11 = 1;
      R9 = R9 + R11;                    // stretches in the window
      R11 = 1500;
      COMPU(R9, R11);
      IF LT JUMP 0x16f587;              // -> wr_idle_keep. (the window is still open)
      R9 = DM(0x2de144);                // the window closes: publish its longest
      R8 = LSHIFT R9 BY 16;
      R9 = LSHIFT R9 BY -16;
      R9 = R9 OR R8;
      DM(0x2c49e0) = R9;                // reply word 4, both pages
      DM(0x2c59e0) = R9;
      R9 = R9 - R9;
      DM(0x2de144) = R9;                // a new window

.GLOBAL wr_idle_keep.;
wr_idle_keep.:
      DM(0x2de148) = R9;                // the count (0 when the window just closed)

.GLOBAL wr_idle_out.;
wr_idle_out.:
      R8 = DM(0x2de100);
      R9 = DM(0x2de104);
      R10 = DM(0x2de108);
      R11 = DM(0x2de134);
      JUMP 0xb88aab;                    // back to the idle loop's top
.wr_idle..end:

// M10b-3: PRST (reader_m9.asm's wr_mod_b had it until the reply report needed the room).
// Entered by JUMP from wr_mod_b's end with R6 = 1 if a note started on this voice and I4
// = the oscillator's reader block; clobbers R0, R1, R12. Back into the loop at
// wr_t5v_modded (machine9_live.asm) either way.
.GLOBAL wr_prst.;
wr_prst.:
      // PRST (m10a3): on a note, the oscillator's phase -- Off leaves it, On restarts
      // it at 0 (every note starts alike), Random sets it from the cycle counter.
      // The reader reads it from its block's phase word, DM(1, I4).
      R6 = PASS R6;
      IF EQ JUMP 0x16f5ce;              // -> wr_prst_back. (no note)
      R0 = DM(0x2de7d4);
      R0 = LSHIFT R0 BY -8;
      R0 = PASS R0;
      IF EQ JUMP 0x16f5ce;              // -> wr_prst_back. (Off: free-running)
      R1 = 1;
      COMP(R0, R1);
      IF EQ JUMP 0x16f5cb;              // -> wr_prst_zero.
      // Random: x = rotate(x, 7) + EMUCLK + 0x6d2b79f5, the state at DM 0x2ddea0
      // (the cycle counter alone repeats: a block starts in step with the audio
      // interrupt, and the emulator's reads 0)
      R0 = DM(0x2ddea0);
      R1 = LSHIFT R0 BY 7;
      R0 = LSHIFT R0 BY -25;
      R12 = PASS R1;
      R0 = R12 + R0;
      R1 = EMUCLK;
      R12 = PASS R0;
      R0 = R12 + R1;
      R12 = 0x6d2b79f5;
      R0 = R12 + R0;
      DM(0x2ddea0) = R0;
      DM(1, I4) = R0;
      JUMP 0x16f5ce;                    // -> wr_prst_back.
.GLOBAL wr_prst_zero.;
wr_prst_zero.:
      R0 = R0 - R0;
      DM(1, I4) = R0;
.GLOBAL wr_prst_back.;
wr_prst_back.:
      JUMP 0x16edf3;                    // -> wr_t5v_modded. (machine9_live.asm)
.wr_prst..end:
      .type wr_prst.,STT_FUNC;
