/* LFO4's own stock addresses, Digitone II OS 1.11: the ones dn2_111.h does not name.
 *
 * Plain numbers, so the C and the assembly both include it. Include stock.h, not this file:
 * it picks stock_112.h when the build defines DN2_OS_112. stock_112.h is generated:
 *     python scripts/gen_dn2_header.py --os 1.12 --inc csrc/lfo4/stock_111.h
 * SRAM addresses (0x8000....) are the same on both versions and stay in the sources. */
#ifndef LFO4_STOCK_111_H
#define LFO4_STOCK_111_H

/* bridge.c */
#define STOCK_LFO_RATE      0x402A0DEC    /* the frame's rate, the evaluators' 2nd argument */
#define STOCK_LIVE_STATE    0x4464ABF0    /* the heap arena's first block: build_lfo4_tick.py's LIVE */

/* page.c */
#define STOCK_PAGE_TABLE    0x42432C00

/* note.S */
#define STOCK_KEY_RESUME    0x40063B06    /* the page-key case's exit */
#define STOCK_PAGE_SELECT   0x4005E7E4    /* (this, key index, 0) */
#define STOCK_KEY_HANDLED   0x4005EF52
#define STOCK_NEW           0x40120264    /* operator new(size) */
#define STOCK_STR_CTOR      0x401CE69E    /* std::string(this, const char *, const alloc &) */
#define STOCK_STR_DTOR      0x401CCBEE
#define STOCK_FUNC_DTOR     0x40188086    /* std::function destructor(this) */
#define STOCK_SP_RELEASE    0x401880CC
#define STOCK_SP_GET        0x4018816A
#define STOCK_SP_MOVE       0x401A54AA
#define STOCK_PROMPT        0x40112A2E    /* (this, line1, line2, &fn, 0) */
#define STOCK_PROMPT_CTRL   0x401DD3D4
#define STOCK_PROMPT_TAG    0x401D3B60
#define STOCK_PROMPT_MGR    0x401A4358
#define STOCK_VIEWS         0x4018C8DC
#define STOCK_VIEW_STACK    0x4002C47A
#define STOCK_VIEW_PUSH     0x4011D71E

#endif
