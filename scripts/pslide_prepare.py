"""Step evaluation for the parameter-slide engine: each trig with SLD gets a pending slide, as an
assembly template for `scripts/build_pslide.py` (rendered with `scripts/pslide_engine.py`'s).

- `h_prep` (the step evaluation's store of the trig's lock list, a step ahead of the note):
  `prepare` takes a buffer from the pool and fills it from the trig's list. On the stopped
  sequencer's preview list, a trig without SLD ends the slide an earlier evaluation prepared. A length's entries
  are the trig's locks on slots that slide, and its other locks move to the front of the list,
  which is all the applier gets for a note of the slide.
- `prep_next` (SLD NEXT): the next trig within the track's length or looped page, read without
  its condition, and an entry for each slot that slides and that this trig or the next locks.
"""

STARTS = """
| ==== step evaluation, once it has stored the trig's list (a6) and sound: a3 = the event, a2 = the
| track's data (the pattern + 1701 x the track, 0x400d8a82), d3 = the step. A trig with SLD gets a
| pending slide. A trig without SLD on the stopped sequencer's preview list (count 0), which
| stock evaluates again into the same list after an edit, ends the pending slide of an earlier
| evaluation. A counted list goes to no other trig while a slide holds it. Stock's next
| instruction is move.l %a3,%d0
h_prep:
    move.l  %a6,84(%a3)
    move.l  56(%a3),%d0
    moveq   #{SLD_BITS},%d1
    and.l   %d0,%d1
    bne.s   1f
    move.l  %a6,%d0
    beq.s   3f
    tst.l   (%a6)
p_preview:
    beq.s   4f
3:  move.l  %a3,%d0
prep_exit:
    jmp     {PREP_BACK:#x}
4:  lea     -56(%sp),%sp
    movem.l %d1-%d7/%a0-%a6,(%sp)
    bsr     preview_off
    bra.s   2f
1:  lea     -56(%sp),%sp
    movem.l %d1-%d7/%a0-%a6,(%sp)
    bsr     prepare
2:  movem.l (%sp),%d1-%d7/%a0-%a6
    lea     56(%sp),%sp
    bra.s   3b

| a3 = the event, a6 = its list (the preview's, without SLD): the track's pending slide of an
| earlier evaluation of the list goes. Uses every register but a2, a3
preview_off:
    move.l  16(%a3),%d6
    moveq   #16,%d0
    cmp.l   %d0,%d6
    bcc.s   9f
    lsl.l   #T_SHIFT,%d6
    lea     tracks,%a5
    adda.l  %d6,%a5
    move.l  %a6,%d7
    bra     drop_earlier
9:  rts

| a3 = the event, a2 = the track's data, d3 = the step, a6 = the list. Uses every register but a3.
| a2 is the pattern from here
prepare:
    move.l  16(%a3),%d6
    moveq   #16,%d0
    cmp.l   %d0,%d6
    bcc     p_out                   | not a sound track's
    move.l  #{TRACK_STRIDE},%d0
    muls.l  %d6,%d0
p_track:
    suba.l  %d0,%a2
    move.l  %d6,%d0
    lsl.l   #T_SHIFT,%d0
    lea     tracks,%a5
    adda.l  %d0,%a5
    move.l  %a6,%d7
p_nolist:
    beq     p_out                   | no list: stock had none to give
    bsr     drop_earlier
| a free place among the track's slides
    bsr     free_place
    tst.l   %d4
    bmi     p_out
    bsr     pool_alloc
    tst.l   %a4
    beq     p_out
    move.l  %d4,-(%sp)
    bsr     prep_fill
    move.l  (%sp)+,%d4
    tst.l   %d0
    bmi     p_back                  | nothing can slide
    lea     B_ELIG(%a4),%a0         | from here: the slots that slide and the trig does not lock,
    lea     B_LMASK(%a4),%a1        | which a return from the last note's locks can take
    moveq   #4,%d1
3:  move.l  (%a1)+,%d0
    not.l   %d0
    and.l   %d0,(%a0)+
    subq.l  #1,%d1
    bne.s   3b
| it waits for its notes, with a hold on the trig's list (released when stock and the slide are
| done with it), so the list's address names this trig while the slide is in a place. The
| stopped sequencer's preview list has no count: stock frees it never, and neither may a hold
    move.w  %sr,%d5
    move.w  #0x2700,%sr
    movea.l B_LIST(%a4),%a0
    tst.l   (%a0)
p_uncounted:
    beq.s   1f
    addq.l  #1,(%a0)
    moveq   #1,%d0
    move.b  %d0,B_HELD(%a4)
1:  move.l  %d4,%d0
    addq.l  #1,%d0
    move.b  %d0,B_SLOT(%a4)
    lsl.l   #3,%d0
    lea     T_PLACE-8(%a5,%d0.l),%a0
    move.l  %d7,(%a0)+              | the place: the trig's list, then the slide
    move.l  %a4,(%a0)
    addq.l  #1,T_NB(%a5)
    moveq   #PENDING,%d0
    move.b  %d0,B_STATE(%a4)
    move.l  g_head,%d0
    move.l  %d0,B_NEXT(%a4)
    move.l  %a4,g_head
    move.w  %d5,%sr
p_out:
    rts
p_back:
    move.w  %sr,%d5
    move.w  #0x2700,%sr
    move.l  g_free,%d0
    move.l  %d0,B_NEXT(%a4)
    move.l  %a4,g_free
    move.w  %d5,%sr
    rts

| a5 = a track, d7 = a list: the track's slide with that list, from an earlier evaluation of it,
| goes. Uses d0, d1, d5, a0, a1
drop_earlier:
    tst.l   T_NB(%a5)
    beq.s   9f
    move.w  %sr,%d5
    move.w  #0x2700,%sr
    movea.l %a5,%a0
    move.l  %d7,%d1
    bsr     find
    tst.l   %a1
    beq.s   1f
    bsr     drop_place
1:  move.w  %d5,%sr
9:  rts

| a5 = a track, a1 = its slide in place d0: it goes (state DROPPED, freed by the next frame).
| Interrupts masked by the caller. Uses d0, d1, a0
drop_place:
    moveq   #DROPPED,%d1
    move.b  %d1,B_STATE(%a1)
    clr.b   B_SLOT(%a1)
    lsl.l   #3,%d0
    lea     T_PLACE(%a5,%d0.l),%a0
    clr.l   (%a0)+
    clr.l   (%a0)
    subq.l  #1,T_NB(%a5)
    rts

| a5 = a track: d4 = a free place among its slides, or -1 when all are in use (the trig's locks
| then change at once, as on stock). A frame can only free a place, so a place seen free stays
| free. Uses d4, a0
free_place:
    lea     T_PLACE+4(%a5),%a0
    moveq   #0,%d4
1:  tst.l   (%a0)
    beq.s   2f
    addq.l  #8,%a0
    addq.l  #1,%d4
    cmpi.l  #PLACES,%d4
    bne.s   1b
    moveq   #-1,%d4
2:  rts

| a4 = a new buffer for the event a3 (list d7, track d6, track state a5, pattern a2, step d3):
| its entries and length. d0 = its entry count, or -1 when nothing can slide (a
| length slide without entries waits for its note, which can add the last note's locks). Uses
| d0-d2, d4, d5, a0, a1, a6
prep_fill:
    move.l  %d7,B_LIST(%a4)
    move.l  %a5,B_TRACK(%a4)
    move.l  %d6,B_TNUM(%a4)
    move.l  {PATTERN:#x},%d0
    move.l  %d0,B_PTN(%a4)
    clr.l   B_MASK(%a4)
    clr.b   B_INIT(%a4)
    clr.b   B_HELD(%a4)
    clr.b   B_USED(%a4)
    clr.w   B_ARRIVED(%a4)
    clr.b   B_ISNEXT(%a4)
    clr.b   B_KIND(%a4)             | KIND_NOTE (h_lock makes it a lock trig's template)
    movea.l 60(%a3),%a0
    move.l  %a0,B_SOUND(%a4)
    bsr     elig_mask
    move.l  56(%a3),%d0
| the SLD value: 1..6 a length of 1/2..16 steps, 7 NEXT
    move.l  %d0,%d1
    lsr.l   #3,%d1
    moveq   #1,%d2
    and.l   %d2,%d1
    lsr.l   #4,%d0
    moveq   #6,%d2
    and.l   %d2,%d0
    or.l    %d1,%d0
    cmpi.l  #{SLD_NEXT},%d0
    beq     prep_next
| a length: 2^(v-1) half-steps of the track's speed. Its entries are the trig's locks that slide;
| the applier writes the rest as stock does
    subq.l  #1,%d0
    moveq   #1,%d1
    lsl.l   %d0,%d1
    bsr     set_length
    bsr     list_entries
    move.l  %d5,%d0
    rts

| a4 = a buffer, its sound in B_SOUND: B_ELIG, the slots that slide for the sound's
| machine and filter type. Uses d0, d1, a0, a1
elig_mask:
    movea.l B_SOUND(%a4),%a0
    mvz.b   {SOUND_MACHINE}(%a0),%d0
    mvz.b   {SOUND_FILTER}(%a0),%d1
    lea     elig_shared,%a1
    move.l  (%a1)+,B_ELIG(%a4)
    move.l  (%a1)+,B_ELIG+4(%a4)
    move.l  (%a1)+,B_ELIG+8(%a4)
    move.l  (%a1)+,B_ELIG+12(%a4)
    cmpi.l  #{MACHINES},%d0
    bcc.s   1f
    lsl.l   #4,%d0
    lea     elig_machine,%a1
    adda.l  %d0,%a1
    bsr.s   elig_or
1:  lsl.l   #4,%d1                  | (a filter type, 0 to FILTERS - 1)
    lea     elig_filter,%a1
    adda.l  %d1,%a1
    bsr.s   elig_or
    rts
elig_or:
    move.l  (%a1)+,%d0
    or.l    %d0,B_ELIG(%a4)
    move.l  (%a1)+,%d0
    or.l    %d0,B_ELIG+4(%a4)
    move.l  (%a1)+,%d0
    or.l    %d0,B_ELIG+8(%a4)
    move.l  (%a1)+,%d0
    or.l    %d0,B_ELIG+12(%a4)
    rts

| a4 = a buffer, d1 = half-steps, a2 = the pattern, d6 = the track: B_LEN, B_LENS and B_SH, in clock
| units of 16 (a half-step of 1x, 3 ticks of 900,000, is 168,750 of them). Uses d0-d2, a0
set_length:
    movea.l %a2,%a0
    adda.l  #{SCALE_MODE},%a0
    tst.b   (%a0)
    beq.s   1f
    move.l  #{TRACK_STRIDE},%d0
    muls.l  %d6,%d0
    movea.l %a2,%a0
    adda.l  %d0,%a0
    mvz.b   {TRACK_SCALE}(%a0),%d0
    bra.s   2f
1:  movea.l %a2,%a0
    adda.l  #{MASTER_SCALE},%a0
    mvz.b   (%a0),%d0
2:  lea     {TICKS_PER_STEP:#x},%a0
    move.l  (%a0,%d0.l*4),%d0
    muls.l  %d1,%d0
    move.l  #{HALF_TICK_UNITS},%d1
    muls.l  %d1,%d0
    move.l  %d0,B_LEN(%a4)
    move.l  %d0,%d1
    ff1     %d1
    moveq   #16,%d2                 | (the shortest, a half step at 2x, has 17 bits)
    sub.l   %d1,%d2
    move.b  %d2,B_SH(%a4)
    lsr.l   %d2,%d0
    move.l  %d0,B_LENS(%a4)
    rts

| a4 = a buffer, d7 = the trig's list: each lock on a slot that slides becomes an entry (its target
| the lock, its offset 34 + 2 slot, its lock bit set). The other locks move to the front of the
| list, B_NRES of them: a note of the slide gives the applier those alone (h_apply). The list
| keeps every lock and its count. d5 = the entries. Uses d0-d2, a0, a1, a6
list_entries:
    clr.l   B_LMASK(%a4)
    clr.l   B_LMASK+4(%a4)
    clr.l   B_LMASK+8(%a4)
    clr.l   B_LMASK+12(%a4)
    lea     B_ENT(%a4),%a1
    movea.l %d7,%a0
    move.l  8(%a0),%d2
    lea     20(%a0),%a0
    movea.l %a0,%a6                 | the next place for a lock that does not slide
    moveq   #0,%d5
    tst.l   %d2
    beq.s   9f
1:  mvz.w   (%a0),%d0
    bsr     slot_slides
l_slides:
    beq.s   2f
    mvz.w   2(%a0),%d1
    bsr     add_entry
    bra.s   3f
2:  move.l  (%a6),%d0               | it changes places with the first lock that slides
    move.l  (%a0),(%a6)
    move.l  %d0,(%a0)
    move.l  4(%a6),%d0
    move.l  4(%a0),4(%a6)
    move.l  %d0,4(%a0)
    addq.l  #8,%a6
3:  addq.l  #8,%a0
    subq.l  #1,%d2
    bne.s   1b
9:  move.l  %a6,%d0
    movea.l %d7,%a0
    lea     20(%a0),%a0
    sub.l   %a0,%d0
    lsr.l   #3,%d0
    move.w  %d0,B_NRES(%a4)
    move.w  %d5,B_N(%a4)
    rts

| d0 = a slot, 0 to 100 (the list builder's bound, 0x400d8640): Z clear when it slides for buffer
| a4 (in B_ELIG). Keeps d0. Uses d1
slot_slides:
    move.l  %d0,%d1
    lsr.l   #5,%d1
    lsl.l   #2,%d1
    move.l  B_ELIG(%a4,%d1.l),%d1
    btst    %d0,%d1
    rts

| d0 = a slot, d1 = its target, a1 = the next entry of buffer a4, d5 = entries so far: the entry
| (its offset 34 + 2 slot, its target) and the slot's lock bit. a1, d5 = past it. Keeps d0, d1
add_entry:
    move.l  %d2,-(%sp)
    move.l  %a0,-(%sp)
    move.w  %d1,E_TO(%a1)
    move.l  %d0,%d2
    add.l   %d2,%d2
    addi.l  #{SRC_HEADER_BYTES},%d2
    move.w  %d2,(%a1)
    addq.l  #8,%a1
    addq.l  #1,%d5
    move.l  %d0,%d2
    lsr.l   #5,%d2
    lsl.l   #2,%d2
    lea     B_LMASK(%a4,%d2.l),%a0
    move.l  (%a0),%d2
    bset    %d0,%d2
    move.l  %d2,(%a0)
    movea.l (%sp)+,%a0
    move.l  (%sp)+,%d2
    rts
"""

