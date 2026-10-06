/* SAVE PROJECT and LOAD PROJECT carry the pool lists (docs/for-dnx-waverider-pool.md §2,
 * "What the instrument does with them").
 *
 * Two entry hooks, each a jmp over the routine's 8-byte prologue (dnfw.waverider.drive):
 * - 0x400f6960(this, slot, progress), the save of the working project to project slot
 *   SLOT (0-based, 128 the working copy). SAVE PROJECT AS 002 calls it with 1, then
 *   with 128 (measured in the emulator, 2026-10-06; boot and CREATE NEW call it with
 *   128 only). After a save to 0..127 that succeeded, record 0 is copied to record
 *   SLOT + 1: a stored record as it is, and with none an automatic record.
 * - 0x400f6a2c(handle, slot, project, progress), the +Drive read of LOAD PROJECT
 *   (called from 0x40042c48 with slot 1 for LOAD PROJECT 002, measured). After a read
 *   that succeeded, record SLOT + 1 is copied to record 0 (none: an automatic one),
 *   and Waverider refills its pool (wr_store.changes).
 * Each copy is one sector write, so an interrupted one leaves the old record or the
 * new one. The stock result is returned unchanged. Both routines answer success in
 * d0's low byte (the callers test it with tstb). 1.11 addresses: for 1.12, find both
 * routines again by their callers. */

#include "records.h"

#define WORKING_COPY 128

/* The probe reads this */
struct wr_projects { u32 magic, saves, loads, last_slot, last_generation, failed; };
volatile struct wr_projects wr_projects __attribute__((section(".data"))) =
    { 0x5752504Au, 0, 0, 0, 0, 0 };

/* Record FROM as project slot TO's next record */
static void copy_record(u32 from, u32 to)
{
    u8 *rec = NEW(RECORD_BYTES);
    u32 generation;
    if (wr_record_read(from, rec)) {
        wr_put16(rec + R_PROJECT, to);       /* the rest as stored; the write rehashes */
    } else {
        wr_record_automatic(to, rec);
    }
    generation = wr_record_write(to, rec);
    DELETE(rec);
    wr_projects.last_slot = to;
    wr_projects.last_generation = generation;
    if (!generation)
        wr_projects.failed++;
}

void wr_project_saved(u32 slot, u32 ok)
{
    if (!(ok & 0xff) || slot >= WORKING_COPY)
        return;
    copy_record(0, slot + 1);
    wr_projects.saves++;
}

void wr_project_loaded(u32 slot, u32 ok)
{
    if (!(ok & 0xff) || slot >= WORKING_COPY)
        return;
    copy_record(slot + 1, 0);
    wr_projects.loads++;
    wr_store.changes++;                      /* the working pool changed: refill */
}

/* The wrappers the hooks jump to: the stock routine, then ours with its slot and result */
__asm__(
"	.section .text.wr_project_hooks,\"ax\",@progbits\n"
"	.globl	wr_save_wrap\n"
"wr_save_wrap:\n"                       /* 4 this, 8 slot, 12 progress */
"	move.l	12(%sp),-(%sp)\n"
"	move.l	12(%sp),-(%sp)\n"
"	move.l	12(%sp),-(%sp)\n"
"	jsr	wr_save_stock\n"
"	lea	12(%sp),%sp\n"
"	move.l	%d0,-(%sp)\n"                   /* the result, kept */
"	move.l	%d0,-(%sp)\n"                   /* ok */
"	move.l	16(%sp),-(%sp)\n"               /* slot */
"	jsr	wr_project_saved\n"
"	addq.l	#8,%sp\n"
"	move.l	(%sp)+,%d0\n"
"	rts\n"
"wr_save_stock:\n"                      /* the prologue the hook replaced, then on */
"	lea	-32(%sp),%sp\n"
"	movem.l	%d2-%d4,(%sp)\n"
"	jmp	0x400f6968\n"
"	.globl	wr_load_wrap\n"
"wr_load_wrap:\n"                       /* 4 handle, 8 slot, 12 project, 16 progress */
"	move.l	16(%sp),-(%sp)\n"
"	move.l	16(%sp),-(%sp)\n"
"	move.l	16(%sp),-(%sp)\n"
"	move.l	16(%sp),-(%sp)\n"
"	jsr	wr_load_stock\n"
"	lea	16(%sp),%sp\n"
"	move.l	%d0,-(%sp)\n"
"	move.l	%d0,-(%sp)\n"
"	move.l	16(%sp),-(%sp)\n"
"	jsr	wr_project_loaded\n"
"	addq.l	#8,%sp\n"
"	move.l	(%sp)+,%d0\n"
"	rts\n"
"wr_load_stock:\n"
"	lea	-32(%sp),%sp\n"
"	movem.l	%d2-%d3/%a2,(%sp)\n"
"	jmp	0x400f6a34\n"
"	.text\n");
