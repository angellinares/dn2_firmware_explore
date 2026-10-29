/* The /devslots route (diagnostic builds only, WR_SLOTROUTE): the device settings block,
 * as the start-up reader 0x400f2004 finds it, for DNX to read (docs/for-dnx-devslots.md).
 *
 * The start-up reader reads 256 bytes from raw sector 0x40000 into 0x405cd85c and checks
 * them (0x400bb4c0); if they fail, it tries sector 0x48000. Both slots start with the
 * 256-byte header (COKi) and go on with the working project. Each save writes the slot
 * not in use, then zeroes the other slot's 'C' (0x400f1e26). MIDI CONFIG is not in the
 * header: on the unit (2026-10-29) a CLOCK SEND change and a save left it unchanged. Three read-only files of SLOT_BYTES each, read when DNX opens them:
 *
 *   /devslots/0  sector 0x40000's first 272 bytes
 *   /devslots/1  sector 0x48000's first 272 bytes
 *   /devslots/2  the running copy, RAM 0x405cd85c
 *
 * and the whole saved state, header and working project, 12,890,388 bytes as the start-up
 * reader loads it, summarised so DNX need not fetch it all (the file protocol returns 16
 * bytes a request): a CRC-32 of each 64 KiB block, 197 of them, then any block on request.
 *
 *   /devslots/3  crc-40000: 197 big-endian CRC-32s of sector 0x40000's blocks (788 bytes)
 *   /devslots/4  crc-48000: the same for sector 0x48000
 *   /devslots/5  crc-ram: the same for the running copy, RAM 0x405cd85c
 *   /devslots/N  N = 1000 + source x 256 + block (source 0, 1, 2 as above, block 0..196):
 *                that block, 65,536 bytes (the last one 45,332). Not listed.
 *
 * One 64 KiB stage and a 1 KiB table, allocated once: the route never takes a
 * project-sized block from the heap the project cache uses.
 *
 * Built as /modinfo is (modinfo.c): content kind 0x53, object version 1, raw. A write
 * is refused at its first chunk. Nothing here writes the +Drive or the settings block. */

#include "routekit.h"
#include "store.h"

#define SLOT_KIND    0x53u                  /* 'S' (/modinfo's record is 0x4D) */
#define SLOT_BYTES   272u                   /* the header and the project's first 16 bytes */
#define SLOT_HEADS   3u                     /* 0, 1, 2: the 272-byte blocks */
#define SLOT_FILES   6u                     /* listed: the heads and the three CRC files */
#define FULL_BYTES   12890388u              /* 0x405cd85c..0x41218970, as 0x400f2004 loads it */
#define BLOCK        0x10000u               /* 64 KiB, the +Drive reader's largest piece */
#define BLOCKS       197u                   /* 196 of 64 KiB, then 45,332 B */
#define CRC_BYTES    (BLOCKS * 4u)
#define BLOCK_BASE   1000u                  /* /devslots/1000 + source x 256 + block */
#define READ_ONLY    0x12u
#define SETTINGS_RAM ((const u8 *)0x405cd85cu)

static const u32 sectors[2] = { 0x40000u, 0x48000u };
static const char *const names[SLOT_FILES] = { "slot-40000", "slot-48000", "ram", "crc-40000", "crc-48000", "crc-ram" };
static const u32 file_size[SLOT_FILES] = { SLOT_BYTES, SLOT_BYTES, SLOT_BYTES, CRC_BYTES, CRC_BYTES, CRC_BYTES };

static u8 *bstage __attribute__((section(".data"))) = 0;   /* BLOCK, for the CRCs and the blocks, allocated once */
static u32 *crctab __attribute__((section(".data"))) = 0;  /* 256 words, the CRC-32 table */
static u32 *crcout __attribute__((section(".data"))) = 0;  /* BLOCKS words, a CRC file's content */

static u32 block_bytes(u32 b) { return b + 1 < BLOCKS ? BLOCK : FULL_BYTES - (BLOCKS - 1) * BLOCK; }

/* file i -> its length, or 0 when there is no such file */
static u32 file_bytes(u32 i)
{
    if (i < SLOT_FILES)
        return file_size[i];
    if (i >= BLOCK_BASE && (i - BLOCK_BASE) / 256u < 3u && (i - BLOCK_BASE) % 256u < BLOCKS)
        return block_bytes((i - BLOCK_BASE) % 256u);
    return 0;
}

/* block b of source src (0, 1 the slots, 2 the running copy) into bstage; < 0 on a read failure */
static int load_block(u32 src, u32 b)
{
    u32 n = block_bytes(b);
    if (src < 2)
        return DRIVE_READ(sectors[src] + b * (BLOCK / 512u), (n + 511u) & ~511u, bstage);
    for (u32 k = 0; k < n; k++)                       /* a plain loop: no stock memcpy, which lfo4 hooks */
        bstage[k] = SETTINGS_RAM[b * BLOCK + k];
    return 0;
}

