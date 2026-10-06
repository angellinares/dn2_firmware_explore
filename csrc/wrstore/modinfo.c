/* The /modinfo route: what this image is modded with, for DNX to gate on
 * (docs/for-dnx-modinfo.md; the codec is dnfw.mods.modinfo).
 *
 * Built as /wavepool is (poolroute.c): `/` lists `modinfo` with one child; `/modinfo`
 * lists index 0 named `info`; `/modinfo/0` is a 256-byte file in the transfer container,
 * content kind 0x4D, object version 1, raw. It is read-only: a write is refused at its
 * first chunk. Stock firmware has no such path, and answers its own "invalid path".
 *
 * The record is wr_modinfo below. What this chunk can say for itself is filled in here,
 * from the same defines the routes use, so it can't drift from the code: the
 * capabilities, the pool's size and record version, the store's slots. What only the
 * build knows (the mods applied, the build tag, the commit, the image's id, the hash) is
 * written into the image after every mod is applied (`dnfw mods apply`), at the marker. */

#include "routekit.h"
#include "records.h"

#define INFO_KIND    0x4Du                  /* 'M' (a table is 0x57, a pool list 0x50) */
#define INFO_BYTES   256u
#define READ_ONLY    0x12u                  /* listed write-protected (route.c's note) */

/* the capabilities, one bit per thing DNX branches on; unknown bits must be ignored */
#define CAP_STORE    0x01u                  /* /waverider: list, read and write tables */
#define CAP_POOL     0x02u                  /* /wavepool: per-project pool lists */
#define CAP_RENAME   0x04u                  /* /waverider/<n>: a 128-byte body renames in place */
#define CAP_DELETE   0x08u                  /* /waverider/<n>: delete frees the slot */
#define CAP_CAS      0x10u                  /* /wavepool: a sent generation is a compare-and-swap */
#define CAP_PAGE     0x20u                  /* the instrument's wavetable page (PRESET/KIT page 2) */
#define CAPS (CAP_STORE | CAP_POOL | CAP_RENAME | CAP_DELETE | CAP_CAS | CAP_PAGE)

#define B16(v) (u8)((v) >> 8), (u8)(v)
#define B32(v) (u8)((v) >> 24), (u8)((v) >> 16), (u8)((v) >> 8), (u8)(v)

/* 0 magic, 4 version, 6 bytes, 8 caps, 12 pool slots, 14 pool record version,
 * 16 store slots, 18 zero; from 20 the build's part, its marker at 24 until written */
u8 wr_modinfo[INFO_BYTES] __attribute__((section(".data"), aligned(4))) = {   /* .data: GCC puts no const there */
    'D', 'N', 'M', 'I', B16(1), B16(INFO_BYTES), B32(CAPS),
    B16(POOL_ENTRIES), B16(RECORD_VERSION), B16(SLOTS), B16(0),
    B32(0),
    'M', 'O', 'D', 'I', 'N', 'F', 'O', '-', 'U', 'N', 'F', 'I', 'L', 'L', 'E', 'D',
};

void mi_root_entry(void);
void mi_list_invoker(void);
void mi_file_invoker(void);
void mi_check_invoker(void);
void mi_header_invoker(void);
void mi_commit_invoker(void);
void wr_nop(void);
void mi_register(void *self, u8 *registry);

static const u32 vtable[6] __attribute__((aligned(4))) = {
    0, TYPEINFO, (u32)wr_nop, (u32)wr_nop, (u32)mi_root_entry, (u32)mi_register,
};

static u8 *istage __attribute__((section(".data"))) = 0;   /* INFO_BYTES, allocated once */

u32 mi_root_fill(u32 *out)
{
    u8 alloc;
    STR_CSTR(out, "modinfo", &alloc);
    out[1] = 1;
    return (u32)out;
}

/* /modinfo's listing: index 0, `info`, always used */
u32 mi_list_fill(u32 *out)
{
    struct entry *e = NEW(sizeof(struct entry));
    u8 alloc;
    e->index = 0;
    e->size = INFO_BYTES;
    e->permissions = READ_ONLY;
    e->used = e->used2 = 1;
    e->zero = 0;
    e->pad[0] = e->pad[1] = e->pad[2] = 0;
    STR_CSTR(&e->name, "info", &alloc);
    ((u8 *)out)[0] = 1;
    out[1] = EMPTY_STR;
    out[2] = (u32)e;
    out[3] = (u32)(e + 1);
    out[4] = (u32)(e + 1);
    return (u32)out;
}

/* The file: kind 1 over a copy of the record (a write, refused at its header, never
 * reaches it; the stage keeps the record itself out of the session's hands) */
