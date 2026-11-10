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
 * page after a clear, until PLAY). Counters only grow; readers compare, never reset.
 *
 * - **Voices not yet played as a Waverider:** the same holds when a track becomes a
 *   Waverider in MACHINE SEL. Its voices are marked Waverider in the frame (bytes 148..,
 *   a big-endian word per voice) at once, but still hold what the old machine played, its
 *   LFOs included, and an idle voice also reads as track 1's. The page showed that
 *   modulation until a note (owner, 2026-11-02: POS moved on a new Waverider track until a
 *   track key). `unplayed` keeps a bit per voice, set while the voice is another machine,
 *   cleared by its first note-on as a Waverider; set for every voice at boot.
 * - **A pattern change:** the same again with the machine unchanged. Each pattern has its
 *   own kit, and a voice holds the old kit's sound until its next note. With a Waverider
 *   in both patterns no bit was set, so the page drew the old sound's MOVE around the new
 *   knobs (instrument, wrl2b, 2026-11-03). A kit change sets every bit, so each voice
 *   counts again from its next Waverider note. */

#include "loader.h"
#include "events.h"

#ifndef WR_RAW_TRACK
#error "WR_RAW_TRACK: the raw machine-type getter's address (dnfw.waverider.coldfire raw_track)"
#endif
#define RAW_TRACK ((u32 (*)(void *))(WR_RAW_TRACK))

extern volatile struct trace_ring wr_scope_ring;           /* scope_feed.c */
volatile struct wr_events wr_events __attribute__((section(".data"))) =
    { 0x57524556u, 0, { 0 }, 0, 0xFF, 0xFFFF, &wr_scope_ring };

#define WR_TYPE 5                          /* Waverider's machine type (dnfw.waverider.coldfire NEW_TYPE) */
/* The live kit, &kits[active pattern] (0x40025af4 stores it; 0x40025e0a only when it
 * differs). Instrument, wrl2b, 2026-11-03: it moved 23,921 B a pattern number on each
 * change, came back to the same value on the same pattern, and held through 30 s of play. */
#define LIVE_KIT (*(volatile u32 *)0x800052A0u)

static u32 kit_seen __attribute__((section(".data"))) = 0;

/* the frame ISR, every frame: count each voice whose note-on bit is set, and keep
 * `unplayed` (see above), set again for every voice when the kit changes */
void wr_note_seen(const u8 *frame)
{
    u32 on = (u32)frame[34] << 8 | frame[35];
    u32 unplayed = wr_events.unplayed, kit = LIVE_KIT;
    if (kit != kit_seen) {                 /* before the note-ons: a note in this frame plays the new kit */
        kit_seen = kit;
        unplayed = 0xFFFF;
    }
    for (u32 v = 0; v < 16; v++) {
        u32 wr = ((u32)frame[148 + 2 * v] << 8 | frame[149 + 2 * v]) == WR_TYPE;
        if (on >> v & 1) {
            wr_events.notes[v]++;
            if (wr)
                unplayed &= ~(1u << v);
        }
        if (!wr)
            unplayed |= 1u << v;
    }
    wr_events.unplayed = (unsigned short)unplayed;
}

/* 0x40071eb6's call: the clear asks the track's machine type */
u32 wr_clear_type(void *track)
{
    wr_events.clears++;
    return RAW_TRACK(track);
}
