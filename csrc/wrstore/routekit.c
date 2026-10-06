/* What our Data API routes share (routekit.h). */

#include "routekit.h"

void rk_fail_in(u32 *out, u32 words, const char *why)
{
    u8 alloc;
    for (u32 i = 0; i < words; i++)
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

void rk_fail_num_in(u32 *out, u32 words, const char *prefix, u32 n, const char *rule)
{
    char text[96];
    char *at = text;
    while (*prefix)
        *at++ = *prefix++;
    at = put_u32(at, n);
    *at++ = ':';
    *at++ = ' ';
    while (*rule && at < text + 95)
        *at++ = *rule++;
    *at = 0;
    rk_fail_in(out, words, text);
}

void rk_make_fn(struct fn *f, u32 n, void *invoker)
{
    u32 *closure = NEW(4);
    *closure = n;
    f->data[0] = closure;
    f->data[1] = 0;
    f->manager = MANAGER;
    f->invoker = invoker;
}

void rk_add_route(void *self, u8 *registry, const char *text, void *invoker, u32 at,
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
