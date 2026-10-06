/* Edits of the working project's pool list (wtedit.c). */

#ifndef WAVERIDER_WTEDIT_H
#define WAVERIDER_WTEDIT_H

enum { WT_DONE = 0, WT_ALREADY, WT_FULL, WT_FAILED, WT_NOT_WAVERIDER, WT_EMPTY };

/* STORE_SLOT into the first free pool slot -> WT_* */
unsigned int wt_pool_add(unsigned int store_slot);

/* Pool index J (shown slot J + 1) emptied -> WT_* */
unsigned int wt_pool_clear(unsigned int j);

/* Pool index J onto the active track's TBL of oscillator OSC (0 or 1), as a turn of TBL
 * to it would leave the sound -> WT_* */
unsigned int wt_tbl_load(unsigned int j, unsigned int osc);

/* Store slot S deleted from the +Drive (its index entry freed; the table's sectors stay
 * until overwritten). Every pool list naming it keeps the slot, which plays Prim. and
 * reads MISSING, until CLEAR SLOT frees it. -> WT_* */
unsigned int wt_store_delete(unsigned int s);

#endif
