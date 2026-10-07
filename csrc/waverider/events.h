/* Note-ons and preset clears, counted for the page (events.c). */

#ifndef WAVERIDER_EVENTS_H
#define WAVERIDER_EVENTS_H

struct trace_ring;

/* The probe can PEEK this; every counter only grows (and wraps). */
struct wr_events {
    unsigned int magic;                    /* 'WREV' */
    unsigned int clears;                   /* CLEAR TRK PRESET, any track */
    unsigned char notes[16];               /* note-ons per voice */
    unsigned char shown_osc;               /* the oscillator of the SYN page last drawn (page.c) */
    unsigned char scope_track;             /* page 4's scope: the track to capture, 0..15; 0xFF none (page.c) */
    unsigned char spare[2];
    volatile struct trace_ring *scope;     /* its samples, fed every frame (scope_feed.c) */
};

#ifndef WAVERIDER_PAGE
extern volatile struct wr_events wr_events;
void wr_note_seen(const unsigned char *frame);
unsigned int wr_clear_type(void *track);
void wr_scope_feed(void);
#endif

#endif
