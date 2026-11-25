"""The parameter-slide engine's routines, as an assembly template for `scripts/build_pslide.py`.

`build_pslide.py` carries the reading of the firmware and the rules. This module holds the code
that runs in the instrument, as `dnfw.osport.render` text: each stock address is a name that the
build script defines, so the same text assembles for OS 1.11 and 1.12.

The routines, by where they run:

- `slide_frame` (the hook bus's `ev_frame`, every audio frame): each running slide writes its
  voices that are due, by the sequencer's clock. In a frame where a note or a lock trig plays,
  nothing moves.
- `h_prep` (step evaluation, a step ahead of the note) is `scripts/pslide_prepare.py`'s: a trig
  with SLD gets a pending slide, which its notes find by the trig's lock list.
- the note and lock-trig hooks are `scripts/pslide_notes.py`'s: a note of a pending slide starts
  it, a later note of the same trig joins it, and each voice of a lock trig gets a slide of its own.

A value belongs to one slide at a time: `owners` (a word for each voice and slot) names the slide
that writes it, so a lock trig on a sliding voice takes only its own parameters.

Each slide entry is 8 bytes: the value's offset in a voice's SRC block (34 + 2 slot), its start,
its target and the value last written.
"""

ENGINE = """
    .equ T_NB, 0
    .equ T_LASTV, 8
    .equ T_SLOT, 12
    .equ T_SIZE, 32
    .equ PLACES, 5
    .equ B_STATE, 0
    .equ B_N, 2
    .equ B_LIST, 4
    .equ B_TRACK, 8
    .equ B_TNUM, 12
    .equ B_NEXT, 16
    .equ B_MASK, 20
    .equ B_LAST, 24
    .equ B_PROG, 28
    .equ B_LEN, 32
    .equ B_KIND, 36
    .equ B_INIT, 37
    .equ B_SLOT, 38
    .equ B_PHASE, 39
    .equ B_SH, 40
    .equ B_ID, 41
    .equ B_VSER, 42
    .equ B_HELD, 43
    .equ B_WORK, 44
    .equ B_PTN, 48
    .equ B_SOUND, 52
    .equ B_LENS, 56
    .equ B_ISNEXT, 60
    .equ B_USED, 61
    .equ B_ARRIVED, 62
    .equ B_ELIG, 64
    .equ B_LMASK, 80
    .equ B_NRES, 96
    .equ B_ENT, 100
    .equ E_FROM, 2
    .equ E_TO, 4
    .equ E_CUR, 6
    .equ BUF_SIZE, {BUF_SIZE}
    .equ MAX_ENTRIES, {MAX_ENTRIES}
    .equ KIND_NOTE, 0
    .equ KIND_TEMPLATE, 2
    .equ KIND_VOICE, 3
    .equ PENDING, 1
    .equ RUNNING, 2
    .equ DROPPED, 3

| ==== the hook bus's ev_frame: every audio frame, before the smoother
slide_frame:
    addq.l  #1,g_frame
    tst.l   g_head
    beq.s   9f
    move.l  g_start,%d0
    cmp.l   g_frame,%d0
f_note:
    bne.s   frame_work
9:  rts                             | (a note or a lock trig played in this frame: nothing moves)
frame_work:
    lea     -44(%sp),%sp
    movem.l %d2-%d7/%a2-%a6,(%sp)
    moveq   #0,%d7
    tst.l   {PLAYING:#x}
    bne.s   1f
f_stopped:
    moveq   #1,%d7                  | the sequencer stopped: every running slide ends where it is
1:
f_cut:
    bsr     pattern_cut
    move.l  g_played,%d0            | the frame the sequencer stops in
    and.l   %d7,%d0
    move.l  %d0,g_stop_edge
    moveq   #1,%d0
    sub.l   %d7,%d0
    move.l  %d0,g_played
    clr.l   g_wsum
    lea     g_head,%a5
w_loop:
    move.l  (%a5),%d0
    beq     w_done
    movea.l %d0,%a3
    tst.l   g_cut_now
    beq.s   2f
    move.l  {PATTERN:#x},%d0
    cmp.l   B_PTN(%a3),%d0
    bne     w_free                  | another pattern plays: it ends where it is
2:  tst.l   %d7
    bne.s   3f
    tst.b   B_HELD(%a3)
    beq.s   3f
    movea.l B_LIST(%a3),%a0
    moveq   #1,%d0
    cmp.l   (%a0),%d0
w_alone:
    bne.s   3f                      | stock still holds the trig's list: its notes can come
    mvz.b   B_STATE(%a3),%d0
    subq.l  #RUNNING,%d0
    bne.s   4f
    bsr     let_go                  | stock is done with the trig: the slide goes on, and no note finds it
    bra.s   3f
4:
w_unplayed:
    bra     w_free                  | stock is done with a trig whose notes never came (a muted track, a condition)
3:  mvz.b   B_STATE(%a3),%d0
    subq.l  #RUNNING,%d0
    beq.s   w_run
    bpl     w_free                  | a pending slide whose list came again
    tst.b   B_USED(%a3)
    bne     w_free                  | a lock trig's template, once its trig has played
    tst.l   g_stop_edge
    beq.s   w_keep
    tst.b   B_HELD(%a3)
w_stale:
    beq.s   w_keep                  | the preview list's slide, which holds no count, waits for PLAY
    bra     w_free                  | the sequencer has just stopped: a played step's notes will not come
w_run:
    tst.l   %d7
    bne     w_free
    move.l  B_WORK(%a3),%d0
    add.l   %d0,g_wsum
| its voices due in this frame: voice v when (v + phase + frame) & div is 0, so a slide on many
| voices spreads over the frames as slides on one voice do
    mvz.b   B_PHASE(%a3),%d0
    add.l   g_frame,%d0
    neg.l   %d0
    and.l   g_div,%d0
    move.l  g_due,%d1
    lsl.l   %d0,%d1
    and.l   B_MASK(%a3),%d1
w_due:
    beq.s   w_keep
    move.l  %d1,g_due_now
    bsr     update
    tst.l   %d0
    beq.s   w_keep
w_free:
    move.l  B_NEXT(%a3),(%a5)
    bsr     release
    bra     w_loop
w_keep:
    lea     B_NEXT(%a3),%a5
    bra     w_loop
w_done:
    bsr     rate_set
    movem.l (%sp),%d2-%d7/%a2-%a6
    lea     44(%sp),%sp
frame_exit:
    rts

| d7 = 1 when stopped. g_cut_now = 1 in the frame from which a slide of a pattern that no longer
| plays ends: at once while stopped, else as the new pattern's first step plays. Stock's switch of
| the pattern pointer sets the step word to the new pattern's first step, 0, as it evaluates it, a
| step early: it plays one tick after the step word next changes. directjump's sets it to the
| playing position, and that step plays one tick after the switch. Uses d0
pattern_cut:
    move.l  %d7,g_cut_now
    move.l  {PATTERN:#x},%d0
    cmp.l   g_ptn,%d0
    beq.s   1f
    move.l  %d0,g_ptn               | a change
    mvz.w   {STEP_WORD:#x},%d0
p_early:
    bne.s   3f
    move.l  %d0,g_cut_step          | step 0: the next step change starts the last tick
    moveq   #1,%d0
    move.l  %d0,g_cut_wait          | 1: until the step word changes, 2: until g_cut_at
    bra.s   1f
3:  move.l  {CLOCK:#x},%d0          | another step: the next tick
    addi.l  #{TICK_UNITS},%d0
    move.l  %d0,g_cut_at
    moveq   #2,%d0
    move.l  %d0,g_cut_wait
1:  move.l  g_cut_wait,%d0
    beq.s   9f
    subq.l  #1,%d0
    bne.s   2f
    mvz.w   {STEP_WORD:#x},%d0
    cmp.l   g_cut_step,%d0
    beq.s   9f
    move.l  {CLOCK:#x},%d0
    addi.l  #{TICK_UNITS},%d0
    move.l  %d0,g_cut_at
    moveq   #2,%d0
    move.l  %d0,g_cut_wait
2:  move.l  g_cut_at,%d0
    sub.l   {CLOCK:#x},%d0
    bgt.s   9f
    clr.l   g_cut_wait
    moveq   #1,%d0
    move.l  %d0,g_cut_now
9:  rts

| The next frame's divisor: every frame while the running slides' value writes fit the budget,
| every second frame up to twice it, every fourth above (a slide catches up by its clock), and
| g_due, the voices due at a shift of 0. Uses d0, d1, a0
rate_set:
    move.l  g_wsum,%d0
    moveq   #0,%d1
    cmpi.l  #{BUDGET},%d0
    bls.s   1f
    moveq   #1,%d1
    cmpi.l  #{BUDGET2},%d0
    bls.s   1f
    moveq   #3,%d1
1:  move.l  %d1,g_div
    lea     due_voices,%a0
    move.l  (%a0,%d1.l*4),%d0
    move.l  %d0,g_due
    rts

| a3 = a slide that ends where it is: our hold on its list, its place among the track's slides,
| and its buffer, back to the pool. Not its link in g_head, which the caller has removed. Uses
| d0, d1, a0, a1
release:
    bsr.s   let_go
    clr.b   B_STATE(%a3)
    move.w  %sr,%d1
    move.w  #0x2700,%sr
    move.l  g_free,%d0
    move.l  %d0,B_NEXT(%a3)
    move.l  %a3,g_free
    move.w  %d1,%sr
    rts

| a3 = a slide: it leaves its place among the track's slides, so no later note finds it, and lets
| go of its trig's list. Uses d0, d1, a0, a1
let_go:
    mvz.b   B_SLOT(%a3),%d0
    beq.s   2f
    movea.l B_TRACK(%a3),%a0
    lea     T_SLOT-4(%a0),%a1
    clr.l   (%a1,%d0.l*4)
    subq.l  #1,T_NB(%a0)
    clr.b   B_SLOT(%a3)
2:  tst.b   B_HELD(%a3)
    beq.s   3f
    clr.b   B_HELD(%a3)
    move.l  B_LIST(%a3),-(%sp)
    jsr     {LIST_RELEASE:#x}
    addq.l  #4,%sp
3:  rts

| a3 = a running slide, g_due_now = its voices due: one update, which writes those voices. d0 = 0:
| it goes on, 1: it has ended. Uses d0-d6, a0-a2, a4, a6
update:
    move.l  B_MASK(%a3),%d2
    bsr     members
    move.l  %d2,B_MASK(%a3)
    beq     u_ended                 | no voice follows it
    mvz.w   B_N(%a3),%d0
    beq     u_ended                 | no value left in it
    muls.l  %d0,%d4
    move.l  %d4,B_WORK(%a3)
    bsr     first_voice             | d2 -> a0, a1, a2: its SRC and STATE blocks and owners
    tst.b   B_INIT(%a3)
    bne.s   1f
| a slide that starts from the voice's own values reads them at its first update
    lea     B_ENT(%a3),%a4
    mvz.w   B_N(%a3),%d4
2:  mvz.w   (%a4),%d1
    move.w  (%a1,%d1.l*2),%d0
    move.w  %d0,E_FROM(%a4)
    move.w  %d0,E_CUR(%a4)
    addq.l  #8,%a4
    subq.l  #1,%d4
    bne.s   2b
    moveq   #1,%d0
    move.b  %d0,B_INIT(%a3)
| its progress, by the sequencer's clock (clock / 16, the remainder kept): a tempo change
| changes the rest of it
1:  move.l  {CLOCK:#x},%d0
    move.l  %d0,%d1
    sub.l   B_LAST(%a3),%d1
u_back:
    bmi.s   3f                      | the clock went back (external clock): it waits
    move.l  %d1,%d0
    lsr.l   #4,%d1
    add.l   %d1,B_PROG(%a3)
    moveq   #15,%d1
    not.l   %d1
    and.l   %d1,%d0
    add.l   %d0,B_LAST(%a3)
    bra.s   4f
3:  move.l  %d0,B_LAST(%a3)
4:  move.l  B_PROG(%a3),%d3
    cmp.l   B_LEN(%a3),%d3
    bcc     u_arrive
| f = progress / length, in 15 bits
    mvz.b   B_SH(%a3),%d0
    lsr.l   %d0,%d3
    moveq   #15,%d0
    lsl.l   %d0,%d3
    move.l  B_LENS(%a3),%d0
    divu.l  %d0,%d3
| each value: from + (to - from) * f. A target that is not its smoother state's value (on the
| first voice) has had another writer (a knob, or a CC): that value leaves the slide, and follows
| its writer
    mvz.w   B_N(%a3),%d4
    move.l  %d4,%d0
    lsl.l   #3,%d0
    lea     B_ENT-8(%a3,%d0.l),%a6  | the last entry
    lea     B_ENT(%a3),%a4
    moveq   #15,%d5
    move.l  g_due_now,%d0           | one voice, and due: it takes each value as it is computed
    and.l   %d2,%d0
    cmp.l   %d2,%d0
    bne.s   5f
    subq.l  #1,%d0
    and.l   %d2,%d0
u_one:
    beq.s   u_single
5:  cmpa.l  %a6,%a4
    bhi.s   7f
    mvz.w   (%a4),%d1
    move.w  (%a0,%d1.l),%d0
    cmp.w   (%a1,%d1.l*2),%d0
u_foreign_all:
    bne.s   6f
    mvz.w   E_FROM(%a4),%d6
    mvz.w   E_TO(%a4),%d0
    sub.l   %d6,%d0
    muls.l  %d3,%d0
    asr.l   %d5,%d0
    add.l   %d6,%d0
    move.w  %d0,E_CUR(%a4)
    addq.l  #8,%a4
    bra.s   5b
6:  move.l  (%a6),(%a4)             | the last entry takes its place
    move.l  4(%a6),4(%a4)
    subq.l  #8,%a6
    subq.l  #1,%d4
    bra.s   5b
7:  move.w  %d4,B_N(%a3)
    and.l   g_due_now,%d2
    bsr     write_voices
u_owned:
    tst.l   g_owned
    bne.s   8f
    mvz.b   B_KIND(%a3),%d0
    subq.l  #KIND_VOICE,%d0
u_taken:
    beq     u_ended                 | a lock trig's voice slide that a later one has taken whole
8:  moveq   #0,%d0
    rts
| the slide's one voice (a0, a1, a2) takes each value it owns as the value is computed
u_single:
    clr.l   g_owned
    mvz.b   B_ID(%a3),%d2
1:  cmpa.l  %a6,%a4
    bhi.s   3f
us_each:
    mvz.w   (%a4),%d1
    move.w  (%a0,%d1.l),%d0
    cmp.w   (%a1,%d1.l*2),%d0
u_foreign:
    bne.s   2f
    mvz.w   E_FROM(%a4),%d6
    mvz.w   E_TO(%a4),%d0
    sub.l   %d6,%d0
    muls.l  %d3,%d0
    asr.l   %d5,%d0
    add.l   %d6,%d0
    move.w  %d0,E_CUR(%a4)
    addq.l  #8,%a4
    mvz.w   (%a2,%d1.l),%d6
    cmp.l   %d2,%d6
w_owner:
    bne.s   1b
    move.w  %d0,(%a0,%d1.l)
    swap    %d0
    move.l  %d0,(%a1,%d1.l*2)
    addq.l  #1,g_owned
    bra.s   1b
2:  move.l  (%a6),(%a4)             | the last entry takes its place
    move.l  4(%a6),4(%a4)
    subq.l  #8,%a6
    subq.l  #1,%d4
    bra.s   1b
3:  move.w  %d4,B_N(%a3)
    bra.s   u_owned
| it arrives: every value is its target, on each voice in its turn, and it ends once each voice
| that follows it has had its targets. A value that another writer has changed since the last
| update (on the first voice) leaves the slide, as before
u_arrive:
    mvz.w   B_N(%a3),%d4
    move.l  %d4,%d0
    lsl.l   #3,%d0
    lea     B_ENT-8(%a3,%d0.l),%a6  | the last entry
    lea     B_ENT(%a3),%a4
1:  cmpa.l  %a6,%a4
    bhi.s   3f
    mvz.w   (%a4),%d1
    move.w  (%a0,%d1.l),%d0
    cmp.w   (%a1,%d1.l*2),%d0
u_foreign_end:
    bne.s   2f
    move.w  E_TO(%a4),E_CUR(%a4)
    addq.l  #8,%a4
    bra.s   1b
2:  move.l  (%a6),(%a4)             | the last entry takes its place
    move.l  4(%a6),4(%a4)
    subq.l  #8,%a6
    subq.l  #1,%d4
    bra.s   1b
3:  move.w  %d4,B_N(%a3)
    movea.l %d2,%a6                 | (write_voices keeps a6)
    and.l   g_due_now,%d2
    bsr     write_voices
    mvz.w   B_ARRIVED(%a3),%d0
    or.l    g_due_now,%d0
    move.w  %d0,B_ARRIVED(%a3)
    not.l   %d0
    move.l  %a6,%d1
    and.l   %d1,%d0
u_all:
    beq.s   u_ended
    moveq   #0,%d0
    rts
u_ended:
    moveq   #1,%d0
    rts

| a3 = a slide, d2 = its voices: the voices that still follow it. d2 = those, d4 = how many.
| A voice follows it while it has had no other note since (every note, of any track, passes
| h_post): for a note's slide, the voice's last note is of the slide; for a lock trig's, the
| voice's note count is the one the slide started with. Uses d0, d1, d3, d5, a0
members:
    move.l  %d2,%d3
    moveq   #0,%d4
1:  tst.l   %d3
    beq.s   9f
    move.l  %d3,%d0
    move.l  %d0,%d1
    neg.l   %d1
    and.l   %d1,%d0
    eor.l   %d0,%d3
    move.l  %d0,%d5
    ff1     %d0
    moveq   #31,%d1
    sub.l   %d0,%d1
    mvz.b   B_KIND(%a3),%d0
    subq.l  #KIND_VOICE,%d0
    bne.s   2f
    lea     vserial,%a0
    mvz.b   (%a0,%d1.l),%d0
    mvz.b   B_VSER(%a3),%d1
    cmp.l   %d1,%d0
m_vserial:
    bne.s   3f
    addq.l  #1,%d4
    bra.s   1b
2:  lea     vslide,%a0
    cmpa.l  (%a0,%d1.l*4),%a3
m_vslide:
    bne.s   3f
    addq.l  #1,%d4
    bra.s   1b
3:  eor.l   %d5,%d2
    bra.s   1b
9:  rts

| d2 = voices: a0, a1, a2 = the first one's SRC and STATE blocks and owners (voice_blocks). Uses d0, d1
first_voice:
    move.l  %d2,%d1
    move.l  %d1,%d0
    neg.l   %d0
    and.l   %d0,%d1
    ff1     %d1
    moveq   #31,%d0
    sub.l   %d1,%d0
    move.l  %d0,%d1
    bra     voice_blocks

| a3 = a slide, d2 = its voices: each voice gets each value it still owns, as its target and its
| smoother state. g_owned = how many it wrote. Uses d0, d1, d3, d4, d6, a0-a2, a4
write_voices:
    clr.l   g_owned
    move.l  %d2,%d3
    mvz.b   B_ID(%a3),%d6
1:  tst.l   %d3
    beq.s   9f
    move.l  %d3,%d0
    move.l  %d0,%d1
    neg.l   %d1
    and.l   %d1,%d0
    eor.l   %d0,%d3
    ff1     %d0
    moveq   #31,%d1
    sub.l   %d0,%d1
    bsr     voice_blocks            | d1 -> a0 SRC, a1 STATE, a2 owner bytes
    lea     B_ENT(%a3),%a4
    mvz.w   B_N(%a3),%d4
    beq.s   1b
wv_each:
2:  mvz.w   (%a4),%d1
    mvz.w   (%a2,%d1.l),%d0
    cmp.l   %d6,%d0
w_owner_all:
    bne.s   3f
    mvz.w   E_CUR(%a4),%d0
    move.w  %d0,(%a0,%d1.l)
    swap    %d0
    move.l  %d0,(%a1,%d1.l*2)
    addq.l  #1,g_owned
3:  addq.l  #8,%a4
    subq.l  #1,%d4
    bne.s   2b
    bra.s   1b
9:  rts

| d1 = a voice: a0, a1 = its SRC and STATE blocks, a2 = its owner words less 34, so that an
| entry's offset indexes them. Uses d0
voice_blocks:
    move.l  #202,%d0
    muls.l  %d1,%d0
    lea     owners-34,%a2
    adda.l  %d0,%a2
    lea     {SRC:#x},%a0
    adda.l  %d0,%a0
    add.l   %d0,%d0
    lea     {STATE:#x},%a1
    adda.l  %d0,%a1
    rts

| a0 = a track, d1 = a list: a1 = the track's slide with that list (0: none), d0 = its place
find:
    moveq   #0,%d0
1:  movea.l T_SLOT(%a0,%d0.l*4),%a1
    tst.l   %a1
    beq.s   2f
    cmp.l   B_LIST(%a1),%d1
    beq.s   3f
2:  addq.l  #1,%d0
    cmpi.l  #PLACES,%d0
    bne.s   1b
    suba.l  %a1,%a1
3:  rts

| a4 = a buffer from the pool with its id, or 0 when every buffer is in use (the trig's locks
| then change at once, as on stock). Uses d0, d1, d5
pool_alloc:
    move.w  %sr,%d5
    move.w  #0x2700,%sr
    move.l  g_free,%d0
    beq.s   1f
    movea.l %d0,%a4
    move.l  B_NEXT(%a4),%d0
    move.l  %d0,g_free
    bra.s   2f
1:  move.l  g_bump,%d0
    cmpi.l  #{POOL_N},%d0
    bcc.s   3f
    addq.l  #1,g_bump
    move.l  #BUF_SIZE,%d1
    muls.l  %d0,%d1
    lea     pool,%a4
    adda.l  %d1,%a4
    addq.l  #1,%d0
    move.b  %d0,B_ID(%a4)
2:  move.w  %d5,%sr
    rts
3:  suba.l  %a4,%a4
    bra.s   2b
"""
