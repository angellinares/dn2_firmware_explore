/* The /waverider route, step 1: read-only. DNX lists `/` and sees `waverider`, and
 * lists `/waverider` and sees the store's 256 slots (docs/waverider-store.md).
 *
 * docs/data-api-routes.md has the firmware this follows, DN2 1.11:
 * - a handler is a C++ object with a 4-slot vtable: two destructors, the root entry
 *   (`{std::string name, u32 children}`, hidden result pointer in a0), and
 *   register_route(this, registry);
 * - `0x400ead92(registry, &unique_ptr)` calls register_route and appends the handler,
 *   and `/` is built from the handlers it holds;
 * - a directory route is a pattern plus a std::function whose invoker (result
 *   pointer in a0) returns `{u8 ok; std::string error; vector<entry>}`, with
 *   20-byte entries.
 * The start-up builder 0x4002b8c8 adds ours after the kits handler (the hook at
 * 0x4002bb70, which also sets the builder's "built" flag, as stock does there).
 *
 * The listing reads the store from the +Drive with the stock block driver: both
 * groups' superblocks, then the current group's index. A slot is used when its
 * entry's flags say so. Nothing here writes to the +Drive. */

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;

/* The firmware returns every value in d0. This GCC (m68k-linux) returns pointers in
 * a0, so nothing called here is declared to return a pointer: values are u32, and
 * our own fill functions return u32 too. */
#define NEW_RAW      ((u32 (*)(u32))0x40120264u)
#define NEW(n)       ((void *)NEW_RAW(n))
#define DELETE       ((void (*)(void *))0x40120270u)
#define STR_CSTR     ((void (*)(void *, const char *, void *))0x401ce69eu)
#define STR_DTOR     ((void (*)(void *))0x401ccbeeu)
#define SPLIT        ((void (*)(void *, void *))0x400ec394u)
#define ROUTE_COPY   ((void (*)(void *, const void *))0x401b276au)
#define ROUTE_GROW   ((void (*)(void *, const void *))0x401b2b00u)
#define FN_DTOR      ((void (*)(void *))0x40188086u)
#define STRVEC_DTOR  ((void (*)(void *))0x4018dc80u)
#define REG_ADD      ((void (*)(void *, void *))0x400ead92u)
#define FILE_COPY    ((void (*)(void *, const void *))0x401b27b8u)    /* file routes: copy at end */
#define FILE_GROW    ((void (*)(void *, const void *))0x401b28d8u)    /* file routes: grow */
#define PATH_ARGS    ((void (*)(void *, void *))0x401b250eu)          /* (vector<string> *out, args) */
#define PARSE_U32    ((u32 (*)(u32, u32 *))0x401510ecu)              /* (string, &n) -> bool */
#define REGISTRY     ((u8 *)0x4059cd24u)
#define BUILT_FLAG   (*(volatile u8 *)0x4059cd20u)
#define MANAGER      ((void *)0x400eb0b6u)  /* ProjectHandler's: a 4-byte closure */
#define EMPTY_STR    0x44647a74u            /* the empty std::string's pointer */
#define TYPEINFO     0x401feb54u            /* RouteTypeHandler's typeinfo */
#define DRIVE_READ   ((int (*)(u32, u32, void *))0x4012c59au)
#define XXH32        ((u32 (*)(const void *, u32, u32))0x4014be0eu)

#define REGION        0x600000u
#define GROUP_B       0x400u
#define SLOTS         256
#define DATA_START    0x1000u               /* sectors, from the region's start */
#define SLOT_SECTORS  1024u                 /* 512 KiB: slot n's fixed extent */
#define ENTRY_BYTES   128
#define INDEX_BYTES   (SLOTS * ENTRY_BYTES)
#define SLOT_SIZE     524288u               /* the fixed 512 KiB extent every slot reports */
#define PERMISSIONS   0x7e                  /* a user slot: DNX writes when & 0x6c == 0x6c */

struct fn { void *data[2]; void *manager; void *invoker; };       /* std::function, 16 B */
struct route { void *comps[3]; struct fn fn; };                    /* 28 B */
struct entry {                                                     /* 20 B, as /projects' */
    u32 index;
    u32 name;                 /* std::string */
    u32 size;
    u16 permissions;
    u8 used, used2;
    u8 zero, pad[3];
};

void wr_root_entry(void);
void wr_list_invoker(void);
void wr_nop(void);
void wr_register(void *self, u8 *registry);
void wr_file_invoker(void);

/* offset-to-top, typeinfo, then the four slots */
static const u32 vtable[6] __attribute__((aligned(4))) = {
    0, TYPEINFO, (u32)wr_nop, (u32)wr_nop, (u32)wr_root_entry, (u32)wr_register,
};

/* The probe reads this (PEEK): what the last listing found. */
struct wr_route { u32 magic, lists, group, generation, used, read_errors; };
volatile struct wr_route wr_route __attribute__((section(".data"))) = { 0x57525254u, 0, 0, 0, 0, 0 };

static u32 be32(const u8 *p) { return (u32)p[0] << 24 | (u32)p[1] << 16 | (u32)p[2] << 8 | p[3]; }

