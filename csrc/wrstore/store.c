/* The Waverider store on the +Drive: finding its current index (store.h).
 *
 * Two groups, A and B, each a superblock and a 32 KiB index. A group is valid when its
 * superblock checks (magic, version, sizes, its own xxh32) and so does its index's
 * xxh32; the higher generation wins, and a tie keeps A, which is read first. The
 * hash is the firmware's own XXH32 (0x4014be0e). */

#include "store.h"

volatile struct wr_store wr_store __attribute__((section(".data"))) = { 0x57525354u, 0, 0, 0, 0, 0 };

/* -> the superblock's generation if it checks, else 0 */
static u32 superblock_ok(const u8 *sb, u32 *index_hash)
{
    if (sb[0] != 'W' || sb[1] != 'R' || sb[2] != 'T' || sb[3] != 'B'
            || be32(sb + 4) != 0x00010040u || be32(sb + 16) != SLOTS
            || be32(sb + 20) != ENTRY_BYTES || be32(sb + 60) != XXH32(sb, 60, 0))
        return 0;
    *index_hash = be32(sb + 24);
    return be32(sb + 8);
}

u8 *wr_store_index(void)
{
    u8 *sb = NEW(512), *index = NEW(INDEX_BYTES), *chosen = 0;
    u32 best = 0;
    wr_store.reads++;
    for (u32 g = 0; g < 2; g++) {
        u32 base = REGION + g * GROUP_B, hash, gen;
        if (DRIVE_READ(base, 512, sb) < 0) {
            wr_store.read_errors++;
            continue;
        }
        gen = superblock_ok(sb, &hash);
        if (!gen || gen <= best)
            continue;
        if (DRIVE_READ(base + 1, INDEX_BYTES, index) < 0) {
            wr_store.read_errors++;
            continue;
        }
        if (XXH32(index, INDEX_BYTES, 0) != hash)
            continue;
        best = gen;
        wr_store.group = g;
        if (!chosen)
            chosen = NEW(INDEX_BYTES);
        for (u32 i = 0; i < INDEX_BYTES; i++)
            chosen[i] = index[i];
    }
    DELETE(sb);
    DELETE(index);
    wr_store.generation = best;
    return chosen;
}
