/* The LFO4 page's note: the key stub and the stock two-line box (`note.c`).
 *
 * The stub sits on the page-key case of the main key handler (0x4005ed12),
 * no FUNC held, at its three pushes for the page select. It replays them,
 * calls the page select by its absolute address (the stock call is
 * PC-relative, so it cannot be replayed), then asks `lfo4_page_key` and
 * leaves through the handler's "handled" exit, as the stock case does.
 *
 * `lfo4_note_open` builds the YES/NO prompt as the pattern menu's RELOAD
 * does (0x401a5e2c), with the call sequence of reloadconfirm's `confirm`
 * (`scripts/build_reload_confirm.py`, passed on the instrument 2026-10-04).
 * Its answer does nothing: YES and NO both close it.
 */
#define PAGE_SELECT   0x4005E7E4      /* (this, key index, 0) */
#define KEY_HANDLED   0x4005EF52
#define NEW           0x40120264      /* operator new(size) */
#define STR_CTOR      0x401CE69E      /* std::string(this, const char *, const alloc &) */
#define STR_DTOR      0x401CCBEE
#define FUNC_DTOR     0x40188086      /* std::function destructor(this) */
#define SP_RELEASE    0x401880CC
#define SP_GET        0x4018816A
#define SP_MOVE       0x401A54AA
#define PROMPT        0x40112A2E      /* (this, line1, line2, &fn, 0) */
#define PROMPT_CTRL   0x401DD3D4
#define PROMPT_TAG    0x401D3B60
#define PROMPT_MGR    0x401A4358
#define VIEWS         0x4018C8DC
#define VIEW_STACK    0x4002C47A
#define VIEW_PUSH     0x4011D71E

/* Page key, no FUNC: %d4 the key index, %a2 the handler's object. */
    .globl  lfo4_key_stub
lfo4_key_stub:
    .globl  lfo4_key_displaced
lfo4_key_displaced:
    clr.l   -(%sp)
    move.l  %d4,-(%sp)
    move.l  %a2,-(%sp)
    jsr     PAGE_SELECT
    lea     12(%sp),%sp
    move.l  %d4,-(%sp)
    jsr     lfo4_page_key
    addq.l  #4,%sp
    jmp     KEY_HANDLED

/* The page setter 0x40063ade(mode, index), after its clamp: %a0 the mode,
 * %d0 the index. Replays the load of the vtable and the store of the index,
 * asks `lfo4_page_set`, and goes on to the tail call of entry +80. */
    .globl  lfo4_setpage_stub
lfo4_setpage_stub:
    .globl  lfo4_setpage_displaced
lfo4_setpage_displaced:
    movea.l (%a0),%a1
    move.l  %d0,144(%a0)
    lea     -16(%sp),%sp
    movem.l %d0-%d1/%a0-%a1,(%sp)
    move.l  %a0,-(%sp)
    jsr     lfo4_page_set
    addq.l  #4,%sp
    movem.l (%sp),%d0-%d1/%a0-%a1
    lea     16(%sp),%sp
    jmp     0x40063B06

/* lfo4_note_open(line1, line2). Frame: -16 the callback (then the view's
 * shared_ptr), -20 the control block, -24 the made one, -28 and -32 the two
 * lines, -33 and -34 their allocators. */
    .globl  lfo4_note_open
lfo4_note_open:
    link    %a6,#-64
    lea     -16(%sp),%sp
    movem.l %d2/%d5/%a2-%a3,(%sp)
    pea     0x8c
    jsr     NEW
    addq.l  #4,%sp
    move.l  %d0,%a2
    tst.l   %d0
    beq.w   9f
    moveq   #1,%d0
    move.l  %d0,4(%a2)
    move.l  %d0,8(%a2)
    move.l  #PROMPT_CTRL,(%a2)
    move.l  %a2,%d5
    addi.l  #16,%d5
    move.l  %d5,12(%a2)
    pea     -33(%a6)
    move.l  8(%a6),-(%sp)
    pea     -28(%a6)
    jsr     STR_CTOR
    pea     -34(%a6)
    move.l  12(%a6),-(%sp)
    pea     -32(%a6)
    jsr     STR_CTOR
    pea     1
    jsr     NEW
    lea     28(%sp),%sp
    move.l  %d0,-16(%a6)
    lea     PROMPT_MGR,%a0
    move.l  %a0,-8(%a6)
    lea     lfo4_note_answer,%a0
    move.l  %a0,-4(%a6)
    clr.l   -(%sp)
    pea     -16(%a6)
    pea     -32(%a6)
    pea     -28(%a6)
    move.l  %d5,-(%sp)
    jsr     PROMPT
    pea     -16(%a6)
    jsr     FUNC_DTOR
    pea     -32(%a6)
    jsr     STR_DTOR
    pea     -28(%a6)
    jsr     STR_DTOR
    lea     32(%sp),%sp
    move.l  %a2,-20(%a6)
    pea     PROMPT_TAG
    pea     -20(%a6)
    jsr     SP_GET
    move.l  %d0,-24(%a6)
    pea     -24(%a6)
    pea     -16(%a6)
    jsr     SP_MOVE
    lea     16(%sp),%sp
    jsr     VIEWS
    move.l  %d0,-(%sp)
    jsr     VIEW_STACK
    addq.l  #4,%sp
    clr.l   -(%sp)
    pea     -16(%a6)
    move.l  %d0,-(%sp)
    jsr     VIEW_PUSH
    pea     -12(%a6)
    jsr     SP_RELEASE
    pea     -20(%a6)
    jsr     SP_RELEASE
    lea     20(%sp),%sp
9:  movem.l (%sp),%d2/%d5/%a2-%a3
    lea     16(%sp),%sp
    unlk    %a6
    rts

/* The answer (functor, yes): nothing to do, the box closes itself. */
    .globl  lfo4_note_answer
lfo4_note_answer:
    rts
