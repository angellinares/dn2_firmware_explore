/* The per-project pool lists (records.h, docs/for-dnx-waverider-pool.md §2). */

#include "records.h"

u32 wr_record_check(const u8 *rec, u32 p)
{
    u32 flags = be16(rec + R_FLAGS), used = 0;
    if (be32(rec + R_MAGIC) != RECORD_MAGIC)
        return WP_MAGIC;
    if (be16(rec + R_VERSION) != 1)
        return WP_VERSION;
    if (be16(rec + R_PROJECT) != p)
        return WP_PROJECT;
    if (flags & ~RF_AUTOMATIC)
        return WP_FLAGS;
    for (u32 j = 0; j < POOL_ENTRIES; j++) {
        u32 s = be16(rec + R_ENTRIES + 2 * j);
        if (s == RECORD_NONE)
            continue;
        if (flags & RF_AUTOMATIC)
            return WP_AUTO_ENTRIES;
        if (s >= SLOTS)
            return WP_ENTRY;
        used++;
    }
    if (be16(rec + R_COUNT) != used)
        return (flags & RF_AUTOMATIC) ? WP_AUTO_ENTRIES : WP_COUNT;
    for (u32 i = R_ENTRIES + 2 * POOL_ENTRIES; i < R_HASH; i++)
        if (rec[i])
            return WP_RESERVED;
    if (be32(rec + R_HASH) != XXH32(rec, R_HASH, 0))
        return WP_HASH;
    return WP_OK;
}

/* -> the generation of the record in SECTOR if it is valid for P (into REC), else 0 */
static u32 read_one(u32 sector, u32 p, u8 *rec)
{
    if (DRIVE_READ(REGION + sector, RECORD_BYTES, rec) < 0) {
        wr_store.read_errors++;
        return 0;
    }
    if (wr_record_check(rec, p) != WP_OK)
        return 0;
    return be32(rec + R_GEN);
}

/* -> the current generation, with REC the current record; *CURRENT_B 1 if it is B's */
static u32 read_current(u32 p, u8 *rec, u32 *current_b)
{
    u8 *b = NEW(RECORD_BYTES);
    u32 ga = read_one(RECORD_A + p, p, rec), gb = read_one(RECORD_B + p, p, b);
    *current_b = gb > ga;
    if (*current_b)
        for (u32 i = 0; i < RECORD_BYTES; i++)
            rec[i] = b[i];
    DELETE(b);
    return *current_b ? gb : ga;
}

u32 wr_record_read(u32 p, u8 *rec)
{
    u32 current_b;
    return p < PROJECT_SLOTS ? read_current(p, rec, &current_b) : 0;
}

static void rehash(u8 *rec)
{
    wr_put32(rec + R_HASH, XXH32(rec, R_HASH, 0));
}

void wr_record_automatic(u32 p, u8 *rec)
{
    for (u32 i = 0; i < RECORD_BYTES; i++)
        rec[i] = 0;
    wr_put32(rec + R_MAGIC, RECORD_MAGIC);
    wr_put16(rec + R_VERSION, 1);
    wr_put16(rec + R_PROJECT, p);
    wr_put16(rec + R_FLAGS, RF_AUTOMATIC);
    for (u32 j = 0; j < POOL_ENTRIES; j++)
        wr_put16(rec + R_ENTRIES + 2 * j, RECORD_NONE);
    rehash(rec);
}

u32 wr_record_resolve(u32 p, u8 *rec, const u8 *index)
{
    u32 generation = wr_record_read(p, rec), used = 0;
    if (!generation)
        wr_record_automatic(p, rec);
    if (!(be16(rec + R_FLAGS) & RF_AUTOMATIC))
        return generation;
    for (u32 n = 0; index && n < SLOTS && used < POOL_ENTRIES; n++)
        if (wr_store_playable(index + n * ENTRY_BYTES, n))
            wr_put16(rec + R_ENTRIES + 2 * used++, n);
    wr_put16(rec + R_COUNT, used);
    rehash(rec);
    return generation;
}

u32 wr_record_write(u32 p, u8 *rec)
{
    u8 *old = NEW(RECORD_BYTES);
    u32 current_b, generation = read_current(p, old, &current_b) + 1;
    DELETE(old);
    wr_put32(rec + R_GEN, generation);
    rehash(rec);
    /* the sector that is not current: B after A, A after B or when there is none */
    if (DRIVE_WRITE(REGION + (current_b || generation == 1 ? RECORD_A : RECORD_B) + p,
                    RECORD_BYTES, rec) < 0)
        return 0;
    return generation;
}
