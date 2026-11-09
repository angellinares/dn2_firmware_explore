/* The LFO4 page says why a sound has no LFO4.
 *
 * `store.c` refuses a stored sound whose LFO4 values are out of range and
 * marks it. When [MOD] brings up MOD (4/4) and a track of the current kit is
 * marked, a stock two-line box opens (`note.S`, the prompt reloadconfirm
 * uses), and any answer closes it:
 *
 *     T3 T7: LFO4 AREA HOLDS
 *     DATA LFO4 DIDN'T WRITE :)
 *
 * The box is 107 px wide inside, and the font advances 4 px for a character
 * and 3 for a space (measured on reloadconfirm's prompt in the emulator). Two
 * tracks fit, even T10 T16 (91 px). Three or more read "3 TRACKS:".
 *
 * It opens from the key handler, after stock's page select has run: the place
 * reloadconfirm opens its prompt from, never from a draw. The mode object is
 * the one the header hook saw (`page.c`); its `+144` is the page shown, 0-based
 * (read in the emulator: 0..3 for MOD 1/4..4/4). Two routes reach page 4/4:
 * [MOD] into the mode when 4/4 is the page it remembers (the key handler's
 * page-key case), and [MOD] within the mode, which calls the page setter
 * 0x40063ade(mode, index).
 *
 * One subject: when the note opens, and what it says.
 */
#include "ext.h"

#define KIT          0x800052A0u      /* the current kit (engine gate, `emu_boot_engine.py`) */
#define KIT_SOUNDS   52u              /* its first track sound */
#define SOUND_BYTES  1163u
#define TRACKS       16u
#define MOD_KEY      5u               /* key code 6, less one, as the handler switches */
#define PAGE_SHOWN   144u             /* the mode's page, 0-based: 3 is MOD (4/4) */
#define LFO4_INDEX   3u

extern u32 lfo4_mod_mode;
int lfo4_is_marked(u32 key);
void lfo4_note_open(const char *line1, const char *line2);

u32 lfo4_notes;
static char line1[32];
static const char LINE2[] = "DATA LFO4 DIDN'T WRITE :)";
static const char TAIL[] = " LFO4 AREA HOLDS";

static char *put(char *at, const char *s)
{
    while (*s)
        *at++ = *s++;
    return at;
}

static char *number(char *at, u32 n)
{
    if (n >= 10u)
        *at++ = (char)('0' + n / 10u);
    *at++ = (char)('0' + n % 10u);
    return at;
}

static void check(u32 mode)
{
    u32 kit, t, n = 0, first = 0, second = 0;
    char *at = line1;

    if (!mode || mode != lfo4_mod_mode)
        return;
    if (*(volatile u32 *)(mode + PAGE_SHOWN) != LFO4_INDEX)
        return;
    kit = *(volatile u32 *)KIT;
    if (!kit)
        return;
    for (t = 0; t < TRACKS; t++)
        if (lfo4_is_marked(kit + KIT_SOUNDS + SOUND_BYTES * t)) {
            if (!n)
                first = t + 1u;
            else if (n == 1u)
                second = t + 1u;
            n++;
        }
    if (!n)
        return;
    if (n <= 2u) {
        *at++ = 'T';
        at = number(at, first);
        if (n == 2u) {
            at = put(at, " T");
            at = number(at, second);
        }
    } else {
        at = number(at, n);
        at = put(at, " TRACKS");
    }
    *at++ = ':';
    at = put(at, TAIL);
    *at = 0;
    lfo4_notes++;
    lfo4_note_open(line1, LINE2);
}

/* [MOD] into the mode, from the key handler, after the page select. */
void lfo4_page_key(u32 key)
{
    if (key == MOD_KEY)
        check(lfo4_mod_mode);
}

/* [MOD] within the mode: the page setter has stored the new index. */
void lfo4_page_set(u32 mode)
{
    check(mode);
}
