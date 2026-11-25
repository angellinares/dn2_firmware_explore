"""SLD on TRIG PAGE 2, and the paths that carry it with its trig, as an assembly template for
`scripts/build_pslide.py`.

- `ui_draw` (the TRIG page's call of the page renderer): on the page whose knob A is RTRG and whose
  knob E has no control, SLD in E's place, in LEN's box: the first held trig's value, or OFF. A
  value other than OFF is drawn inverted, as stock draws a locked parameter.
- `ui_knob` (the TRIG page's call of the shared knob handler): knob E on that page sets SLD on
  each held trig, through stock's flag setter; with no trig held it does nothing, as on stock.
- `ui_push` (the parameter pages' key handler, at a knob with no parameter): the release of knob
  E's push on that page sets the held trigs' SLD to OFF, as the release of a knob's push takes its
  lock off the held trigs.
- `copy_hook`, `paste_hook` (trig copy and paste): stock's clipboard keeps ten of a step's flags.
  The three SLD bits go in byte + 8 of the clipboard entry, whose low byte alone stock reads.
- `euc_read`, `euc_set` (FREEZE TRACK, the Euclidean conversion): stock carries `0x0008` and
  `0x0020` to the generated step; these carry `0x0040` with `0x0020`.
"""

UI = """
    .equ SLD_VALUES, 8

| ==== the TRIG page's call of the page renderer: (page, canvas)
ui_draw:
    move.l  8(%sp),-(%sp)
    move.l  8(%sp),-(%sp)
    jsr     {RENDERER:#x}
    addq.l  #8,%sp
    lea     -28(%sp),%sp
    movem.l %d2-%d4/%a2-%a3,(%sp)
    movea.l 32(%sp),%a2
    move.l  36(%sp),%d3
    bsr     sld_page
    beq     9f
    bsr     held_value
    move.l  %d0,%d4
| E's empty-cell dots go, and LEN's box shows SLD (stock's LEN formatter, 0x400cc2b4)
    clr.l   -(%sp)
    pea     {SLD_BOX_Y1}
    pea     {SLD_BOX_X1}
    pea     {SLD_BOX_Y}
    pea     {SLD_BOX_X}
    move.l  %d3,-(%sp)
    jsr     {FILL:#x}
    lea     24(%sp),%sp
    pea     {VALUE_FONT:#x}
    pea     24(%sp)                 | the 8-byte font copy, past the saved registers
    jsr     {FONT_COPY:#x}
    addq.l  #8,%sp
    lea     sld_names,%a0
    move.l  (%a0,%d4.l*4),-(%sp)
    pea     fmt_s
    pea     2
    pea     {SLD_BOX_Y}+6
    pea     {SLD_BOX_X}+9
    pea     40(%sp)
    move.l  %d3,-(%sp)
    jsr     {TEXT:#x}
    lea     28(%sp),%sp
    pea     20(%sp)
    jsr     {FONT_RELEASE:#x}
    addq.l  #4,%sp
    pea     1
    pea     {SLD_BOX_Y}+16
    pea     {SLD_BOX_X}+18
    pea     {SLD_BOX_Y}
    pea     {SLD_BOX_X}
    move.l  %d3,-(%sp)
    jsr     {OUTLINE:#x}
    lea     24(%sp),%sp
| a held trig's SLD other than OFF: inverted, as stock draws a locked value (LEN's box and 3
| pixels each side, 1 above and below; the canvas counts rows up from the screen's bottom)
    tst.l   %d4
d_locked:
    beq.s   1f
    pea     -1
    pea     {SLD_BOX_Y}+17
    pea     {SLD_BOX_X}+21
    pea     {SLD_BOX_Y}-1
    pea     {SLD_BOX_X}-3
    move.l  %d3,-(%sp)
    jsr     {FILL:#x}
    lea     24(%sp),%sp
| its label, as the page writes RTRG's (0x40064650)
1:
    pea     sld_label
    pea     fmt_s
    pea     label_width
    clr.l   -(%sp)
    pea     1
    pea     {SLD_LABEL_Y}
    pea     {SLD_BOX_X}+9
    pea     {LABEL_FONT:#x}
    move.l  %d3,-(%sp)
    jsr     {LABEL:#x}
    lea     36(%sp),%sp
9:  movem.l (%sp),%d2-%d4/%a2-%a3
    lea     28(%sp),%sp
    rts

| a2 = a TRIG page: Z clear when it is the page with RTRG at knob A and nothing at knob E (an
| audio track's TRIG PAGE 2). Uses d0, d1, a0, a1
sld_page:
    clr.l   -(%sp)
    move.l  %a2,-(%sp)
    jsr     {PARAM_OF:#x}
    addq.l  #8,%sp
    cmpi.l  #{RTRG_ID},%d0
    bne.s   1f
    pea     4
    move.l  %a2,-(%sp)
    jsr     {PARAM_OF:#x}
    addq.l  #8,%sp
    tst.l   %d0
    seq     %d0
    tst.b   %d0
    rts
1:  moveq   #0,%d0
    rts

| a2 = the page: d0 = the SLD of its first held trig, 0 (OFF) when none is held. Uses d0, d1,
| a0, a1
held_value:
    bsr     first_held
    bmi.s   1f
    bsr     flag_word
    bra     sld_of
1:  moveq   #0,%d0
    rts

| a2 = the page: d0 = the first held step, -1 (N set) when none. Uses d1, a0
first_held:
    movea.l {PAGE_UI}(%a2),%a0
    tst.b   {HELD_ANY}(%a0)
    beq.s   3f
    lea     {HELD_BITS}(%a0),%a0
    moveq   #0,%d1
1:  move.l  (%a0)+,%d0
    bne.s   2f
    addi.l  #32,%d1
    cmpi.l  #128,%d1
    bne.s   1b
3:  moveq   #-1,%d0
    rts
2:  move.l  %d0,-(%sp)
    neg.l   %d0
    and.l   (%sp)+,%d0
    ff1     %d0
    eori.l  #31,%d0
    add.l   %d1,%d0
    rts

| a2 = the page, d0 = a step: a0 = its flag word in the selected track. Keeps d0. Uses d1, a1
flag_word:
    move.l  %d0,-(%sp)
    move.l  {PAGE_APP}(%a2),-(%sp)
    jsr     {SELECTED_TRACK:#x}
    addq.l  #4,%sp
    movea.l %d0,%a0
    movea.l {TRACK_DATA}(%a0),%a0
    move.l  (%sp)+,%d0
    adda.l  %d0,%a0
    adda.l  %d0,%a0
    rts

| a0 = a flag word: d0 = its SLD, 0 to 7. Uses d1
sld_of:
    mvz.w   (%a0),%d0
    move.l  %d0,%d1
    lsr.l   #3,%d1
    andi.l  #1,%d1
    lsr.l   #4,%d0
    andi.l  #6,%d0
    or.l    %d1,%d0
    rts

| ==== the TRIG page's call of the shared knob handler: (page, event). Knob E on the SLD page
ui_knob:
    movea.l 8(%sp),%a0
    moveq   #{KNOB_E},%d0
    cmp.l   {EVENT_CODE}(%a0),%d0
    beq.s   1f
2:  jmp     {KNOB_HANDLER:#x}
1:  lea     -36(%sp),%sp
    movem.l %d2-%d6/%a2-%a5,(%sp)
    movea.l 40(%sp),%a2
    movea.l 44(%sp),%a3
    bsr     sld_page
    bne.s   3f
    movem.l (%sp),%d2-%d6/%a2-%a5
    lea     36(%sp),%sp
    bra.s   2b
3:  movea.l {PAGE_UI}(%a2),%a4
    tst.b   {HELD_ANY}(%a4)
k_held:
    beq.s   10f
| its counts, a unit for each COUNTS_PER_UNIT as LEN moves: d4 = the units
    move.l  {EVENT_DELTA}(%a3),%d0
    add.l   g_knob,%d0
    move.l  %d0,%d4
    moveq   #{COUNTS_PER_UNIT},%d1
    divs.l  %d1,%d4
    moveq   #{COUNTS_PER_UNIT},%d1
    muls.l  %d4,%d1
    sub.l   %d1,%d0
    move.l  %d0,g_knob
    tst.l   %d4
    beq.s   8f
| each held trig: its SLD moves by the units, from OFF to NEXT
    lea     {HELD_BITS}(%a4),%a4
    moveq   #0,%d5                  | the step
4:  move.l  %d5,%d0
    lsr.l   #5,%d0
    move.l  (%a4,%d0.l*4),%d1
    btst    %d5,%d1
    beq.s   7f
    move.l  %d5,%d0
    bsr     flag_word
    bsr     sld_of
    add.l   %d4,%d0
    bpl.s   5f
    moveq   #0,%d0
5:  moveq   #SLD_VALUES-1,%d1
    cmp.l   %d1,%d0
    ble.s   6f
    move.l  %d1,%d0
6:  move.l  %d0,%d6
    bsr     set_sld
7:  addq.l  #1,%d5
    cmpi.l  #128,%d5
    bne.s   4b
    move.l  %a2,-(%sp)
    jsr     {REDRAW:#x}
    addq.l  #4,%sp
8:  movem.l (%sp),%d2-%d6/%a2-%a5
    lea     36(%sp),%sp
    moveq   #1,%d0
    rts
10: clr.l   g_knob                  | no trig held: knob E does nothing and keeps no counts
    bra.s   8b

| ==== the parameter pages' key handler, at a knob's push or release when the knob has no
| parameter: d3 = its parameter, d4 = the knob (0 to 7, A to H), d2 = the event, a2 = the page.
| On the SLD page, the release of knob E's push sets each held trig's SLD to OFF. Then stock's
| return for a knob with no parameter, which restores every register it saved. A knob with a
| parameter goes on to stock's handling
ui_push:
    tst.l   %d3
    beq.s   1f
    jmp     {PUSH_BACK:#x}
1:  moveq   #{KNOB_E_PUSH},%d0
    cmp.l   %d4,%d0
p_knob:
    bne.s   9f
    move.l  %d2,-(%sp)
    jsr     {IS_RELEASE:#x}
    addq.l  #4,%sp
    tst.l   %d0
p_release:
    beq.s   9f
    bsr     sld_page
p_page:
    beq.s   9f
    movea.l {PAGE_UI}(%a2),%a4      | each held step (none are while no trig is held)
    lea     {HELD_BITS}(%a4),%a4
    moveq   #0,%d5                  | the step
2:  move.l  %d5,%d0
    lsr.l   #5,%d0
    move.l  (%a4,%d0.l*4),%d1
    btst    %d5,%d1
    beq.s   3f
    moveq   #0,%d6
    bsr     set_sld
3:  addq.l  #1,%d5
    cmpi.l  #128,%d5
    bne.s   2b
    move.l  %a2,-(%sp)
    jsr     {REDRAW:#x}
    addq.l  #4,%sp
9:  jmp     {PUSH_NONE:#x}

| a2 = the page, d5 = a step, d6 = its new SLD: each of its three bits through stock's flag
| setter (trackObject, step, mask, on). Uses d0-d3, a0, a1, a5
set_sld:
    move.l  {PAGE_APP}(%a2),-(%sp)
    jsr     {SELECTED_TRACK:#x}
    addq.l  #4,%sp
    movea.l %d0,%a5
    moveq   #0,%d3
1:  move.l  %d6,%d0
    lsr.l   %d3,%d0
    andi.l  #1,%d0
    move.l  %d0,-(%sp)
    lea     sld_bits,%a0
    move.l  (%a0,%d3.l*4),-(%sp)
    move.l  %d5,-(%sp)
    move.l  %a5,-(%sp)
    jsr     {FLAG_SETTER:#x}
    lea     16(%sp),%sp
    addq.l  #1,%d3
    moveq   #3,%d0
    cmp.l   %d0,%d3
    bne.s   1b
    rts

| ==== trig copy, for each copied step: a3 = its track, a2 -> its step, -72(%fp) = the clipboard
| entry. Then the two instructions the jump displaced
copy_hook:
    mvs.b   %d0,%d0
    move.l  %d0,-64(%fp)
    lea     -16(%sp),%sp
    movem.l %d0-%d1/%a0-%a1,(%sp)
    movea.l (%a3),%a0
    move.l  %a3,-(%sp)
    movea.l {DATA_SLOT}(%a0),%a0
    jsr     (%a0)
    addq.l  #4,%sp
    movea.l %d0,%a0
    move.l  (%a2),%d0
    add.l   %d0,%d0
    mvz.w   (%a0,%d0.l),%d0
    andi.l  #{SLD_BITS},%d0
    move.b  %d0,-64(%fp)            | entry + 8: stock reads the long's low byte only
    movem.l (%sp),%d0-%d1/%a0-%a1
    lea     16(%sp),%sp
    jmp     {COPY_BACK:#x}

| ==== trig paste, after each applied entry: a2 = the destination track, a3 = the entry, (a3) =
| its step. The destination's SLD is the entry's, then the two instructions the jump displaced
paste_hook:
    movea.l (%a2),%a0
    move.l  %a2,-(%sp)
    movea.l {DATA_SLOT}(%a0),%a0
    jsr     (%a0)
    addq.l  #4,%sp
    movea.l %d0,%a0
    move.l  (%a3),%d0
    add.l   %d0,%d0
    adda.l  %d0,%a0
    mvz.w   (%a0),%d0
    andi.l  #{SLD_CLEAR},%d0
    mvz.b   8(%a3),%d1
    andi.l  #{SLD_BITS},%d1
    or.l    %d1,%d0
    move.w  %d0,(%a0)
    move.l  %d3,-(%sp)
    jsr     {PASTE_CALL:#x}
    jmp     {PASTE_BACK:#x}

| ==== FREEZE TRACK, for each generated step: (a2, d3) on the stack for the 0x0020 getter. d0 =
| bit 0 its 0x0020, bit 1 its 0x0040. Then the instruction the jump displaced
euc_read:
    jsr     {GET_0020:#x}
    move.l  %d0,-(%sp)
    pea     0x40
    move.l  12(%sp),-(%sp)
    move.l  12(%sp),-(%sp)
    jsr     {FLAG_GET:#x}
    lea     12(%sp),%sp
    andi.l  #1,%d0
    add.l   %d0,%d0
    move.l  (%sp)+,%d1
    andi.l  #1,%d1
    or.l    %d1,%d0
    move.l  %d2,-(%sp)
    jmp     {EUC_READ_BACK:#x}

| FREEZE TRACK, setting the generated step d2 of track a2: d3 = what euc_read gave. 0x0020 through
| stock's setter, with its arguments left for the next instruction to remove, then 0x0040
euc_set:
    move.l  %d3,%d0
    andi.l  #1,%d0
    move.l  %d0,-(%sp)
    move.l  %d2,-(%sp)
    move.l  %a2,-(%sp)
    jsr     {SET_0020:#x}
    move.l  %d3,%d0
    lsr.l   #1,%d0
    andi.l  #1,%d0
    move.l  %d0,-(%sp)
    pea     0x40
    move.l  %d2,-(%sp)
    move.l  %a2,-(%sp)
    jsr     {FLAG_SETTER:#x}
    lea     16(%sp),%sp
    jmp     {EUC_SET_BACK:#x}

    .balign 4
sld_bits:
    .long 0x0008, 0x0020, 0x0040
sld_names:
    .long n_off, n_half, n_1, n_2, n_4, n_8, n_16, n_next
n_off:  .asciz "OFF"
n_half: .asciz "1/2"
n_1:    .asciz "1"
n_2:    .asciz "2"
n_4:    .asciz "4"
n_8:    .asciz "8"
n_16:   .asciz "16"
n_next: .asciz "NEXT"
sld_label:
    .asciz "SLD"
label_width:
    .asciz "XXXX"
fmt_s:
    .asciz "%s"
"""
