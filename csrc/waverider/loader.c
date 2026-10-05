/* Waverider's table loader, the ColdFire half: +Drive sectors -> the DSP's load area.
 *
 * docs/drive-load-command.md has the protocol and the measurements behind it. Two
 * sides, one queue:
 *
 * - The UI task (`wr_load_poll`, from wr_poll once a UI pass) reads +Drive sectors
 *   with the stock block driver 0x4012c59a(sector, bytes, buf) straight into the
 *   payload of the next free chunk, a whole frame laid out as the DSP's load command
 *   reads it. The driver needs live interrupts, so it is never called from the ISR.
 * - The audio ISR (`wr_frame_src`, from the hook at 0x40025e82 just before the stock
 *   send) picks what this exchange sends: the frame the stock code built, or the
 *   oldest chunk. A chunk replaces a frame only when that frame and the last frame
 *   sent both carry no note events (frame bytes 34..41, the four voice masks): the DSP
 *   renders a load frame from the previous frame's copy, so an event there would play
 *   twice, and an event in the frame replaced would be lost.
 *
 * One chunk is in flight at a time. The DSP answers in reply word 6 with its
 * sequence when the sum matched, or the sequence with bit 31 flipped when it refused
 * it; neither within TIMEOUT frames
 * sends it again. GIVE_UP timeouts in a row (a DSP that never answers: one without
 * load.asm renders a load frame as silence) stop the loader for good, so a broken
 * DSP half costs a few dropped frames, never a stream of them. Byte order: the ColdFire sends 16-bit words big-endian, and DSP word
 * k is ColdFire words 2k (low half) and 2k+1 (high half), so a payload of int16
 * samples in order, as the ColdFire holds them, lands in DDR as the samples in order.
 * The DSP writes the answer with the halves swapped, so a ColdFire long read of
 * reply +0x18 is the sequence as sent.
 */

#include "loader.h"
#include "events.h"

#define FRAME_WORDS   1344                /* 2,688 bytes, the frame the stock ISR sends */
#define HEADER_WORDS  8                   /* 4 DSP words: command|count, dest, seq, sum */
#define CHUNK_SECTORS 5
#define PAYLOAD_BYTES (CHUNK_SECTORS * 512)   /* 2,560 B, 640 DSP words (the DSP takes 668) */
#define QUEUE         3
#define TIMEOUT       24                  /* frames, 16 ms: the reply trails by two or three */
#define GIVE_UP       8                   /* timeouts in a row */
#define SEQ_TAG       0x4C440000u         /* 'LD': no stock reply value looks like it */
#define AREA_BYTES    0x200000u           /* the DSP's load area, 0x80800000.. */

#define REPLY   0x800053A4u               /* the stock reply copy, filled by the send */
#define ANSWER  0x18                      /* reply word 6: load.asm's answer (the only free word) */
#define REFUSED 0x80000000u               /* the answer for a refused chunk: its sequence ^ this */
#define MASKS   34                        /* frame bytes 34..41: note-on, note-off, copies */
#define DRIVE_READ ((int (*)(u32, u32, void *))0x4012C59Au)

struct chunk { u16 w[FRAME_WORDS]; };

static const u8 *want_memory __attribute__((section(".data"))) = 0;   /* 0: the +Drive */
static wr_load_seen want_seen __attribute__((section(".data"))) = 0;
static u32 timeouts_in_a_row __attribute__((section(".data"))) = 0;

static struct chunk queue[QUEUE] __attribute__((section(".data"), aligned(16))) = { { { 0 } } };
/* after the queue, which it names for the probe */
volatile struct wr_load wr_load __attribute__((section(".data"))) =
    { 0x57524C44u, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, (u32)queue, QUEUE };
static volatile u32 head __attribute__((section(".data"))) = 0;    /* UI task: next to fill */
static volatile u32 tail __attribute__((section(".data"))) = 0;    /* ISR: the oldest */
static u32 seq __attribute__((section(".data"))) = 0;
static u32 in_flight __attribute__((section(".data"))) = 0;        /* frames since sent, 0 = none */
static u32 last_clear __attribute__((section(".data"))) = 0;       /* the last frame sent had no events */

static u32 quiet(const u8 *frame)
{
    const u32 *m = (const u32 *)(frame + MASKS - 2);              /* longword-aligned: 32..43 */
    return !(m[0] & 0xFFFFu) && !m[1] && !(m[2] & 0xFFFF0000u);
}

static u32 reply_long(u32 offset)
{
    return *(volatile u32 *)(REPLY + offset);
}

/* The ISR: -> the buffer this exchange sends. */
void *wr_frame_src(void *frame)
{
    u32 clear = quiet((const u8 *)frame);

    wr_note_seen((const u8 *)frame);      /* every frame, before it may be replaced */

    if (in_flight) {
        struct chunk *c = &queue[tail % QUEUE];
        u32 mine = ((u32)c->w[5] << 16) | c->w[4];
        u32 answer = reply_long(ANSWER);
        if (answer == mine) {                                      /* accepted */
            wr_load.acked++;
            in_flight = 0;
            timeouts_in_a_row = 0;
            tail++;
        } else if (answer == (mine ^ REFUSED)) {                   /* refused: send it again */
            wr_load.refused++;
            in_flight = 0;
            wr_load.resent++;
        } else if (++in_flight > TIMEOUT) {
            wr_load.timeouts++;
            in_flight = 0;
            if (++timeouts_in_a_row >= GIVE_UP)
                wr_load.failed = 1;
            else
                wr_load.resent++;
        }
    }
    if (!in_flight && tail != head && !wr_load.failed) {
        if (clear && last_clear) {
            in_flight = 1;
            wr_load.sent++;
            return &queue[tail % QUEUE];              /* the DSP still holds the last frame */
        }
        wr_load.held++;
    }
    last_clear = clear;
    return frame;
}

