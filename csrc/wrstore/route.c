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
#define ENTRY_BYTES   128
#define INDEX_BYTES   (SLOTS * ENTRY_BYTES)
#define SLOT_SIZE     131072u               /* the fixed 128 KiB extent every slot reports */
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

/* register_route(this, registry): the one pattern, /waverider, into the directory
 * routes (registry + 12), as ProjectHandler adds /projects. */
void wr_register(void *self, u8 *registry)
{
    u8 alloc;
    u32 pattern;
    struct route r;
    u32 *closure = NEW(4);
    u32 *end = (u32 *)(registry + 16), *cap = (u32 *)(registry + 20);

    r.comps[0] = r.comps[1] = r.comps[2] = 0;
    r.fn.data[1] = 0;
    *closure = (u32)self;
    STR_CSTR(&pattern, "/waverider", &alloc);
    SPLIT(&pattern, r.comps);
    r.fn.data[0] = closure;
    r.fn.manager = MANAGER;
    r.fn.invoker = (void *)wr_list_invoker;
    if (*end != *cap) {
        if (*end)
            ROUTE_COPY((void *)*end, &r);
        *end += sizeof(struct route);
    } else {
        ROUTE_GROW(registry + 12, &r);
    }
    FN_DTOR(&r.fn);
    STRVEC_DTOR(r.comps);
    STR_DTOR(&pattern);
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
"	.globl	wr_nop\n"
"wr_nop:\n"
"	rts\n"
"	.text\n");
