/* Waverider's table loader, the ColdFire half (loader.c): chunks of the +Drive, or of
 * memory, to the DSP's load area through the per-frame exchange. */

#ifndef WAVERIDER_LOADER_H
#define WAVERIDER_LOADER_H

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;

/* The probe reads this (PEEK); the counters only grow. */
struct wr_load {
    u32 magic;                            /* 'WRLD' */
    u32 queued, sent, resent, acked, refused, timeouts;
    u32 held;                             /* exchanges a ready chunk waited for a free frame */
    u32 read_errors, last_rc;
    u32 want_sector, want_bytes, want_dest; /* the extent being loaded */
    u32 done_bytes;
    u32 failed;                           /* 1: the DSP stopped answering; so did the loader */
    u32 queue, queue_chunks;              /* where the chunks are (2,688 B each), and how many */
};
extern volatile struct wr_load wr_load;

/* Each chunk's payload as it is queued: DEST in the load area, the 16-bit words as
 * read, BYTES of them. */
typedef void (*wr_load_seen)(u32 dest, const u16 *words, u32 bytes);

/* One extent at a time, to DEST in the load area (4-aligned, inside its 2 MB): -> 0
 * if one is still loading, it does not fit, or the loader has stopped. */
int wr_load_extent(u32 sector, u32 sectors, u32 dest, wr_load_seen seen);
int wr_load_memory(const void *memory, u32 bytes, u32 dest);
/* -> 1 once everything asked for is acknowledged (or the loader has stopped) */
int wr_load_idle(void);
/* the UI task, once a pass */
void wr_load_poll(void);
/* the frame ISR (the hook at 0x40025e82): -> the buffer this exchange sends */
void *wr_frame_src(void *frame);

#endif