static u32 crc32(const u8 *p, u32 n)
{
    u32 c = 0xFFFFFFFFu;
    while (n--)
        c = crctab[(c ^ *p++) & 0xFFu] ^ (c >> 8);
    return c ^ 0xFFFFFFFFu;
}

void ds_root_entry(void);
void ds_list_invoker(void);
void ds_file_invoker(void);
void ds_check_invoker(void);
void ds_header_invoker(void);
void ds_commit_invoker(void);
void wr_nop(void);
void ds_register(void *self, u8 *registry);

static const u32 vtable[6] __attribute__((aligned(4))) = {
    0, TYPEINFO, (u32)wr_nop, (u32)wr_nop, (u32)ds_root_entry, (u32)ds_register,
};

static u8 *dstage __attribute__((section(".data"))) = 0;   /* 512 B, a whole sector, allocated once */

u32 ds_root_fill(u32 *out)
{
    u8 alloc;
    STR_CSTR(out, "devslots", &alloc);
    out[1] = SLOT_FILES;
    return (u32)out;
}

/* /devslots' listing: the three files, always used */
u32 ds_list_fill(u32 *out)
{
    struct entry *e = NEW(SLOT_FILES * sizeof(struct entry));
    u8 alloc;
    for (u32 i = 0; i < SLOT_FILES; i++) {
        e[i].index = i;
        e[i].size = file_size[i];
        e[i].permissions = READ_ONLY;
        e[i].used = e[i].used2 = 1;
        e[i].zero = 0;
        e[i].pad[0] = e[i].pad[1] = e[i].pad[2] = 0;
        STR_CSTR(&e[i].name, names[i], &alloc);
    }
    ((u8 *)out)[0] = 1;
    out[1] = EMPTY_STR;
    out[2] = (u32)e;
    out[3] = (u32)(e + SLOT_FILES);
    out[4] = (u32)(e + SLOT_FILES);
    return (u32)out;
}

/* The file: kind 1 over the stage, filled at the read's pre-check */
u32 ds_file_fill(u32 *out, void *any, void *args)
{
    u32 params[3] = { 0, 0, 0 }, i = SLOT_FILES, ok;
    (void)any;
    PATH_ARGS(params, args);
    ok = params[0] != params[1] && PARSE_U32(params[0], &i);
    STRVEC_DTOR(params);
    if (!ok || !file_bytes(i)) {
        rk_fail_in(out, RESULT_WORDS, "devslots: the files are 0 to 5, or 1000 + source x 256 + block");
        return (u32)out;
    }
    if (!dstage)
        dstage = NEW(512);
    if (i >= SLOT_HEADS && !bstage)
        bstage = NEW(BLOCK);
    if (i >= SLOT_HEADS && !crctab) {
        crctab = NEW(256 * 4);
        if (crctab)
            for (u32 n = 0; n < 256; n++) {
                u32 c = n;
                for (int k = 0; k < 8; k++)
                    c = c & 1u ? 0xEDB88320u ^ (c >> 1) : c >> 1;
                crctab[n] = c;
            }
    }
    if (i >= SLOT_HEADS && !crcout)
        crcout = NEW(CRC_BYTES);
    if (i >= SLOT_HEADS && (!bstage || !crctab || !crcout)) {
        rk_fail_in(out, RESULT_WORDS, "devslots: no memory for the stage");
        return (u32)out;
    }
    for (u32 k = 0; k < RESULT_WORDS; k++)
        out[k] = 0;
    ((u8 *)out)[0] = 1;
    out[1] = EMPTY_STR;
    out[2] = SLOT_KIND;                               /* info +0: the content kind */
    out[3] = 1;                                       /* +4 kind 1: a memory stream */
    ((u16 *)out)[8] = READ_ONLY;                      /* +8 */
    out[5] = (u32)(i < SLOT_HEADS ? dstage : i < SLOT_FILES ? (u8 *)crcout : bstage);   /* +12 the stage */
    out[6] = file_bytes(i);                           /* +16 the length */
    out[7] = i;                                       /* +20 index */
    out[8] = 1;                                       /* +24 object version */
    rk_make_fn((struct fn *)&out[2 + 7], i, (void *)ds_check_invoker);    /* +28 read pre-check */
    rk_make_fn((struct fn *)&out[2 + 19], i, (void *)ds_commit_invoker);  /* +76 commit */
    rk_make_fn((struct fn *)&out[2 + 27], i, (void *)ds_header_invoker);  /* +108 header check */
    return (u32)out;
}

/* +28, before a transfer: a read gets the slot's sector (one sector, as the start-up
 * reader reads it) or the running copy */
