/* The per-project pool lists on the +Drive (docs/for-dnx-waverider-pool.md §2).
 *
 * Project slot p (0 the working project, 1..128 as /projects numbers them) has two
 * sectors, A at REGION + 0x800 + p and B at REGION + 0x900 + p, written alternately.
 * The current record is the valid one with the higher generation (a tie keeps A).
 * None valid, or the automatic flag, means the automatic pool: every playable stored
 * table in store-slot order, the first 127. Shared by the /wavepool route (route.c)
 * and Waverider's pool fill (csrc/waverider/pool.c). UI task only. */

#ifndef WRSTORE_RECORDS_H
#define WRSTORE_RECORDS_H

#include "store.h"

#define PROJECT_SLOTS   129                 /* 0 working, 1..128 */
#define POOL_ENTRIES    127
#define RECORD_BYTES    512
#define RECORD_A        0x800u              /* sectors, from the region's start */
#define RECORD_B        0x900u
#define RECORD_MAGIC    0x5752504Cu         /* 'WRPL' */
#define RECORD_NONE     0xFFFFu
#define RF_AUTOMATIC    1u

/* A record's fields (big-endian) */
#define R_MAGIC   0
#define R_VERSION 4
#define R_PROJECT 6
#define R_GEN     8
#define R_COUNT   12
#define R_FLAGS   14
#define R_ENTRIES 16                        /* 127 x u16 */
#define R_HASH    508

/* -> 0 if REC is a well-formed record for project slot P, else why not (WP_*) */
u32 wr_record_check(const u8 *rec, u32 p);

/* Project slot P's current record into REC (RECORD_BYTES) and its generation, or 0 if
 * it has none (REC then undefined). */
u32 wr_record_read(u32 p, u8 *rec);

/* What project slot P plays, into REC, always well-formed: the stored record, or with
 * none generation 0 and the automatic flag. An automatic one comes back with its
 * entries filled from INDEX (the current store index, or 0 for an empty store) and
 * the count to match. -> the generation. */
u32 wr_record_resolve(u32 p, u8 *rec, const u8 *index);

/* REC (checked) as project slot P's next record: generation = current + 1, the hash
 * recomputed, into the sector that is not current. -> the new generation, or 0 if the
 * +Drive write failed. */
u32 wr_record_write(u32 p, u8 *rec);

/* An automatic record for P (entries cleared, count 0, generation 0), hashed. */
void wr_record_automatic(u32 p, u8 *rec);

enum { WP_OK = 0, WP_MAGIC = 1, WP_VERSION, WP_PROJECT, WP_FLAGS, WP_ENTRY, WP_COUNT,
       WP_RESERVED, WP_HASH, WP_AUTO_ENTRIES, WP_STALE };

static inline void wr_put16(u8 *p, u32 v) { p[0] = (u8)(v >> 8); p[1] = (u8)v; }
static inline void wr_put32(u8 *p, u32 v)
{
    p[0] = (u8)(v >> 24); p[1] = (u8)(v >> 16); p[2] = (u8)(v >> 8); p[3] = (u8)v;
}

#endif
