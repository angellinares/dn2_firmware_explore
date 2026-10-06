/* The /wavepool route: each project's pool list, read and written whole
 * (docs/for-dnx-waverider-pool.md §2, the records in records.c).
 *
 * A second handler beside /waverider's, built the same way (route.c,
 * docs/data-api-routes.md): `/` lists `wavepool` with 129 children; `/wavepool` lists
 * project slots 0..128, 0 named `working`; `/wavepool/<p>` is a 512-byte file in the
 * transfer container, content kind 0x50, object version 2 (the record's), index p, raw.
 * A version 1 write (127 entries) is accepted and stored as version 2 (records.c); the
 * container's version and the record's must agree.
 * - A read returns what project slot p plays (wr_record_resolve): its stored record,
 *   or with none generation 0, the automatic flag and the automatic pool's entries.
 * - A write is checked whole at the commit (wr_record_check: an automatic record must
 *   carry no entries), then written to the sector that is not current with
 *   generation + 1. A non-zero generation sent must be the current one (0 for a slot
 *   with no record), or the write is refused: two writers can't lose each other's edit. A write to record 0 makes Waverider refill its pool
 *   (wr_store.changes). As with /waverider, a refusal at the commit is silent: the
 *   session has already answered. wp_write says what happened.
 * - A delete answers as the stock session does and changes nothing. */

#include "routekit.h"
#include "records.h"

#define POOL_KIND   0x50u                   /* 'P' (a table is 0x57) */

void wp_root_entry(void);
void wp_list_invoker(void);
void wp_file_invoker(void);
void wp_check_invoker(void);
void wp_header_invoker(void);
void wp_commit_invoker(void);
void wr_nop(void);
void wp_register(void *self, u8 *registry);

static const u32 vtable[6] __attribute__((aligned(4))) = {
    0, TYPEINFO, (u32)wr_nop, (u32)wr_nop, (u32)wp_root_entry, (u32)wp_register,
};

/* The probe reads this: the last write's outcome. last: 0 none yet, 1 written,
 * 2 aborted or deleted, 3 the +Drive write failed, 16 + WP_* refused. */
struct wp_write { u32 magic, commits, last, project, generation; };
volatile struct wp_write wp_write __attribute__((section(".data"))) = { 0x57505754u, 0, 0, 0, 0 };
enum { P_OK = 1, P_ABORTED, P_DRIVE, P_REFUSED = 16 };

static u8 *pstage __attribute__((section(".data"))) = 0;   /* RECORD_BYTES, allocated once */
static u32 sent_version __attribute__((section(".data"))) = 0;   /* the write's container version */

u32 wp_root_fill(u32 *out)
{
    u8 alloc;
    STR_CSTR(out, "wavepool", &alloc);
    out[1] = PROJECT_SLOTS;
    return (u32)out;
}

static void slot_name(char *at, u32 p)
{
    const char *w = "working";
    char digits[4];
    u32 k = 0;
    if (!p) {
        while ((*at++ = *w++))
            ;
        return;
    }
    do {
        digits[k++] = (char)('0' + p % 10);
        p /= 10;
    } while (p);
    while (k)
        *at++ = digits[--k];
    *at = 0;
}

/* /wavepool's listing: project slot p at index p; used when it has a stored record */
u32 wp_list_fill(u32 *out)
{
    struct entry *v = NEW(PROJECT_SLOTS * sizeof(struct entry));
    u8 *rec = NEW(RECORD_BYTES);
    for (u32 p = 0; p < PROJECT_SLOTS; p++) {
        struct entry *e = &v[p];
        char name[8];
        u8 alloc;
        u32 used = wr_record_read(p, rec) != 0;
        e->index = p;
        e->size = RECORD_BYTES;
        e->permissions = PERMISSIONS;
        e->used = e->used2 = used ? 1 : 0;
        e->zero = 0;
        e->pad[0] = e->pad[1] = e->pad[2] = 0;
        slot_name(name, p);
        STR_CSTR(&e->name, name, &alloc);
    }
    DELETE(rec);
    ((u8 *)out)[0] = 1;
    out[1] = EMPTY_STR;
    out[2] = (u32)v;
    out[3] = (u32)(v + PROJECT_SLOTS);
    out[4] = (u32)(v + PROJECT_SLOTS);
    return (u32)out;
}