u32 ds_check_fill(u32 *out, void *any, u8 *info, u32 ret)
{
    u32 i = rk_closure_slot(any);
    (void)info;
    out[0] = 0;
    out[1] = EMPTY_STR;
    if (ret != READ_OPEN_RETURN) {
        ((u8 *)out)[0] = 1;
        return (u32)out;
    }
    if (i < 2) {
        if (DRIVE_READ(sectors[i], 512, dstage) < 0) {
            rk_fail_num_in(out, 2, "devslots ", i, "the +Drive read failed");
            return (u32)out;
        }
    } else if (i < SLOT_HEADS) {
        for (u32 k = 0; k < SLOT_BYTES; k++)
            dstage[k] = SETTINGS_RAM[k];
    } else if (i < SLOT_FILES) {
        u32 src = i - SLOT_HEADS;
        for (u32 b = 0; b < BLOCKS; b++) {            /* big-endian words, as the ColdFire stores them */
            if (load_block(src, b) < 0) {
                rk_fail_num_in(out, 2, "devslots ", i, "the +Drive read failed");
                return (u32)out;
            }
            crcout[b] = crc32(bstage, block_bytes(b));
        }
    } else {
        u32 src = (i - BLOCK_BASE) / 256u, b = (i - BLOCK_BASE) % 256u;
        if (load_block(src, b) < 0) {
            rk_fail_num_in(out, 2, "devslots ", i, "the +Drive read failed");
            return (u32)out;
        }
    }
    ((u8 *)out)[0] = 1;
    return (u32)out;
}

/* +108, a write's first chunk: always refused */
u32 ds_header_fill(u32 *out, void *any, const u8 *header)
{
    (void)any;
    (void)header;
    out[0] = out[1] = out[2] = 0;
    rk_fail_in(out, 3, "devslots is read-only");
    return (u32)out;
}

/* +76: nothing is ever written (a delete lands here too, and changes nothing) */
void ds_commit_fill(void *any, const u8 *header, u32 ret)
{
    (void)any;
    (void)header;
    (void)ret;
}

void ds_register(void *self, u8 *registry)
{
    rk_add_route(self, registry, "/devslots", (void *)ds_list_invoker, 12, ROUTE_COPY, ROUTE_GROW);
    rk_add_route(self, registry, "/devslots/*", (void *)ds_file_invoker, 24, FILE_COPY, FILE_GROW);
}

/* From wr_add (route.c), after /modinfo's handler */
void ds_add(void)
{
    u32 *h = NEW(8);
    u32 owner;
    h[0] = (u32)&vtable[2];
    h[1] = 0;
    owner = (u32)h;
    REG_ADD(REGISTRY, &owner);
}

/* The entry points the firmware calls, as modinfo.c's (hidden result pointer in a0) */
__asm__(
"	.section .text.ds_entries,\"ax\",@progbits\n"
"	.globl	ds_root_entry\n"
"ds_root_entry:\n"
"	move.l	%a0,-(%sp)\n"
"	jsr	ds_root_fill\n"
"	addq.l	#4,%sp\n"
"	rts\n"
"	.globl	ds_list_invoker\n"
"ds_list_invoker:\n"
"	move.l	%a0,-(%sp)\n"
"	jsr	ds_list_fill\n"
"	addq.l	#4,%sp\n"
"	rts\n"
"	.globl	ds_file_invoker\n"
"ds_file_invoker:\n"
"	move.l	8(%sp),-(%sp)\n"
"	move.l	8(%sp),-(%sp)\n"
"	move.l	%a0,-(%sp)\n"
"	jsr	ds_file_fill\n"
"	lea	12(%sp),%sp\n"
"	rts\n"
"	.globl	ds_check_invoker\n"
"ds_check_invoker:\n"
"	move.l	(%sp),-(%sp)\n"
"	move.l	12(%sp),-(%sp)\n"
"	move.l	12(%sp),-(%sp)\n"
"	move.l	%a0,-(%sp)\n"
"	jsr	ds_check_fill\n"
"	lea	16(%sp),%sp\n"
"	rts\n"
"	.globl	ds_header_invoker\n"
"ds_header_invoker:\n"
"	move.l	8(%sp),-(%sp)\n"
"	move.l	8(%sp),-(%sp)\n"
"	move.l	%a0,-(%sp)\n"
"	jsr	ds_header_fill\n"
"	lea	12(%sp),%sp\n"
"	rts\n"
"	.globl	ds_commit_invoker\n"
"ds_commit_invoker:\n"
"	move.l	(%sp),-(%sp)\n"
"	move.l	12(%sp),-(%sp)\n"
"	move.l	12(%sp),-(%sp)\n"
"	jsr	ds_commit_fill\n"
"	lea	12(%sp),%sp\n"
"	rts\n"
"	.text\n");
