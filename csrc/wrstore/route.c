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
/* A user slot: DNX writes when & 0x6c == 0x6c. (0x12, write-protected, while there
 * was no writer: an info with empty callbacks ends in abort() on a write.) */
#define PERMISSIONS   0x7e

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

/* A refusal: ok 0 and the message, in a result of WORDS longs (the caller's size: 33
 * for a file's info, 2 for a pre-check, 3 for the header check). Writing more than
 * the caller has overruns its stack. */
static void fail_in(u32 *out, u32 words, const char *why)
{
    u8 alloc;
    for (u32 i = 0; i < words; i++)
        out[i] = 0;
    STR_CSTR(&out[1], why, &alloc);
}

static void fail(u32 *out, const char *why) { fail_in(out, RESULT_WORDS, why); }

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
static void fail_slot_in(u32 *out, u32 words, u32 n, const char *rule)
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
    fail_in(out, words, text);
}

static void fail_slot(u32 *out, u32 n, const char *rule) { fail_slot_in(out, RESULT_WORDS, n, rule); }

/* --- A slot's file: [128-byte index entry][table], through one RAM buffer ---------
 *
 * Measured in the emulator (docs/data-api-routes.md):
 * - the info's kind 1 makes the stock session read from / write to memory:
 *   MemoryStreamReader / MemoryStreamWriter (0x400efef6 / 0x400f00ac) at the info's
 *   +12 (an address) for +16 bytes;
 * - a READ open calls the info's callback at +28 first, with the info itself, and
 *   reads only after it says ok (0x400e9f7a). A write open does not;
 * - a WRITE calls the header validator at +108 on the first chunk, with a pointer to
 *   the container's 31-byte header (an empty one ends in abort());
 * - after the commit's own checks (footer, hash), the session calls the callback at
 *   +76 with a pointer to the header, or 0 if the transfer failed. Its result is
 *   ignored: the reply is already decided.
 * So the slot is staged in RAM. A read's pre-check fills the buffer from the +Drive
 * and sets the length. A write lands in the buffer, and only the commit callback,
 * after checking the entry and the table's hash, writes the +Drive: the table into
 * the slot's own extent, then the other group's index, then its superblock
 * (docs/waverider-store.md). Nothing touches the +Drive before that. One buffer
 * serves one transfer at a time, as DNX makes them. */
#define DRIVE_WRITE  ((int (*)(u32, u32, const void *))0x4012c780u)
#define TABLE_MAX    (SLOT_SECTORS * 512)              /* 512 KiB */
#define FILE_MAX     (ENTRY_BYTES + TABLE_MAX)
#define DATA_END     (DATA_START + SLOTS * SLOT_SECTORS)  /* 0x41000 */
#define CONTENT_KIND 0x57u                             /* 'W' (stock: 1 project, 3 sound, 5 kit) */

void wr_check_invoker(void);
void wr_header_invoker(void);
void wr_commit_invoker(void);

static u8 *stage __attribute__((section(".data"))) = 0;   /* FILE_MAX + 512, allocated once */

/* The probe reads this: the last write's outcome. 0 none yet, 1 written, else why not. */
struct wr_write { u32 magic, commits, last, slot, generation; };
volatile struct wr_write wr_write __attribute__((section(".data"))) = { 0x57525754u, 0, 0, 0, 0 };
enum { W_OK = 1, W_ABORTED, W_ENTRY, W_HASH, W_DRIVE, W_RANGE };

static void put32(u8 *p, u32 v) { p[0] = (u8)(v >> 24); p[1] = (u8)(v >> 16); p[2] = (u8)(v >> 8); p[3] = (u8)v; }

static void make_fn(struct fn *f, u32 n, void *invoker)
{
    u32 *closure = NEW(4);
    *closure = n;
    f->data[0] = closure;
    f->data[1] = 0;
    f->manager = MANAGER;
    f->invoker = invoker;
}

static u32 closure_slot(void *any) { return **(u32 **)any; }

/* The file invoker, read and write alike: kind 1 over the stage, at its full size
 * (a write's capacity). A read's pre-check then trims it to the slot's file. */
