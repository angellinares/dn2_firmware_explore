/* Note-ons and preset clears, counted for the page (events.c). */

#ifndef WAVERIDER_EVENTS_H
#define WAVERIDER_EVENTS_H

/* The probe can PEEK this; every counter only grows (and wraps). */
struct wr_events {
    unsigned int magic;                    /* 'WREV' */
    unsigned int clears;                   /* CLEAR TRK PRESET, any track */
    unsigned char notes[16];               /* note-ons per voice */
    unsigned char shown_osc;               /* the oscillator of the SYN page last drawn (page.c) */
};

#ifndef WAVERIDER_PAGE
extern volatile struct wr_events wr_events;
void wr_note_seen(const unsigned char *frame);
unsigned int wr_clear_type(void *track);
#endif

#endif
