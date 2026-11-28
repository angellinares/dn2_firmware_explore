"""The note and lock-trig hooks of the parameter-slide engine, as an assembly template for
`scripts/build_pslide.py` (rendered with `scripts/pslide_engine.py`'s, whose names it uses).

- `h_pre`, `h_apply`, `h_post` (each note, in the audio-frame interrupt): the start values from the
  track's last voice, before stock's restore can overwrite a reused voice, which takes them there
  when it keeps its sound; the applier's call, with the trig's list counting only the locks that do
  not slide, or no call when every lock slides; the start, or the join of a later note of the same
  trig. When the voice keeps its sound, the voice has its values and lock bits in the note's frame,
  and the rest of the start waits for the next frame (`queue_note`, `drain`).
- `h_lock` (each voice of a lock trig): the slots the trig locks leave the voice's older slides, and
  the voice gets a slide of its own, from its own values.
"""

NOTES = """
| ==== each note, before stock restores the voice's locked values or loads another sound: d2 = the
| voice, a0 = the event. A note of a pending slide reads its start values here, from the track's
| last voice, which can be this one. Then the two instructions the jump displaced
h_pre:
    tst.l   g_head
    bne.s   1f
9:  movea.l %d2,%a4
    move.l  64(%a0),%d0
    jmp     {PRE_BACK:#x}
1:  lea     -44(%sp),%sp
    movem.l %d1-%d6/%a0-%a3/%a5,(%sp)
    bsr     drain_due               | an earlier frame's queued starts come first
    clr.l   g_note
    move.l  16(%a0),%d0
    moveq   #16,%d1
    cmp.l   %d1,%d0
    bcc     2f
    lsl.l   #T_SHIFT,%d0
    lea     tracks,%a5
    adda.l  %d0,%a5
    tst.l   T_NB(%a5)
    beq     2f
    move.l  84(%a0),%d1
    movea.l %a5,%a0
    bsr     find
    move.l  %a1,g_note
    beq     2f
    mvz.b   B_STATE(%a1),%d0
    subq.l  #PENDING,%d0
    beq.s   5f
    subq.l  #RUNNING-PENDING,%d0
p_dropped:
    beq     2f                      | running: the note joins it
    subq.l  #QUEUED-RUNNING,%d0
p_queued:
    beq     2f                      | queued in this frame: a later note of its trig joins it
    clr.l   g_note                  | dropped (another machine): the note's locks change at once
    bra     2f
5:  movea.l %a1,%a4
    tst.b   B_ISNEXT(%a4)
    beq.s   6f
    bsr     last_voice              | NEXT: it starts from this trig's own values, unless the trig
p_next_machine:
    bne.s   7f                      | changes machine or filter type (rule 4)
    bra     2f
7:  bsr     sv_drop
    bra     2f
6:
| stock loads a sound whole into the voice when the event names one at + 64 or the voice has
| another sound (0x40026bae..0x40026bee). Otherwise the restore leaves the slots the slide writes
| (their lock bits go below) and the applier gets only the others, so the voice takes its start
| values here (B_INIT 2), in the pass that reads them
    moveq   #1,%d0
    movea.l 24(%sp),%a0             | the event (a0, saved)
    tst.l   64(%a0)
    bne.s   3f
    move.l  60(%a0),%d1
    beq.s   3f
    lea     {VOICE_SOUND:#x},%a0
    cmp.l   (%a0,%d2.l*4),%d1
p_whole:
    bne.s   3f
    moveq   #2,%d0
3:  move.b  %d0,B_INIT(%a4)
    bsr     start_values
    tst.l   g_note
    beq     2f                      | (dropped: another machine)
| the voice's lock bits of the slots the slide writes go: stock's restore would set them to the
| sound's value only for the slide's start to overwrite them (h_post sets the bits again)
    move.l  4(%sp),%d0              | the voice (d2, saved)
    lsl.l   #4,%d0
    lea     {LOCKMASK:#x},%a0
    adda.l  %d0,%a0
    move.l  B_LMASK(%a4),%d0
    not.l   %d0
    and.l   %d0,(%a0)+
    move.l  B_LMASK+4(%a4),%d0
    not.l   %d0
    and.l   %d0,(%a0)+
    move.l  B_LMASK+8(%a4),%d0
    not.l   %d0
    and.l   %d0,(%a0)+
    move.l  B_LMASK+12(%a4),%d0
    not.l   %d0
    and.l   %d0,(%a0)
2:  movem.l (%sp),%d1-%d6/%a0-%a3/%a5
    lea     44(%sp),%sp
    bra     9b

| a4 = a slide, a5 = its track, in the note path: d3 = the track's last voice, or -1 when the
| track has no voice of its own with a sound. Z clear when the slide's sound has another machine or
| filter type than that voice's sound, or, with no such voice, than the track's own sound in the
| kit. Uses d0, d1, a0, a1
last_voice:
    move.l  T_LASTV(%a5),%d3
    subq.l  #1,%d3
    bmi.s   8f
    lea     {VOICE_TRACK:#x},%a0
    move.l  (%a0,%d3.l*4),%d0
    cmp.l   B_TNUM(%a4),%d0
    bne.s   8f
    lea     {VOICE_SOUND:#x},%a0
    move.l  (%a0,%d3.l*4),%d0
    beq.s   8f
    movea.l %d0,%a0
    bra.s   9f
8:  moveq   #-1,%d3                 | the kit's sound of the track, as the note path finds it
    move.l  B_TNUM(%a4),%d0
    move.l  #{SOUND_BYTES},%d1
    muls.l  %d1,%d0
    movea.l {KIT:#x},%a0
lv_kit:
    lea     {KIT_SOUND}(%a0,%d0.l),%a0
9:  movea.l B_SOUND(%a4),%a1
    move.w  {SOUND_MACHINE}(%a0),%d0
    cmp.w   {SOUND_MACHINE}(%a1),%d0
    rts

| a4 = a pending slide whose note plays on voice d2, a5 = its track. Its start values: what the
| track's last voice has now, or the sound's values when the track has no voice of its own. With
| B_INIT 2 and the last voice's values, voice d2 takes them here.
| Locks of the last note that this trig does not have go back to the sound's value (they join
| the slide). A last voice of another machine or filter type: the trig's values change at once.
| Uses d0-d6, a0-a3, a5
start_values:
    bsr     last_voice
sv_machine:
    bne     sv_drop
    tst.l   %d3
    bmi     sv_sound
| the last note's locks that slide, and that this trig does not lock (B_ELIG after prepare):
| d4..d6, a2 = its mask
    move.l  %d3,%d0
    lsl.l   #4,%d0
    lea     {LOCKMASK:#x},%a2
    adda.l  %d0,%a2
    mvz.w   B_N(%a4),%d5
    lea     B_LMASK(%a4),%a0        | none but this trig's slots: no return (and no read of B_ELIG)
    moveq   #0,%d1
    moveq   #3,%d4
8:  move.l  (%a0,%d4.l*4),%d0
    not.l   %d0
    and.l   (%a2,%d4.l*4),%d0
    or.l    %d0,%d1
    subq.l  #1,%d4
    bpl.s   8b
    tst.l   %d1
s_novel:
    beq     sv_values
    lea     B_ELIG(%a4),%a0
    move.l  (%a2),%d0
    and.l   (%a0),%d0
    move.l  4(%a2),%d1
    and.l   4(%a0),%d1
    or.l    %d1,%d0
    move.l  8(%a2),%d1
    and.l   8(%a0),%d1
    or.l    %d1,%d0
    move.l  12(%a2),%d1
    and.l   12(%a0),%d1
    or.l    %d1,%d0
sv_returns:
    beq.s   sv_values
    move.l  %d5,%d0
    lsl.l   #3,%d0
    lea     B_ENT(%a4,%d0.l),%a1
    moveq   #0,%d6                  | the mask's long
1:  move.l  (%a2,%d6.l*4),%d4
    lea     B_ELIG(%a4),%a0
    and.l   (%a0,%d6.l*4),%d4
2:  tst.l   %d4                     | (the trig's and these are distinct slots: at most MAX_ENTRIES)
    beq.s   4f
    move.l  %d4,%d0
    ff1     %d0
    moveq   #31,%d1
    sub.l   %d0,%d1
    bclr    %d1,%d4
    move.l  %d6,%d0
    lsl.l   #5,%d0
    add.l   %d1,%d0                 | the slot
    movea.l B_SOUND(%a4),%a0
    move.l  %d0,%d1
    add.l   %d1,%d1
    mvz.w   {SOUND_VALUES}(%a0,%d1.l),%d1
    bsr     add_entry
    bra.s   2b
4:  addq.l  #1,%d6
    moveq   #4,%d0
    cmp.l   %d0,%d6
    bne.s   1b
    move.w  %d5,B_N(%a4)
| every start value: the last voice's smoother state
sv_values:
    tst.l   %d5
    beq.s   sv_done
    mvz.b   B_INIT(%a4),%d0
    subq.l  #2,%d0
sv_claim:
    beq.s   sv_take
    move.l  #{STATE_VOICE_BYTES},%d0
    muls.l  %d3,%d0
    lea     {STATE:#x},%a0
    adda.l  %d0,%a0
    lea     B_ENT(%a4),%a1
5:  mvz.w   (%a1),%d1
    move.w  (%a0,%d1.l*2),%d0
    move.w  %d0,E_FROM(%a1)
    move.w  %d0,E_CUR(%a1)
    addq.l  #8,%a1
    subq.l  #1,%d5
    bne.s   5b
    bra.s   sv_done
| no voice of its own: the sound's values (sound + 20 + 2 slot = sound + offset - 14)
sv_sound:
    movea.l B_SOUND(%a4),%a0
    lea     {SOUND_VALUES}-{SRC_HEADER_BYTES}(%a0),%a0
    lea     B_ENT(%a4),%a1
    mvz.w   B_N(%a4),%d5
    tst.l   %d5
    beq.s   sv_done
6:  mvz.w   (%a1),%d1
    move.w  (%a0,%d1.l),%d0
    move.w  %d0,E_FROM(%a1)
    move.w  %d0,E_CUR(%a1)
    addq.l  #8,%a1
    subq.l  #1,%d5
    bne.s   6b
sv_done:
    moveq   #1,%d0
    move.b  %d0,B_INIT(%a4)
    rts
| the voice d2 takes each start value, voice d3's smoother state, as its target and its state, for
| each of the slide's entries (it has one at least). Only their offsets are read: B_INIT stays 2,
| and the drain fills the entries from the voice and claims its owners. The target is written even
| when d2 is d3, because a knob can leave a voice's target apart from its state. Uses d0, d1, d4,
| a0-a3, a5
sv_take:
    move.l  %d2,%d1
    bsr     voice_blocks            | a0 SRC, a1 STATE of the note's voice, both by an entry's offset
    move.l  #{STATE_VOICE_BYTES},%d0
    muls.l  %d3,%d0
    lea     {STATE:#x},%a3
    adda.l  %d0,%a3                 | voice d3's STATE
    lea     B_ENT(%a4),%a5
    mvz.w   B_N(%a4),%d4
1:  mvz.w   (%a5),%d1
    move.l  (%a3,%d1.l*2),%d0
    move.l  %d0,(%a1,%d1.l*2)
    swap    %d0
s_target:
    move.w  %d0,(%a0,%d1.l)
    addq.l  #8,%a5
    subq.l  #1,%d4
    bne.s   1b
    rts
sv_drop:
    moveq   #DROPPED,%d0
    move.b  %d0,B_STATE(%a4)
    clr.l   g_note
    rts

| ==== the note path's call of the lock applier (voice, list, mirror). A note of a length slide:
| the applier gets the trig's own list with its count lowered, for the call, to the locks that do
| not slide (prepare put them first), as the slide writes the rest. With none, stock's applier
| writes nothing and is not called; an applier whose first instruction is not stock's has been
| hooked by another mod (arpplocks reads the list's arp locks there) and is called
h_apply:
    move.l  g_note,%d0
    beq.s   1f
    movea.l %d0,%a0
    tst.b   B_ISNEXT(%a0)
    bne.s   1f
    mvz.w   B_NRES(%a0),%d0
a_none:
    bne.s   a_part
    move.l  {APPLIER:#x},%d1
    cmpi.l  #{APPLIER_ENTRY:#x},%d1
a_stock:
    bne.s   a_part
    rts
1:  jmp     {APPLIER:#x}
a_part:
    movea.l 8(%sp),%a1              | the list
    move.l  8(%a1),-(%sp)           | its count, put back after the call
    move.l  %d0,8(%a1)
    move.l  16(%sp),-(%sp)          | the applier's three arguments again
    move.l  16(%sp),-(%sp)
    move.l  16(%sp),-(%sp)
    jsr     {APPLIER:#x}
    lea     12(%sp),%sp
    movea.l 12(%sp),%a1
    move.l  (%sp)+,8(%a1)
    rts

| ==== the note path, after the applier: d2 = the voice, -36(%a6) = the event. Every note: the
| track's last voice, and the voice's note count. A note of a slide starts it or joins it, and a
| note outside any slide takes its voice out of the voice's old slide
h_post:
    clr.l   {FRAME_FLAG:#x}
    movea.l -36(%a6),%a0            | (d0, d1, a0 and a1 are free after the applier)
    move.l  16(%a0),%d0
    moveq   #16,%d1
    cmp.l   %d1,%d0
    bcc.s   8f
    lsl.l   #T_SHIFT,%d0
    lea     tracks,%a1
    adda.l  %d0,%a1
    move.l  T_LASTV(%a1),%d1        | the voice of the track's note before this one, + 1
    move.l  %d2,%d0
    addq.l  #1,%d0
    move.l  %d0,T_LASTV(%a1)
    tst.l   g_head
    bne.s   7f
8:  jmp     {POST_BACK:#x}
7:  move.l  g_frame,%d0             | no slide moves in this frame (slide_frame runs after notes)
    addq.l  #1,%d0
    move.l  %d0,g_start
    lea     -48(%sp),%sp
    movem.l %d1-%d6/%a0-%a5,(%sp)
    movea.l %a1,%a5
    lea     vserial,%a1
    mvz.b   (%a1,%d2.l),%d0
    addq.l  #1,%d0
    move.b  %d0,(%a1,%d2.l)
    lea     vslide,%a1
    move.l  g_note,%d0
    clr.l   g_note
    move.l  %d0,(%a1,%d2.l*4)
    beq.s   9f
    movea.l %d0,%a4
    mvz.b   B_STATE(%a4),%d0
    subq.l  #PENDING,%d0
    bne.s   2f
    mvz.b   B_INIT(%a4),%d0         | a start: queued, unless the voice took a whole sound (B_INIT 1)
    subq.l  #1,%d0
q_whole:
    beq.s   3f
    moveq   #QUEUED,%d0
    move.b  %d0,B_STATE(%a4)
    bra.s   4f
3:  bsr     note_start
    bra.s   9f
2:  subq.l  #QUEUED-PENDING,%d0
q_later:
    bne.s   5f
    tst.b   B_ISNEXT(%a4)           | a later note of a queued trig: the values of the voice of the
    bne.s   4f                      | note before it, which took them in h_pre (NEXT: its own)
    move.l  (%sp),%d3
    subq.l  #1,%d3
    bsr     sv_take
4:  bsr     queue_note
    bra.s   9f
5:
n_join:
    bsr     note_join
9:  movem.l (%sp),%d1-%d6/%a0-%a5
    lea     48(%sp),%sp
    bra.s   8b

| a4 = a pending slide whose trig plays on voice d2, a5 = its track: it starts
note_start:
    bsr     voice_claim
    moveq   #RUNNING,%d0
    move.b  %d0,B_STATE(%a4)
    move.l  {CLOCK:#x},%d0
    move.l  %d0,B_LAST(%a4)
    clr.l   B_PROG(%a4)
    moveq   #0,%d0
    bset    %d2,%d0
    move.l  %d0,B_MASK(%a4)
    bra.s   started

| a4 = a running slide, d2 = a later note's voice: the voice joins it
note_join:
    bsr     voice_claim
    move.l  B_MASK(%a4),%d0
    bset    %d2,%d0
    move.l  %d0,B_MASK(%a4)
    mvz.w   B_N(%a4),%d0
    add.l   %d0,B_WORK(%a4)
    rts

| a4 = a slide that started in this frame (in which no slide moves) on voice d2: the rate counts
| the new slide twice its entries until the next pass counts it (its first update reads more).
| Its phase is the next in turn, counted from its first voice, so slides on one voice take turns
| by their phases and the voices of one slide by their numbers
started:
    mvz.w   B_N(%a4),%d0
    add.l   %d0,%d0
    move.l  %d0,B_WORK(%a4)
    add.l   %d0,g_wsum
    move.l  g_rr,%d0
    addq.l  #1,%d0
    move.l  %d0,g_rr
    sub.l   %d2,%d0
    move.b  %d0,B_PHASE(%a4)
    bra     rate_set

| a4 = a slide, d2 = a voice: the voice's values that the slide moves become the slide's, with
| their lock bits, and, when its values are known, the voice takes them. Uses d0, d1, d3, d4,
| a0, a1, a2
voice_claim:
    move.l  %a3,-(%sp)
    mvz.w   B_N(%a4),%d4
    beq.s   5f
    move.l  %d2,%d1
    bsr     voice_blocks
    mvz.b   B_ID(%a4),%d3
    lea     B_ENT(%a4),%a3
    tst.b   B_INIT(%a4)
    beq.s   3f
1:  mvz.w   (%a3),%d1
    move.w  %d3,(%a2,%d1.l)
    mvz.w   E_CUR(%a3),%d0
    move.w  %d0,(%a0,%d1.l)
    swap    %d0
    move.l  %d0,(%a1,%d1.l*2)
    addq.l  #8,%a3
    subq.l  #1,%d4
    bne.s   1b
    bra.s   5f
3:  mvz.w   (%a3),%d1
    move.w  %d3,(%a2,%d1.l)
    addq.l  #8,%a3
    subq.l  #1,%d4
    bne.s   3b
| the lock bits: the voice's next note returns these values to the sound's
5:  move.l  %d2,%d0
    lsl.l   #4,%d0
    lea     {LOCKMASK:#x},%a0
    adda.l  %d0,%a0
    move.l  B_LMASK(%a4),%d0
    or.l    %d0,(%a0)+
    move.l  B_LMASK+4(%a4),%d0
    or.l    %d0,(%a0)+
    move.l  B_LMASK+8(%a4),%d0
    or.l    %d0,(%a0)+
    move.l  B_LMASK+12(%a4),%d0
    or.l    %d0,(%a0)
    movea.l (%sp)+,%a3
    rts

    .balign 4
due_voices:                         | by divisor: the voices due at a shift of 0
    .long 0xffff, 0x5555, 0, 0x1111

| ==== the lock-trig loop, for each voice of the track: d2 = the voice, d0 = the trig's list,
| -36(%a6) = the event. The voice gets a slide of its own, from its own values, and the applier
| the locks that do not slide. The next instruction removes the applier's 12 bytes of arguments
h_lock:
    move.l  %d0,g_lock_list
    moveq   #-1,%d1
    move.l  %d1,g_lock_n            | the applier gets the whole list
    tst.l   g_head
    beq     lock_apply
    move.l  g_frame,%d1             | no slide moves in this frame
    addq.l  #1,%d1
    move.l  %d1,g_start
    lea     -48(%sp),%sp
    movem.l %d1-%d7/%a0-%a4,(%sp)
    move.l  %d0,%d7
    bsr     drain                   | queued starts claim their owners before the revoke, as before
    bsr     revoke
    movea.l -36(%a6),%a0
    move.l  16(%a0),%d0
    moveq   #16,%d1
    cmp.l   %d1,%d0
    bcc.s   9f
    lsl.l   #T_SHIFT,%d0
    lea     tracks,%a0
    adda.l  %d0,%a0
    tst.l   T_NB(%a0)
    beq.s   9f
    move.l  %d7,%d1
    bsr     find
    tst.l   %a1
    beq.s   9f
    movea.l %a1,%a3                 | (a lock trig's slide is pending until its trig plays)
    moveq   #KIND_TEMPLATE,%d0
    move.b  %d0,B_KIND(%a3)
    moveq   #1,%d0
    move.b  %d0,B_USED(%a3)
    lea     {VOICE_SOUND:#x},%a0     | a voice playing another machine or filter type than the trig's
    move.l  (%a0,%d2.l*4),%d0       | sound takes the locks at once, as stock
    beq.s   2f
    movea.l %d0,%a0
    movea.l B_SOUND(%a3),%a1
    move.w  {SOUND_MACHINE}(%a0),%d0
    cmp.w   {SOUND_MACHINE}(%a1),%d0
l_machine:
    bne.s   9f
2:  bsr     pool_alloc
    tst.l   %a4
    beq.s   9f                      | no buffer: the locks change at once
    tst.b   B_ISNEXT(%a3)
    bne.s   1f
    mvz.w   B_NRES(%a3),%d0
    move.l  %d0,g_lock_n            | the voice's slide writes the locks that slide
1:  bsr     lock_slide
9:  movem.l (%sp),%d1-%d7/%a0-%a4
    lea     48(%sp),%sp
lock_apply:
    pea     {SRC:#x}
    move.l  g_lock_list,-(%sp)
    move.l  %d2,-(%sp)
    move.l  g_lock_n,%d0
l_part:
    bmi.s   1f
    movea.l g_lock_list,%a1         | the list's count lowered for the call, as in h_apply
    move.l  8(%a1),%d1
    move.l  %d1,g_lock_save
    move.l  %d0,8(%a1)
    jsr     {APPLIER:#x}
    movea.l g_lock_list,%a1
    move.l  g_lock_save,%d1
    move.l  %d1,8(%a1)
    jmp     {LOCK_BACK:#x}
1:  jsr     {APPLIER:#x}
    jmp     {LOCK_BACK:#x}

| d2 = a voice, d7 = a lock trig's list: each slot the list locks leaves every slide on the voice,
| so a slide writes no value that the lock replaced. A slide of this trig claims its own slots
| again after this. Uses d0, d1, a0, a1
revoke:
    movea.l %d7,%a0
    move.l  8(%a0),%d0
    beq.s   9f
    lea     20(%a0),%a0
    move.l  #202,%d1
    muls.l  %d2,%d1
    lea     owners,%a1
    adda.l  %d1,%a1
1:  mvz.w   (%a0),%d1
    add.l   %d1,%d1
l_revoke:
    clr.w   (%a1,%d1.l)
    addq.l  #8,%a0
    subq.l  #1,%d0
    bne.s   1b
9:  rts

| a3 = a lock trig's template, a4 = a new buffer, d2 = a voice: the voice's own slide, which reads
| its start values at its first update. Uses d0, d1, d3-d5, a0-a2, a5
lock_slide:
    movea.l %a3,%a0
    movea.l %a4,%a1
    move.b  B_ID(%a4),%d3
    moveq   #{HEADER_LONGS},%d0     | the header and the entries: the template's
1:  move.l  (%a0)+,(%a1)+
    subq.l  #1,%d0
    bne.s   1b
    mvz.w   B_N(%a4),%d0
    beq.s   3f
2:  move.l  (%a0)+,(%a1)+
    move.l  (%a0)+,(%a1)+
    subq.l  #1,%d0
    bne.s   2b
3:  move.b  %d3,B_ID(%a4)
    moveq   #KIND_VOICE,%d0
    move.b  %d0,B_KIND(%a4)
    clr.b   B_INIT(%a4)
    clr.b   B_SLOT(%a4)
    clr.b   B_HELD(%a4)
    clr.b   B_USED(%a4)
    clr.l   B_LIST(%a4)
    lea     vserial,%a0
    move.b  (%a0,%d2.l),%d0
    move.b  %d0,B_VSER(%a4)
    bsr     voice_claim
    moveq   #RUNNING,%d0
    move.b  %d0,B_STATE(%a4)
    move.l  {CLOCK:#x},%d0
    move.l  %d0,B_LAST(%a4)
    clr.l   B_PROG(%a4)
    moveq   #0,%d0
    bset    %d2,%d0
    move.l  %d0,B_MASK(%a4)
    move.l  g_head,%d0
    move.l  %d0,B_NEXT(%a4)
    move.l  %a4,g_head
    bra     started
"""