u32 wr_file_fill(u32 *out, void *any, void *args)
{
    u32 params[3] = { 0, 0, 0 }, n = 0, ok;
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
    if (!stage)
        stage = NEW(FILE_MAX + 512);
    for (u32 i = 0; i < RESULT_WORDS; i++)
        out[i] = 0;
    ((u8 *)out)[0] = 1;
    out[1] = EMPTY_STR;
    out[2] = CONTENT_KIND;                            /* info +0: the content kind */
    out[3] = 1;                                       /* +4 kind 1: a memory stream */
    ((u16 *)out)[8] = PERMISSIONS;                    /* +8 */
    out[5] = (u32)stage;                              /* +12 the stage */
    out[6] = FILE_MAX;                                /* +16 a write's capacity */
    out[7] = n;                                       /* +20 index: the container's slot byte */
    out[8] = 1;                                       /* +24 object version: store format 1 */
    make_fn((struct fn *)&out[2 + 7], n, (void *)wr_check_invoker);    /* +28 read pre-check */
    make_fn((struct fn *)&out[2 + 19], n, (void *)wr_commit_invoker);  /* +76 commit */
    make_fn((struct fn *)&out[2 + 27], n, (void *)wr_header_invoker);  /* +108 header check */
    return (u32)out;
}

/* +28, before a transfer: {u8 ok; std::string error}, 8 bytes. Both the read open
 * (0x400e9f7a, returning to 0x400e9fc2) and a write's first chunk (0x400ea266,
 * returning to 0x400ea2ae) call it, with the info. A read fills the stage with the
 * slot's entry and table and sets the info's length; a write keeps the full
 * capacity and passes. RET is where it was called from. 1.11 address: for 1.12,
 * find again the read open's `jsr (a1)` after `tstl %a4@(36)`. */
#define READ_OPEN_RETURN 0x400e9fc2u

u32 wr_check_fill(u32 *out, void *any, u8 *info, u32 ret)
{
    u32 n = closure_slot(any);
    u8 *index;
    const u8 *raw;
    u32 start, length;
    out[0] = 0;
    out[1] = EMPTY_STR;
    if (ret != READ_OPEN_RETURN) {
        ((u8 *)out)[0] = 1;
        return (u32)out;
    }
    index = read_index();
    if (!index || !(index[n * ENTRY_BYTES + 1] & 1)) {
        if (index)
            DELETE(index);
        fail_slot_in(out, 2, n, "empty");
        return (u32)out;
    }
    raw = index + n * ENTRY_BYTES;
    start = be32(raw + 12);
    length = be32(raw + 16);
    if (start != DATA_START + n * SLOT_SECTORS || !length || length > TABLE_MAX) {
        DELETE(index);
        fail_slot_in(out, 2, n, "the index entry is not valid for this slot");
        return (u32)out;
    }
    for (u32 i = 0; i < ENTRY_BYTES; i++)
        stage[i] = raw[i];
    DELETE(index);
    if (DRIVE_READ(REGION + start, (length + 511) & ~511u, stage + ENTRY_BYTES) < 0) {
        fail_slot_in(out, 2, n, "the +Drive read failed");
        return (u32)out;
    }
    *(u32 *)(info + 16) = ENTRY_BYTES + length;
    ((u8 *)out)[0] = 1;
    return (u32)out;
}

/* +108, a write's first chunk: the container header. -> {u8 ok; string; u8 value}. */
u32 wr_header_fill(u32 *out, void *any, const u8 *header)
{
    u32 n = closure_slot(any), length = be32(header + 25);
    out[0] = out[1] = out[2] = 0;
    if (be32(header + 13) != CONTENT_KIND) {
        fail_slot_in(out, 3, n, "the file is not a Waverider table (container kind)");
        return (u32)out;
    }
    if (be32(header + 17) != 1) {
        fail_slot_in(out, 3, n, "unknown store format version");
        return (u32)out;
    }
    if (header[29] != 0) {
        fail_slot_in(out, 3, n, "the body must be raw, not LZ4");
        return (u32)out;
    }
    if (length <= ENTRY_BYTES || length > FILE_MAX) {
        fail_slot_in(out, 3, n, "the file must be a 128-byte entry and a table of at most 512 KiB");
        return (u32)out;
    }
    ((u8 *)out)[0] = 1;
    out[1] = EMPTY_STR;
    ((u8 *)out)[8] = 1;
    return (u32)out;
}

/* +76, called with the header after an upload, or 0. 0 comes from two places, told
 * apart by the caller: a delete (0x5c, the stock delete 0x400ea3fc zeroes the stage
 * and calls this from 0x40127f8e) and a failed upload (from 0x401287a4). 1.11
 * addresses: for 1.12, find the delete's kind-1 arm again. */
#define DELETE_RETURN 0x40127f8eu
static void commit_index(u32 n, const u8 *entry);