/* -> the superblock's generation if it checks (magic, version, sizes, own hash), else 0 */
static u32 superblock_ok(const u8 *sb, u32 *index_hash)
{
    if (sb[0] != 'W' || sb[1] != 'R' || sb[2] != 'T' || sb[3] != 'B'
            || be32(sb + 4) != 0x00010040u || be32(sb + 16) != SLOTS
            || be32(sb + 20) != ENTRY_BYTES || be32(sb + 60) != XXH32(sb, 60, 0))
        return 0;
    *index_hash = be32(sb + 24);
    return be32(sb + 8) ? be32(sb + 8) : 0;
}

/* -> the current group's index (INDEX_BYTES, to be freed), or 0 for an empty store */
static u8 *read_index(void)
{
    u8 *sb = NEW(512), *index = NEW(INDEX_BYTES), *chosen = 0;
    u32 best = 0;
    for (u32 g = 0; g < 2; g++) {
        u32 base = REGION + g * GROUP_B, hash, gen;
        if (DRIVE_READ(base, 512, sb) < 0) {
            wr_route.read_errors++;
            continue;
        }
        gen = superblock_ok(sb, &hash);
        if (!gen || gen <= best)                  /* a tie keeps A, read first */
            continue;
        if (DRIVE_READ(base + 1, INDEX_BYTES, index) < 0) {
            wr_route.read_errors++;
            continue;
        }
        if (XXH32(index, INDEX_BYTES, 0) != hash)
            continue;
        best = gen;
        wr_route.group = g;
        if (!chosen)
            chosen = NEW(INDEX_BYTES);
        for (u32 i = 0; i < INDEX_BYTES; i++)
            chosen[i] = index[i];
    }
    DELETE(sb);
    DELETE(index);
    wr_route.generation = best;
    return chosen;
}

/* The root entry: "waverider", 256 slots. */
u32 wr_root_fill(u32 *out)
{
    u8 alloc;
    STR_CSTR(out, "waverider", &alloc);
    out[1] = SLOTS;
    return (u32)out;
}

/* /waverider's listing: {ok, error, vector of 256 entries}, slot n at index n. */
u32 wr_list_fill(u32 *out)
{
    struct entry *v = NEW(SLOTS * sizeof(struct entry));
    u8 *index = read_index();
    u32 used = 0;
    for (u32 n = 0; n < SLOTS; n++) {
        struct entry *e = &v[n];
        const u8 *raw = index ? index + n * ENTRY_BYTES : 0;
        u32 in_use = raw && (raw[1] & 1);
        char name[64];
        e->index = n;
        e->size = SLOT_SIZE;
        e->permissions = PERMISSIONS;
        e->used = e->used2 = in_use ? 1 : 0;
        e->zero = 0;
        e->pad[0] = e->pad[1] = e->pad[2] = 0;
        e->name = EMPTY_STR;
        if (in_use) {
            u8 alloc;
            for (u32 i = 0; i < 63; i++)
                name[i] = (char)raw[32 + i];
            name[63] = 0;
            STR_CSTR(&e->name, name, &alloc);
            used++;
        }
    }
    if (index)
        DELETE(index);
    wr_route.lists++;
    wr_route.used = used;
    ((u8 *)out)[0] = 1;
    out[1] = EMPTY_STR;
    out[2] = (u32)v;
    out[3] = (u32)(v + SLOTS);
    out[4] = (u32)(v + SLOTS);
    return (u32)out;
}

/* A slot's file, as the file routes return it: {u8 ok; std::string error;
 * FileStorageInfo, 124 B} (0x400eb6d4; copied by 0x401b1cc8). A failure is ok 0, the
 * message, and a zero info (0x401b24c8). Kind 2 is streamed by the stock eMMC reader
 * 0x400f0270(byte offset, size, 64 KiB) with no filter, since every std::function in
 * the info is empty. So reading /waverider/<n> gives the slot's payload: its
 * byteLength bytes, as stored. */
#define RESULT_WORDS 33                       /* 4 + 4 + 124 bytes */

static void fail(u32 *out, const char *why)
{
    u8 alloc;
    for (u32 i = 0; i < RESULT_WORDS; i++)
        out[i] = 0;
    STR_CSTR(&out[1], why, &alloc);
}

static char *put_u32(char *at, u32 n)
{
    char digits[10];
    u32 k = 0;
    do {
        digits[k++] = (char)('0' + n % 10);
        n /= 10;
    } while (n);
    while (k)
        *at++ = digits[--k];
    return at;
}

/* "slot N: RULE", the shape DNX's messages use too */
static void fail_slot(u32 *out, u32 n, const char *rule)
{
    char text[80];
    char *at = text;
    for (const char *w = "slot "; *w; w++)
        *at++ = *w;
    at = put_u32(at, n);
    *at++ = ':';
    *at++ = ' ';
    while (*rule && at < text + 79)
        *at++ = *rule++;
    *at = 0;
    fail(out, text);
}

