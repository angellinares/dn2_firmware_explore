/* Edits of the working project's pool list (record 0), from the wavetable page.
 *
 * Each edit starts from what plays (wr_record_resolve): the stored list, or, for a
 * project still on the automatic pool, the automatic pool written out as a list, so the
 * edit keeps what was playing (docs/for-dnx-waverider-pool.md §2). It changes the list,
 * writes it in one sector (generation + 1), and makes Waverider refill its pool. One
 * subject: changing record 0. */

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
