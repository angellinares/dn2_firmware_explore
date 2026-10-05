/* Waverider's table pool (pool.c), and what the page reads of it. */

#ifndef WAVERIDER_POOL_H
#define WAVERIDER_POOL_H

#define POOL_SLOTS     127                 /* 16 KiB tables below the load area's directory */
#define WR_POOL_WIDTH  96                  /* the page's wave strip, as wr_spans */

/* the display spans of pool table j: [frame][min, max][column], signed bytes; in RAM
 * above BSS that nothing else claims (dnfw.mods: waverider's RAM) */
#define WR_POOL_SPANS  ((signed char (*)[16][2][WR_POOL_WIDTH])0x46A00000u)

/* The probe can PEEK this. COUNT is what TBL may offer past the baked tables, set when
 * a fill's directory is acknowledged; GENERATION the store's (0: there was none). */
struct wr_pool {
    unsigned int magic;                    /* 'WRPL' */
    unsigned int state;                    /* 0 waiting, 1 filling, 2 directory, 3 ready, 5 failed */
    unsigned int count, fills, generation, changes_seen, spare;
    unsigned char slot_of[POOL_SLOTS];     /* the store slot of pool entry j */
    char names[POOL_SLOTS][8];             /* its name's first five characters, for TBL's text */
};

/* The drive chunk's first bytes, so the page (another chunk, linked first) finds the
 * poll and the pool without knowing this link's addresses. */
#define WR_DRIVE_MAGIC 0x57524456u         /* 'WRDV' */
#define WR_DRIVE_HEAD  ((const struct wr_drive_head *)0x467F0000u)
struct wr_drive_head {
    unsigned int magic;
    void (*poll)(void);
    volatile struct wr_pool *pool;
};

#endif