void wr_commit_fill(void *any, const u8 *header, u32 ret)
{
    u32 n = closure_slot(any);
    u32 length, start, table_len, flags;
    u8 *entry = stage;

    wr_write.commits++;
    wr_write.slot = n;
    if (!header) {
        if (ret == DELETE_RETURN) {
            for (u32 i = 0; i < ENTRY_BYTES; i++)
                stage[i] = 0;
            commit_index(n, stage);           /* a free entry: the slot is gone */
            return;
        }
        wr_write.last = W_ABORTED;
        return;
    }
    length = be32(header + 25);
    table_len = length - ENTRY_BYTES;
    flags = (u32)entry[0] << 8 | entry[1];
    start = be32(entry + 12);
    if (!(flags & 1) || (entry[2] << 8 | entry[3]) != 1 || (entry[8] << 8 | entry[9]) != 1
            || start != DATA_START + n * SLOT_SECTORS || be32(entry + 16) != table_len
            || (u32)(entry[4] << 8 | entry[5]) * (u32)(entry[6] << 8 | entry[7]) * 2 != table_len) {
        wr_write.last = W_ENTRY;
        return;
    }
    if (XXH32(stage + ENTRY_BYTES, table_len, 0) != be32(entry + 20)) {
        wr_write.last = W_HASH;
        return;
    }
    if (REGION + start + SLOT_SECTORS > REGION + DATA_END) {
        wr_write.last = W_RANGE;
        return;
    }
    /* 1. the table, its last sector padded with zeros */
    for (u32 i = ENTRY_BYTES + table_len; i < ENTRY_BYTES + ((table_len + 511) & ~511u); i++)
        stage[i] = 0;
    if (DRIVE_WRITE(REGION + start, (table_len + 511) & ~511u, stage + ENTRY_BYTES) < 0) {
        wr_write.last = W_DRIVE;
        return;
    }
    commit_index(n, entry);
}

/* Steps 2 and 3: slot n's index entry becomes ENTRY (all zero frees it), in the group
 * that is not current, then its superblock with generation + 1. */
static void commit_index(u32 n, const u8 *entry)
{
    u8 *index, *sb;
    u32 generation = 0, target = 0, used = 0;
    /* 2. the index, into the group that is not current */
    index = read_index();
    if (index) {
        generation = wr_route.generation;
        target = wr_route.group ^ 1;
    } else {
        index = NEW(INDEX_BYTES);
        for (u32 i = 0; i < INDEX_BYTES; i++)
            index[i] = 0;
    }
    for (u32 i = 0; i < ENTRY_BYTES; i++)
        index[n * ENTRY_BYTES + i] = entry[i];
    for (u32 k = 0; k < SLOTS; k++)
        used += index[k * ENTRY_BYTES + 1] & 1;
    if (DRIVE_WRITE(REGION + target * GROUP_B + 1, INDEX_BYTES, index) < 0) {
        DELETE(index);
        wr_write.last = W_DRIVE;
        return;
    }
    /* 3. its superblock, generation + 1: the moment the change takes effect */
    sb = NEW(512);
    for (u32 i = 0; i < 512; i++)
        sb[i] = 0;
    sb[0] = 'W'; sb[1] = 'R'; sb[2] = 'T'; sb[3] = 'B';
    put32(sb + 4, 0x00010040u);
    put32(sb + 8, generation + 1);
    put32(sb + 12, used);
    put32(sb + 16, SLOTS);
    put32(sb + 20, ENTRY_BYTES);
    put32(sb + 24, XXH32(index, INDEX_BYTES, 0));
    put32(sb + 28, DATA_START);
    put32(sb + 32, DATA_END);
    put32(sb + 60, XXH32(sb, 60, 0));
    DELETE(index);
    if (DRIVE_WRITE(REGION + target * GROUP_B, 512, sb) < 0) {
        DELETE(sb);
        wr_write.last = W_DRIVE;
        return;
    }
    DELETE(sb);
    wr_write.generation = generation + 1;
    wr_write.last = W_OK;
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
"	.globl	wr_check_invoker\n"
"wr_check_invoker:\n"
"	move.l	(%sp),-(%sp)\n"
"	move.l	12(%sp),-(%sp)\n"
"	move.l	12(%sp),-(%sp)\n"
"	move.l	%a0,-(%sp)\n"
"	jsr	wr_check_fill\n"
"	lea	16(%sp),%sp\n"
"	rts\n"
"	.globl	wr_header_invoker\n"
"wr_header_invoker:\n"
"	move.l	8(%sp),-(%sp)\n"
"	move.l	8(%sp),-(%sp)\n"
"	move.l	%a0,-(%sp)\n"
"	jsr	wr_header_fill\n"
"	lea	12(%sp),%sp\n"
"	rts\n"
"	.globl	wr_commit_invoker\n"
"wr_commit_invoker:\n"
"	move.l	(%sp),-(%sp)\n"
"	move.l	12(%sp),-(%sp)\n"
"	move.l	12(%sp),-(%sp)\n"
"	jsr	wr_commit_fill\n"
"	lea	12(%sp),%sp\n"
"	rts\n"
"	.globl	wr_nop\n"
"wr_nop:\n"
"	rts\n"
"	.text\n");
