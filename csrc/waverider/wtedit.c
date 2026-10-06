/* Edits of the working project's pool list (record 0), from the wavetable page.
 *
 * Each edit starts from what plays (wr_record_resolve): the stored list, or, for a
 * project still on the automatic pool, the automatic pool written out as a list, so the
 * edit keeps what was playing (docs/for-dnx-waverider-pool.md §2). It changes the list,
 * writes it in one sector (generation + 1), and makes Waverider refill its pool.
 *
 * LOAD sets the active track's TBL1 or TBL2 in the kit's sound (the value array at
 * sound + 20, slots 27 and 33; coarse c in the word's high byte, pool index c - 2), the
 * array the SYN page, the frame to the DSP and SAVE all read. It writes no change event:
 * not measured whether anything else waits for one.
 *
 * One subject: what the wavetable page changes. */

#include "../wrstore/records.h"
#include "wtedit.h"

static u32 count_used(const u8 *rec)
{
    u32 n = 0;
    for (u32 j = 0; j < POOL_ENTRIES; j++)
        n += be16(rec + R_ENTRIES + 2 * j) != RECORD_NONE ? 1 : 0;
    return n;
}

/* REC: record 0 as an explicit list to edit (NEW-allocated) */
static u8 *start(void)
{
    u8 *index = wr_store_index(), *rec = NEW(RECORD_BYTES);
    wr_record_resolve(0, rec, index);
    wr_put16(rec + R_FLAGS, 0);
    if (index)
        DELETE(index);
    return rec;
}

static u32 finish(u8 *rec)
{
    u32 generation;
    wr_put16(rec + R_COUNT, count_used(rec));
    generation = wr_record_write(0, rec);
    DELETE(rec);
    if (generation)
        wr_store.changes++;                  /* the working pool changed: refill */
    return generation != 0;
}

u32 wt_pool_add(u32 store_slot)
{
    u8 *rec = start();
    u32 free = POOL_ENTRIES;
    for (u32 j = 0; j < POOL_ENTRIES; j++) {
        u32 s = be16(rec + R_ENTRIES + 2 * j);
        if (s == store_slot) {               /* already there */
            DELETE(rec);
            return WT_ALREADY;
        }
        if (s == RECORD_NONE && free == POOL_ENTRIES)
            free = j;
    }
    if (free == POOL_ENTRIES) {
        DELETE(rec);
        return WT_FULL;
    }
    wr_put16(rec + R_ENTRIES + 2 * free, store_slot);
    return finish(rec) ? WT_DONE : WT_FAILED;
}

u32 wt_pool_clear(u32 j)
{
    u8 *rec;
    if (j >= POOL_ENTRIES)
        return WT_FAILED;
    rec = start();
    wr_put16(rec + R_ENTRIES + 2 * j, RECORD_NONE);
    return finish(rec) ? WT_DONE : WT_FAILED;
}

#define ACTIVE_TRACK (*(volatile u8 *)0x42431a6cu)
#define KIT          (*(u8 *const *)0x800052a0u)
#define SOUND(t)     (KIT + 52u + 1163u * (t))           /* may sit at an odd address */
#define TYPE_AT      0xde                                /* slot 101: the machine type */
#define WAVERIDER    5

u32 wt_tbl_load(u32 j, u32 osc)
{
    u32 t = ACTIVE_TRACK;
    u8 *sound, *at;
    if (t >= 16)
        return WT_NOT_WAVERIDER;
    sound = SOUND(t);
    if (sound[TYPE_AT] != WAVERIDER)
        return WT_NOT_WAVERIDER;
    at = sound + 20u + 2u * (osc ? 33u : 27u);
    at[0] = (u8)(j + 2);                     /* byte by byte: the sound may be at an odd address */
    at[1] = 0;
    return WT_DONE;
}