NEXT = """
| NEXT: the next trig of the track, within its length or its looped page, read without its
| condition. The slide goes from this trig's values to that trig's over the steps between, and
| the applier still writes this trig's whole list
prep_next:
    moveq   #1,%d0
    move.b  %d0,B_ISNEXT(%a4)
    bsr     next_step
    move.l  %d1,-(%sp)
    move.l  %d2,%d1
    add.l   %d1,%d1
    bsr     set_length
    move.l  (%sp)+,%d1
    bsr     next_entries
    move.l  %d5,%d0
    bne.s   1f
    moveq   #-1,%d0
1:  rts

| d3 = this step, d6 = the track, a2 = the pattern: d1 = the next step with a trig, d2 = the steps
| until it plays (the whole cycle when no other step has one). Uses d0, d4, d5, a0, a1
next_step:
    move.l  #{TRACK_STRIDE},%d0
    muls.l  %d6,%d0
    movea.l %a2,%a0
    adda.l  %d0,%a0
    mvz.b   {LOOP_COUNT}(%a0),%d4
    tst.l   %d4
    bne.s   ns_loop
    movea.l %a2,%a1
    adda.l  #{SCALE_MODE},%a1
    tst.b   (%a1)
    beq.s   1f
    mvs.w   {TRACK_LENGTH}(%a0),%d4
    bra.s   2f
1:  movea.l %a2,%a1
    adda.l  #{PATTERN_LENGTH},%a1
    mvs.w   (%a1),%d4
2:  move.l  %d3,%d0
    moveq   #0,%d2
3:  addq.l  #1,%d2
    addq.l  #1,%d0
    cmp.l   %d4,%d0
    blt.s   4f
    moveq   #0,%d0
4:  cmp.l   %d4,%d2
    bcc.s   5f
    mvz.w   (%a0,%d0.l*2),%d5
    btst    #0,%d5
    beq.s   3b
5:  move.l  %d0,%d1
    rts
| with Page Loop on, the looped steps play in the order of the words from + 1445: this step's
| place among them, then the next place whose step has a trig
ns_loop:
    lea     {LOOP_STEPS}(%a0),%a1
    moveq   #-1,%d0
6:  addq.l  #1,%d0
    cmp.l   %d4,%d0
    bcc.s   7f
    mvs.w   (%a1,%d0.l*2),%d1
    cmp.l   %d3,%d1
    bne.s   6b
7:  moveq   #0,%d2
8:  addq.l  #1,%d2
    addq.l  #1,%d0
    cmp.l   %d4,%d0
    blt.s   9f
    moveq   #0,%d0
9:  mvs.w   (%a1,%d0.l*2),%d1
    cmp.l   %d4,%d2
    bcc.s   10f
    mvz.w   (%a0,%d1.l*2),%d5
    btst    #0,%d5
    beq.s   8b
10: rts

| d1 = the next trig's step, d7 = this trig's list: the entries, in slot order, for each slot that
| slides and that this trig or the next one locks. The target is the next trig's lock, or the
| sound's value. d5 = the entries. Uses d0-d2, d4, a0, a1, a6
next_entries:
    move.l  %d1,%d4
    lea     -204(%sp),%sp
    movea.l %sp,%a0
    moveq   #-1,%d0
    moveq   #51,%d2
1:  move.l  %d0,(%a0)+
    subq.l  #1,%d2
    bne.s   1b
| this trig's locks, by slot (0xffff: none)
    movea.l %d7,%a0
    move.l  8(%a0),%d2
    lea     20(%a0),%a0
    tst.l   %d2
    beq.s   3f
2:  mvz.w   (%a0),%d0
    move.w  2(%a0),%d1
    move.w  %d1,(%sp,%d0.l*2)
    addq.l  #8,%a0
    subq.l  #1,%d2
    bne.s   2b
| the next trig's lock records: a6 = the track's record numbers by slot; d2 = 0 when its step has
| no lock
3:  move.l  %d6,%d1
    moveq   #{SLOTS},%d2
    muls.l  %d2,%d1
    addi.l  #{LOCK_IDS},%d1
    movea.l %a2,%a6
    adda.l  %d1,%a6
    move.l  %d6,%d0
    lsl.l   #7,%d0
    add.l   %d4,%d0
    addi.l  #{LOCK_FLAGS},%d0
    movea.l %a2,%a0
    mvz.b   (%a0,%d0.l),%d2
    clr.l   B_LMASK(%a4)
    clr.l   B_LMASK+4(%a4)
    clr.l   B_LMASK+8(%a4)
    clr.l   B_LMASK+12(%a4)
    lea     B_ENT(%a4),%a1
    moveq   #0,%d5
    moveq   #0,%d0
4:  bsr     slot_slides
    beq     8f
    moveq   #-1,%d1
    tst.l   %d2
    beq.s   5f
    mvs.b   (%a6,%d0.l),%d1
    tst.l   %d1
    bmi.s   41f
    move.l  %d0,-(%sp)
    move.l  #{LOCK_RECORD_BYTES},%d0
    muls.l  %d0,%d1
    move.l  %d4,%d0
    add.l   %d0,%d0
    add.l   %d0,%d1
    addi.l  #{LOCK_VALUES},%d1
    movea.l %a2,%a0
    mvz.w   (%a0,%d1.l),%d1
    move.l  (%sp)+,%d0
    bra.s   5f
41: moveq   #-1,%d1
5:  cmpi.w  #-1,%d1
    bne.s   6f
    move.w  (%sp,%d0.l*2),%d1       | this trig's lock
    cmpi.w  #-1,%d1
    beq.s   8f
    movea.l B_SOUND(%a4),%a0        | locked here only: it goes back to the sound's value
    move.l  %d0,%d1
    add.l   %d1,%d1
    mvz.w   {SOUND_VALUES}(%a0,%d1.l),%d1
6:  bsr     add_entry
8:  addq.l  #1,%d0
    cmpi.l  #{SLOTS},%d0
    bne     4b
    lea     204(%sp),%sp
    move.w  %d5,B_N(%a4)
    rts
"""
