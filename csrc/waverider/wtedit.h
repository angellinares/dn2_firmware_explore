/* Edits of the working project's pool list (wtedit.c). */

#ifndef WAVERIDER_WTEDIT_H
#define WAVERIDER_WTEDIT_H

enum { WT_DONE = 0, WT_ALREADY, WT_FULL, WT_FAILED };

/* STORE_SLOT into the first free pool slot -> WT_* */
unsigned int wt_pool_add(unsigned int store_slot);

/* Pool index J (shown slot J + 1) emptied -> WT_* */
unsigned int wt_pool_clear(unsigned int j);

#endif
