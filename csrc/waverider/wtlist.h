/* The wavetable page's lists (wtlist.c), opened from its menu (wtmenu.c). */

#ifndef WAVERIDER_WTLIST_H
#define WAVERIDER_WTLIST_H

enum { WL_LOAD = 0, WL_MANAGE = 1, WL_POOL = 2 };   /* the menu's items, in order */

/* Build list KIND's rows from the store and the working project's pool list */
void wt_list_open(unsigned int kind);

/* A key while the list is shown: CODE, and whether it is the press or the release.
 * -> 0 when the list is left (back to the menu), 1 to stay, 2 not a key of the list's
 * (the stock handler takes it: UNISON, SETTINGS and the rest go where they go). */
unsigned int wt_list_key(unsigned int code, unsigned int pressed, unsigned int released);

void wt_list_draw(void *canvas);

#endif