u32 wr_file_fill(u32 *out, void *any, void *args)
{
    u32 params[3] = { 0, 0, 0 }, n = 0, ok;
    u8 *index;
    (void)any;
    PATH_ARGS(params, args);
    ok = params[0] != params[1] && PARSE_U32(params[0], &n);
    STRVEC_DTOR(params);
    if (!ok) {
        fail(out, "waverider: the slot is not a number");
        return (u32)out;
    }
    if (n >= SLOTS) {
        fail_slot(out, n, "out of range, the slots are 0..255");
        return (u32)out;
    }
    index = read_index();
    if (!index || !(index[n * ENTRY_BYTES + 1] & 1)) {
        if (index)
            DELETE(index);
        fail_slot(out, n, "empty");
        return (u32)out;
    }
    {
        const u8 *raw = index + n * ENTRY_BYTES;
        u32 start = be32(raw + 12), length = be32(raw + 16);
        DELETE(index);
        if (start != DATA_START + n * SLOT_SECTORS) {
            fail_slot(out, n, "the index puts it outside its own extent");
            return (u32)out;
        }
        if (!length || length > SLOT_SECTORS * 512) {
            fail_slot(out, n, "the index gives a length of 0 or over 512 KiB");
            return (u32)out;
        }
        for (u32 i = 0; i < RESULT_WORDS; i++)
            out[i] = 0;
        ((u8 *)out)[0] = 1;
        out[1] = EMPTY_STR;
        out[2] = 1;                                   /* info +0, 1 as for /projects */
        out[3] = 2;                                   /* +4 kind 2: the eMMC stream */
        /* +8: write-protected (0x12) until step 2's writer exists. The stock write path
         * calls the info's writer callback unconditionally, and an empty one ends in
         * abort() (0x40138d92, measured in the emulator): with 0x12 the stock open
         * refuses the write instead, while a read only needs bit 1. The listing still
         * says 0x7e, the contract. */
        ((u16 *)out)[8] = 0x12;
        out[5] = (REGION + start) * 512;              /* +12 the byte offset: < 4 GiB */
        out[6] = length;                              /* +16 size */
        out[7] = n;                                   /* +20 index */
        out[8] = length;                              /* +24 stored length */
    }
    return (u32)out;
}

/* One route: PATTERN with INVOKER into the route vector at registry + AT, as
 * ProjectHandler adds each of its patterns. */
static void add_route(void *self, u8 *registry, const char *text, void *invoker, u32 at,
                      void (*copy)(void *, const void *), void (*grow)(void *, const void *))
{
    u8 alloc;
    u32 pattern;
    struct route r;
    u32 *closure = NEW(4);
    u32 *end = (u32 *)(registry + at + 4), *cap = (u32 *)(registry + at + 8);

    r.comps[0] = r.comps[1] = r.comps[2] = 0;
    r.fn.data[1] = 0;
    *closure = (u32)self;
    STR_CSTR(&pattern, text, &alloc);
    SPLIT(&pattern, r.comps);
    r.fn.data[0] = closure;
    r.fn.manager = MANAGER;
    r.fn.invoker = invoker;
    if (*end != *cap) {
        if (*end)
            copy((void *)*end, &r);
        *end += sizeof(struct route);
    } else {
        grow(registry + at, &r);
    }
    FN_DTOR(&r.fn);
    STRVEC_DTOR(r.comps);
    STR_DTOR(&pattern);
}

/* register_route(this, registry): /waverider into the directory routes (+12), as
 * /projects; /waverider/<n> into the file routes (+24), as /projects/<n>. */
void wr_register(void *self, u8 *registry)
{
    add_route(self, registry, "/waverider", (void *)wr_list_invoker, 12, ROUTE_COPY, ROUTE_GROW);
    add_route(self, registry, "/waverider/*", (void *)wr_file_invoker, 24, FILE_COPY, FILE_GROW);
}

/* The hook at 0x4002bb70: add our handler, then set the builder's flag as stock does. */
void wr_add(void)
{
    u32 *h = NEW(8);
    u32 owner;
    h[0] = (u32)&vtable[2];
    h[1] = 0;
    owner = (u32)h;
    REG_ADD(REGISTRY, &owner);
    BUILT_FLAG = 1;
}

/* The entry points the firmware calls with a hidden result pointer in a0. */
__asm__(
"	.section .text.wr_entries,\"ax\",@progbits\n"
"	.globl	wr_root_entry\n"
"wr_root_entry:\n"
"	move.l	%a0,-(%sp)\n"
"	jsr	wr_root_fill\n"
"	addq.l	#4,%sp\n"
"	rts\n"
"	.globl	wr_list_invoker\n"
"wr_list_invoker:\n"
"	move.l	%a0,-(%sp)\n"
"	jsr	wr_list_fill\n"
"	addq.l	#4,%sp\n"
"	rts\n"
"	.globl	wr_file_invoker\n"
"wr_file_invoker:\n"
"	move.l	8(%sp),-(%sp)\n"
"	move.l	8(%sp),-(%sp)\n"
"	move.l	%a0,-(%sp)\n"
"	jsr	wr_file_fill\n"
"	lea	12(%sp),%sp\n"
"	rts\n"
"	.globl	wr_nop\n"
"wr_nop:\n"
"	rts\n"
"	.text\n");
