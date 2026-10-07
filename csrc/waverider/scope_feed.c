/* Page 4's scope, the capture half: every frame (the ISR, loader.c wr_frame_src), the
 * last block of the track the page shows (wr_events.scope_track, page.c) into a ring the
 * page draws from (wr_events.scope). The audio comes from dn2/audio_tap; the ring is
 * ui/trace_ring. 0xFF: no track, nothing done. */
#include "events.h"
#include "../dn2/audio_tap.h"
#include "../ui/trace_ring.h"

volatile struct trace_ring wr_scope_ring __attribute__((section(".data"))) = { 0, { 0 } };

void wr_scope_feed(void)
{
    short b[DN2_BLOCK];
    if (dn2_track_block(wr_events.scope_track, b))
        trace_ring_push(&wr_scope_ring, b, DN2_BLOCK);
}
