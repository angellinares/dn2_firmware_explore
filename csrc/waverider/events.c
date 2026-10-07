/* Two events the page needs and cannot see from the UI task: note-ons per voice, and
 * clears of a track's preset.
 *
 * - **Note-ons:** frame bytes 34..35 are the note-on mask, one bit per voice, set for
 *   one frame only (docs/drive-load-command.md, "The trigger masks are one-frame
 *   events"). The UI polls far slower than the 1,500 frames a second, so the frame hook
 *   (loader.c, wr_frame_src) counts them here, a counter per voice, on every frame.
 * - **Clears:** CLEAR TRK PRESET (TRK + PLAY, 0x40071e80) asks the track's machine at
 *   0x40071eb6, and that call comes here (dnfw.waverider.drive). This counts the clear,
 *   then answers with the real machine type, as the identity sites do.
 *
 * The page reads both (pool.h, wr_drive_head): after a clear, a voice's stored state
 * (what it last played) is the old preset's, so the page ignores each voice until it
 * has played a note since the clear (owner, 2026-10-05: the old modulation stayed on the
 * page after a clear, until PLAY). Counters only grow; readers compare, never reset. */

#include "loader.h"
#include "events.h"

#ifndef WR_RAW_TRACK
#error "WR_RAW_TRACK: the raw machine-type getter's address (dnfw.waverider.coldfire raw_track)"
#endif
#define RAW_TRACK ((u32 (*)(void *))(WR_RAW_TRACK))

extern volatile struct trace_ring wr_scope_ring;           /* scope_feed.c */
volatile struct wr_events wr_events __attribute__((section(".data"))) =
    { 0x57524556u, 0, { 0 }, 0, 0xFF, { 0, 0 }, &wr_scope_ring };

/* the frame ISR, every frame: count each voice whose note-on bit is set */
void wr_note_seen(const u8 *frame)
{
    u32 on = (u32)frame[34] << 8 | frame[35];
    for (u32 v = 0; on; v++, on >>= 1)
        if (on & 1)
            wr_events.notes[v]++;
}

/* 0x40071eb6's call: the clear asks the track's machine type */
u32 wr_clear_type(void *track)
{
    wr_events.clears++;
    return RAW_TRACK(track);
}
