/* The song position for MOVE's SYNC (sync.c): written into every frame for the DSP. */

#ifndef WAVERIDER_SYNC_H
#define WAVERIDER_SYNC_H

#include "loader.h"

/* The probe can PEEK this. */
struct wr_sync {
    u32 magic;                            /* 'WRSY' */
    u32 position;                         /* the last one sent: 2^32 = SYNC_LOOP sixteenths */
    u32 sixteenths;                       /* since PLAY, mod SYNC_LOOP */
    u32 ticks;                            /* tempo words summed since the last step */
    u32 stops;                            /* STOPs seen (both step bytes 0 for STOP_FRAMES) */
    u32 steps;                            /* step changes seen while playing */
};
extern volatile struct wr_sync wr_sync;

/* the frame ISR, every frame, before the frame may be replaced by a chunk */
void wr_sync_frame(u8 *frame);

#endif
