/* What our Data API routes share (route.c: /waverider, poolroute.c: /wavepool): the
 * firmware's routines a handler calls, the shapes it builds, and the helpers that build
 * them. docs/data-api-routes.md has the firmware this follows, DN2 1.11. */

#ifndef WRSTORE_ROUTEKIT_H
#define WRSTORE_ROUTEKIT_H

#include "store.h"

/* Our fill functions return u32 too: the firmware's code calls them (store.h). */
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

/* Where the stock session calls an info's callbacks from (1.11; for 1.12 find them
 * again): the read open's pre-check (after `tstl %a4@(36)`), and the delete's kind-1
 * arm, which calls the commit with 0 as a failed upload does. */
#define READ_OPEN_RETURN 0x400e9fc2u
#define DELETE_RETURN    0x40127f8eu

#define RESULT_WORDS 33                       /* a file's result: 4 + 4 + 124 bytes */

/* A refusal: ok 0 and the message, in a result of WORDS longs (the caller's size: 33
 * for a file's info, 2 for a pre-check, 3 for the header check). Writing more than
 * the caller has overruns its stack. */
void rk_fail_in(u32 *out, u32 words, const char *why);

/* The same with "PREFIX N: RULE", the shape DNX's messages use too */
void rk_fail_num_in(u32 *out, u32 words, const char *prefix, u32 n, const char *rule);

/* A std::function over a 4-byte closure holding N */
void rk_make_fn(struct fn *f, u32 n, void *invoker);

/* What rk_make_fn's closure holds, from the function's first argument */
static inline u32 rk_closure_slot(void *any) { return **(u32 **)any; }

/* One route: PATTERN with INVOKER into the route vector at registry + AT, as
 * ProjectHandler adds each of its patterns. AT 12 the directory routes (ROUTE_COPY,
 * ROUTE_GROW), 24 the file routes (FILE_COPY, FILE_GROW). */
void rk_add_route(void *self, u8 *registry, const char *text, void *invoker, u32 at,
                  void (*copy)(void *, const void *), void (*grow)(void *, const void *));

#endif