static int extent(u32 sector, const u8 *memory, u32 bytes, u32 dest, wr_load_seen seen)
{
    if (wr_load.failed || wr_load.done_bytes < wr_load.want_bytes || dest % 4 || bytes % 4
            || !bytes || dest + bytes > AREA_BYTES || dest + bytes < dest)
        return 0;
    wr_load.want_sector = sector;
    wr_load.want_dest = dest;
    want_memory = memory;
    want_seen = seen;
    wr_load.done_bytes = 0;
    wr_load.want_bytes = bytes;
    return 1;
}

int wr_load_extent(u32 sector, u32 sectors, u32 dest, wr_load_seen seen)
{
    return extent(sector, 0, sectors * 512, dest, seen);
}

int wr_load_memory(const void *memory, u32 bytes, u32 dest)
{
    return extent(0, (const u8 *)memory, bytes, dest, 0);
}

int wr_load_idle(void)
{
    return wr_load.failed || (wr_load.done_bytes >= wr_load.want_bytes && head == tail && !in_flight);
}

/* The UI task, once a pass: fill free chunks from the extent being loaded. */
void wr_load_poll(void)
{
    while (!wr_load.failed && wr_load.done_bytes < wr_load.want_bytes && head - tail < QUEUE) {
        struct chunk *c = &queue[head % QUEUE];
        u8 *payload = (u8 *)&c->w[HEADER_WORDS];
        u32 bytes = wr_load.want_bytes - wr_load.done_bytes;
        u32 words, sum = 0;
        if (bytes > PAYLOAD_BYTES)
            bytes = PAYLOAD_BYTES;
        if (want_memory) {
            for (u32 i = 0; i < bytes; i++)
                payload[i] = want_memory[wr_load.done_bytes + i];
        } else {
            /* a +Drive extent is whole sectors (wr_load_extent), so is each chunk */
            int rc = DRIVE_READ(wr_load.want_sector + wr_load.done_bytes / 512, bytes, payload);
            wr_load.last_rc = (u32)rc;
            if (rc < 0) {                 /* an out-of-range sector leaves the buffer stale */
                wr_load.read_errors++;
                wr_load.want_bytes = wr_load.done_bytes;          /* give up this extent */
                return;
            }
        }
        words = bytes / 4;
        for (u32 i = 0; i < words; i++)
            sum += ((u32)c->w[HEADER_WORDS + 2 * i + 1] << 16) | c->w[HEADER_WORDS + 2 * i];
        seq = (seq + 1) & 0xFFFFu;
        {
            u32 dest = wr_load.want_dest + wr_load.done_bytes;
            u32 s = SEQ_TAG | seq;
            c->w[0] = 4;
            c->w[1] = (u16)words;
            c->w[2] = (u16)dest;
            c->w[3] = (u16)(dest >> 16);
            c->w[4] = (u16)s;
            c->w[5] = (u16)(s >> 16);
            c->w[6] = (u16)sum;
            c->w[7] = (u16)(sum >> 16);
            for (u32 i = HEADER_WORDS + 2 * words; i < FRAME_WORDS; i++)
                c->w[i] = 0;              /* past the payload: zeros, as loadframes has it */
            if (want_seen)
                want_seen(dest, &c->w[HEADER_WORDS], bytes);
        }
        wr_load.done_bytes += bytes;
        wr_load.queued++;
        head++;                           /* published last: the ISR sees a whole chunk */
    }
}

/* The hook at 0x40025e82, in place of `move.l 0x402876f8,%d0` (6 bytes, a jmp here).
 * Stock: if the skip counter 0x402876f8 is set it counts down and nothing is sent;
 * otherwise send(0xa80, 0x80005e60, 0xabc, 0x800053a4). Here the frame argument is
 * whatever wr_frame_src picks; the rest is stock, then back to 0x40025eb2. The ISR has
 * saved d0-a5 on entry, so the C call's d0/d1/a0/a1 are free, as the send's are. */
__asm__(
"	.section .text.wr_frame_hook,\"ax\",@progbits\n"
"	.globl	wr_frame_hook\n"
"wr_frame_hook:\n"
"	move.l	0x402876f8,%d0\n"
"	bne.s	1f\n"
"	pea	0x80005e60\n"
"	jsr	wr_frame_src\n"
"	addq.l	#4,%sp\n"
"	pea	0x800053a4\n"
"	pea	0xabc\n"
"	move.l	%d0,-(%sp)\n"
"	pea	0xa80\n"
"	jsr	0x400cf7be\n"
"	lea	16(%sp),%sp\n"
"	jmp	0x40025eb2\n"
"1:	subq.l	#1,%d0\n"
"	move.l	%d0,0x402876f8\n"
"	jmp	0x40025eb2\n"
"	.text\n");