static void fail_project_in(u32 *out, u32 words, u32 p, const char *rule)
{
    rk_fail_num_in(out, words, "project slot ", p, rule);
}

/* The file invoker, read and write alike: kind 1 over the stage (route.c's shape) */
u32 wp_file_fill(u32 *out, void *any, void *args)
{
    u32 params[3] = { 0, 0, 0 }, p = 0, ok;
    (void)any;
    PATH_ARGS(params, args);
    ok = params[0] != params[1] && PARSE_U32(params[0], &p);
    STRVEC_DTOR(params);
    if (!ok) {
        rk_fail_in(out, RESULT_WORDS, "wavepool: the project slot is not a number");
        return (u32)out;
    }
    if (p >= PROJECT_SLOTS) {
        fail_project_in(out, RESULT_WORDS, p, "out of range, the project slots are 0..128");
        return (u32)out;
    }
    if (!pstage)
        pstage = NEW(RECORD_BYTES);
    for (u32 i = 0; i < RESULT_WORDS; i++)
        out[i] = 0;
    ((u8 *)out)[0] = 1;
    out[1] = EMPTY_STR;
    out[2] = POOL_KIND;                               /* info +0: the content kind */
    out[3] = 1;                                       /* +4 kind 1: a memory stream */
    ((u16 *)out)[8] = PERMISSIONS;                    /* +8 */
    out[5] = (u32)pstage;                             /* +12 the stage */
    out[6] = RECORD_BYTES;                            /* +16 the length, both ways */
    out[7] = p;                                       /* +20 index: the container's slot byte */
    out[8] = RECORD_VERSION;                          /* +24 object version: the record's */
    rk_make_fn((struct fn *)&out[2 + 7], p, (void *)wp_check_invoker);    /* +28 read pre-check */
    rk_make_fn((struct fn *)&out[2 + 19], p, (void *)wp_commit_invoker);  /* +76 commit */
    rk_make_fn((struct fn *)&out[2 + 27], p, (void *)wp_header_invoker);  /* +108 header check */
    return (u32)out;
}

/* +28, before a transfer: a read fills the stage with what project slot p plays */
u32 wp_check_fill(u32 *out, void *any, u8 *info, u32 ret)
{
    u32 p = rk_closure_slot(any);
    (void)info;
    out[0] = 0;
    out[1] = EMPTY_STR;
    if (ret == READ_OPEN_RETURN) {
        u8 *index = wr_store_index();
        wr_record_resolve(p, pstage, index);
        if (index)
            DELETE(index);
    }
    ((u8 *)out)[0] = 1;
    return (u32)out;
}

/* +108, a write's first chunk: the container header */
u32 wp_header_fill(u32 *out, void *any, const u8 *header)
{
    u32 p = rk_closure_slot(any);
    out[0] = out[1] = out[2] = 0;
    if (be32(header + 13) != POOL_KIND) {
        fail_project_in(out, 3, p, "the file is not a pool list (container kind)");
        return (u32)out;
    }
    if (be32(header + 17) != 1 && be32(header + 17) != RECORD_VERSION) {
        fail_project_in(out, 3, p, "unknown pool list version");
        return (u32)out;
    }
    sent_version = be32(header + 17);        /* the record's own must say the same */
    if (header[29] != 0) {
        fail_project_in(out, 3, p, "the body must be raw, not LZ4");
        return (u32)out;
    }
    if (be32(header + 25) != RECORD_BYTES) {
        fail_project_in(out, 3, p, "a pool list is 512 bytes");
        return (u32)out;
    }
    ((u8 *)out)[0] = 1;
    out[1] = EMPTY_STR;
    ((u8 *)out)[8] = 1;
    return (u32)out;
}