u32 mi_file_fill(u32 *out, void *any, void *args)
{
    u32 params[3] = { 0, 0, 0 }, i = 1, ok;
    (void)any;
    PATH_ARGS(params, args);
    ok = params[0] != params[1] && PARSE_U32(params[0], &i);
    STRVEC_DTOR(params);
    if (!ok || i != 0) {
        rk_fail_in(out, RESULT_WORDS, "modinfo: the only file is 0");
        return (u32)out;
    }
    if (!istage)
        istage = NEW(INFO_BYTES);
    for (u32 k = 0; k < RESULT_WORDS; k++)
        out[k] = 0;
    ((u8 *)out)[0] = 1;
    out[1] = EMPTY_STR;
    out[2] = INFO_KIND;                               /* info +0: the content kind */
    out[3] = 1;                                       /* +4 kind 1: a memory stream */
    ((u16 *)out)[8] = READ_ONLY;                      /* +8 */
    out[5] = (u32)istage;                             /* +12 the stage */
    out[6] = INFO_BYTES;                              /* +16 the length */
    out[7] = 0;                                       /* +20 index */
    out[8] = 1;                                       /* +24 object version: the record's */
    rk_make_fn((struct fn *)&out[2 + 7], 0, (void *)mi_check_invoker);    /* +28 read pre-check */
    rk_make_fn((struct fn *)&out[2 + 19], 0, (void *)mi_commit_invoker);  /* +76 commit */
    rk_make_fn((struct fn *)&out[2 + 27], 0, (void *)mi_header_invoker);  /* +108 header check */
    return (u32)out;
}

/* +28, before a transfer: a read gets the record */
u32 mi_check_fill(u32 *out, void *any, u8 *info, u32 ret)
{
    (void)any;
    (void)info;
    out[0] = 0;
    out[1] = EMPTY_STR;
    if (ret == READ_OPEN_RETURN)
        for (u32 k = 0; k < INFO_BYTES; k++)
            istage[k] = wr_modinfo[k];
    ((u8 *)out)[0] = 1;
    return (u32)out;
}

/* +108, a write's first chunk: always refused */
u32 mi_header_fill(u32 *out, void *any, const u8 *header)
{
    (void)any;
    (void)header;
    out[0] = out[1] = out[2] = 0;
    rk_fail_in(out, 3, "modinfo is read-only");
    return (u32)out;
}

/* +76: nothing is ever written (a delete lands here too, and changes nothing) */
void mi_commit_fill(void *any, const u8 *header, u32 ret)
{
    (void)any;
    (void)header;
    (void)ret;
}

void mi_register(void *self, u8 *registry)
{
    rk_add_route(self, registry, "/modinfo", (void *)mi_list_invoker, 12, ROUTE_COPY, ROUTE_GROW);
    rk_add_route(self, registry, "/modinfo/*", (void *)mi_file_invoker, 24, FILE_COPY, FILE_GROW);
}

/* From wr_add (route.c), after /wavepool's handler */
void mi_add(void)
{
    u32 *h = NEW(8);
    u32 owner;
    h[0] = (u32)&vtable[2];
    h[1] = 0;
    owner = (u32)h;
    REG_ADD(REGISTRY, &owner);
}

/* The entry points the firmware calls, as poolroute.c's (hidden result pointer in a0) */
__asm__(
"	.section .text.mi_entries,\"ax\",@progbits\n"
"	.globl	mi_root_entry\n"
"mi_root_entry:\n"
"	move.l	%a0,-(%sp)\n"
"	jsr	mi_root_fill\n"
"	addq.l	#4,%sp\n"
"	rts\n"
"	.globl	mi_list_invoker\n"
"mi_list_invoker:\n"
"	move.l	%a0,-(%sp)\n"
"	jsr	mi_list_fill\n"
"	addq.l	#4,%sp\n"
"	rts\n"
"	.globl	mi_file_invoker\n"
"mi_file_invoker:\n"
"	move.l	8(%sp),-(%sp)\n"
"	move.l	8(%sp),-(%sp)\n"
"	move.l	%a0,-(%sp)\n"
"	jsr	mi_file_fill\n"
"	lea	12(%sp),%sp\n"
"	rts\n"
"	.globl	mi_check_invoker\n"
"mi_check_invoker:\n"
"	move.l	(%sp),-(%sp)\n"
"	move.l	12(%sp),-(%sp)\n"
"	move.l	12(%sp),-(%sp)\n"
"	move.l	%a0,-(%sp)\n"
"	jsr	mi_check_fill\n"
"	lea	16(%sp),%sp\n"
"	rts\n"
"	.globl	mi_header_invoker\n"
"mi_header_invoker:\n"
"	move.l	8(%sp),-(%sp)\n"
"	move.l	8(%sp),-(%sp)\n"
"	move.l	%a0,-(%sp)\n"
"	jsr	mi_header_fill\n"
"	lea	12(%sp),%sp\n"
"	rts\n"
"	.globl	mi_commit_invoker\n"
"mi_commit_invoker:\n"
"	move.l	(%sp),-(%sp)\n"
"	move.l	12(%sp),-(%sp)\n"
"	move.l	12(%sp),-(%sp)\n"
"	jsr	mi_commit_fill\n"
"	lea	12(%sp),%sp\n"
"	rts\n"
"	.text\n");
