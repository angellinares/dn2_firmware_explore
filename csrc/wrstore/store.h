/* The Waverider store on the +Drive, format v1 (docs/waverider-store.md): reading it.
 *
 * Shared by the /waverider route (route.c), which lists, reads and writes it for DNX,
 * and by Waverider's table loader (csrc/waverider/pool.c), which plays from it. Only
 * the UI task calls these: the block driver needs live interrupts. */

#ifndef WRSTORE_STORE_H
#define WRSTORE_STORE_H

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;

/* The firmware returns every value in d0. This GCC (m68k-linux) returns pointers in
 * a0, so no firmware routine is declared to return a pointer: values are u32. Our own
 * functions, compiled by the same GCC, may return pointers to each other. */
#define NEW_RAW      ((u32 (*)(u32))0x40120264u)
#define NEW(n)       ((void *)NEW_RAW(n))
#define DELETE       ((void (*)(void *))0x40120270u)
#define DRIVE_READ   ((int (*)(u32, u32, void *))0x4012c59au)
#define XXH32        ((u32 (*)(const void *, u32, u32))0x4014be0eu)

#define REGION        0x600000u             /* the store's first sector */
#define GROUP_B       0x400u
#define SLOTS         256
#define DATA_START    0x1000u               /* sectors, from the region's start */
#define SLOT_SECTORS  1024u                 /* 512 KiB: slot n's fixed extent */
#define ENTRY_BYTES   128
#define INDEX_BYTES   (SLOTS * ENTRY_BYTES)

/* An index entry's fields (big-endian), docs/waverider-store.md */
#define E_FLAGS   0                         /* u16: bit 0 used, bit 1 no interpolation */
#define E_KIND    2                         /* u16: 1 a wavetable */
#define E_WAVES   4
#define E_POINTS  6
#define E_FORMAT  8                         /* u16: 1 int16 big-endian */
#define E_START   12                        /* u32: sector, from the region's start */
#define E_LENGTH  16                        /* u32: bytes */
#define E_HASH    20                        /* u32: xxh32 of the table */
#define E_NAME    32                        /* 64 bytes, cp1252, NUL-padded */

/* What the probe can PEEK: the last read's group and generation, and counters that
 * only grow. `changes` counts committed writes, so a reader of the store knows when
 * what it loaded is stale. */
struct wr_store { u32 magic, group, generation, read_errors, reads, changes; };
extern volatile struct wr_store wr_store;

static inline u32 be16(const u8 *p) { return (u32)p[0] << 8 | p[1]; }
static inline u32 be32(const u8 *p) { return (u32)p[0] << 24 | (u32)p[1] << 16 | (u32)p[2] << 8 | p[3]; }

/* -> the current group's index (INDEX_BYTES, NEW-allocated: DELETE it), or 0 for an
 * empty store. Sets wr_store.group and .generation. */
u8 *wr_store_index(void);

#define DRIVE_WRITE  ((int (*)(u32, u32, const void *))0x4012c780u)
#define WR_TABLE_BYTES 0x4000u              /* 16 x 512 int16: the table the DSP reads */

/* Can the DSP play slot n's table? Used, a wavetable of 16 x 512 int16 big-endian, in
 * its own extent. The automatic pool is the slots for which this holds, in order. */
static inline int wr_store_playable(const u8 *e, u32 n)
{
    return (be16(e + E_FLAGS) & 1) && be16(e + E_KIND) == 1 && be16(e + E_WAVES) == 16
        && be16(e + E_POINTS) == 512 && be16(e + E_FORMAT) == 1
        && be32(e + E_START) == DATA_START + n * SLOT_SECTORS && be32(e + E_LENGTH) == WR_TABLE_BYTES;
}

#endif