/* +76, after the transfer: check the record whole, then write it */
void wp_commit_fill(void *any, const u8 *header, u32 ret)
{
    u32 p = rk_closure_slot(any), why, generation;
    (void)ret;
    wp_write.commits++;
    wp_write.project = p;
    if (!header) {                                    /* a failed upload, or a delete */
        wp_write.last = P_ABORTED;
        return;
    }
    why = be16(pstage + R_VERSION) != sent_version ? WP_VERSION : wr_record_check(pstage, p);
    if (!why && be32(pstage + R_GEN)) {
        /* a compare-and-swap: a writer that sends the generation it read is refused when
         * another writer (the instrument's pool page, DNX) has written since. 0: no check */
        u8 *now = NEW(RECORD_BYTES);
        if (wr_record_read(p, now) != be32(pstage + R_GEN))
            why = WP_STALE;
        DELETE(now);
    }
    if (why) {
        wp_write.last = P_REFUSED + why;
        return;
    }
    generation = wr_record_write(p, pstage);
    if (!generation) {
        wp_write.last = P_DRIVE;
        return;
    }
    wp_write.generation = generation;
    if (!p)
        wr_store.changes++;                           /* the working pool changed: refill */
    wp_write.last = P_OK;
}

/* register_route: /wavepool with the directory routes, /wavepool/<p> with the files */
void wp_register(void *self, u8 *registry)
{
    rk_add_route(self, registry, "/wavepool", (void *)wp_list_invoker, 12, ROUTE_COPY, ROUTE_GROW);
    rk_add_route(self, registry, "/wavepool/*", (void *)wp_file_invoker, 24, FILE_COPY, FILE_GROW);
}

/* From wr_add (route.c), after /waverider's handler */
void wp_add(void)
{
    u32 *h = NEW(8);
    u32 owner;
    h[0] = (u32)&vtable[2];
    h[1] = 0;
    owner = (u32)h;
    REG_ADD(REGISTRY, &owner);
}

/* The entry points the firmware calls, as route.c's (hidden result pointer in a0) */
__asm__(
"	.section .text.wp_entries,\"ax\",@progbits\n"
"	.globl	wp_root_entry\n"
"wp_root_entry:\n"
"	move.l	%a0,-(%sp)\n"
"	jsr	wp_root_fill\n"
"	addq.l	#4,%sp\n"
"	rts\n"
"	.globl	wp_list_invoker\n"
"wp_list_invoker:\n"
"	move.l	%a0,-(%sp)\n"
"	jsr	wp_list_fill\n"
"	addq.l	#4,%sp\n"
"	rts\n"
"	.globl	wp_file_invoker\n"
"wp_file_invoker:\n"
"	move.l	8(%sp),-(%sp)\n"
"	move.l	8(%sp),-(%sp)\n"
"	move.l	%a0,-(%sp)\n"
"	jsr	wp_file_fill\n"
"	lea	12(%sp),%sp\n"
"	rts\n"
"	.globl	wp_check_invoker\n"
"wp_check_invoker:\n"
"	move.l	(%sp),-(%sp)\n"
"	move.l	12(%sp),-(%sp)\n"
"	move.l	12(%sp),-(%sp)\n"
"	move.l	%a0,-(%sp)\n"
"	jsr	wp_check_fill\n"
"	lea	16(%sp),%sp\n"
"	rts\n"
"	.globl	wp_header_invoker\n"
"wp_header_invoker:\n"
"	move.l	8(%sp),-(%sp)\n"
"	move.l	8(%sp),-(%sp)\n"
"	move.l	%a0,-(%sp)\n"
"	jsr	wp_header_fill\n"
"	lea	12(%sp),%sp\n"
"	rts\n"
"	.globl	wp_commit_invoker\n"
"wp_commit_invoker:\n"
"	move.l	(%sp),-(%sp)\n"
"	move.l	12(%sp),-(%sp)\n"
"	move.l	12(%sp),-(%sp)\n"
"	jsr	wp_commit_fill\n"
"	lea	12(%sp),%sp\n"
"	rts\n"
"	.text\n");
