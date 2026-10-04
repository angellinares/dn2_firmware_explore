"""Reload confirm: an opt-in YES/NO prompt before FUNC + NO reloads the pattern.

    python scripts/build_reload_confirm.py [--out PATH]

FUNC + NO reloads the active pattern from its temporary save (manual 10.12.6)
at once, and a mistaken press loses the work since. This build adds a toggle,
**SETTINGS > PERSONALIZE > RELOAD CONFIRM**. Off (the default, and what a fresh
or reset instrument reads) FUNC + NO is stock. On, it opens the stock YES/NO
prompt first:

    ARE YOU SURE YOU WANT TO
    RELOAD THE PATTERN? Y/N

YES reloads exactly as FUNC + NO does; NO leaves the pattern alone. A performer
switches it off to get the immediate reload back.

## What FUNC + NO runs, read 2026-10-04 (OS 1.11)

The main key handler `0x4005ed12` switches on the key code less one
(`0x40116018`); NO is code 12, its case `0x4005f16c`. With FUNC held
(`0x401160ac`) and the key pressed (`0x401160bc`), `0x4005f1a2..0x4005f1be`
calls the pattern reload `0x400444da(%a2@(152), 1, pattern, 1, 1)`, the pattern
from `0x400f6df8(%a2@(160))`, and leaves through `0x4005fb1c` (pops the six
pushes) to `0x4005ef52` (handled). Nothing in between asks.

The pattern menu's RELOAD (`PatternReloadMenuView`) already asks first:
`0x401a5e2c` builds a YES/NO prompt -- the class every stock "... Y/N" prompt
uses, constructor `0x40112a2e` (38 callers) -- made with make_shared (0x8c
bytes: control block `0x401dd3d4`, the object at +16), two lines, and a
`std::function<void(bool)>` (manager `0x401a4358`, invoker `0x401a528a`), and
pushes it with `0x4011d71e(0x4002c47a(0x4018c8dc()), &view, 0)`. Its YES calls
the same reload with 0 in place of FUNC + NO's 1: 0 is the saved pattern, 1 the
temporary save. This build's prompt is that sequence with our own lines and
invoker, which passes 1.

## Why our prompt drops one key release (emulator, 2026-10-04)

A prompt answers on a key's **release** (`0x40116040`, event `+16` bit 4), and
the stock menus open theirs on a release too: with YES held in the pattern
menu nothing opens, and the prompt appears when it comes up. FUNC + NO acts on
the **press**. Opened there, the prompt is on top when NO comes up and takes
that release as the answer NO: it closed at once (`on2/`: drawn while NO was
held, gone after).

Opening on NO's release instead does not work from the key handler: with no
prompt open, the release goes to the open page's own handler
(`0x40067c30`, `0x40068244`) and never reaches `0x4005ed12` (traced: the
handler ran for the press and its repeat only).

So the prompt opens on the press, and **our instance** gets a copy of the
prompt's vtable (`0x40206264`, its offset-to-top and typeinfo before it,
copied at run time) whose key handler (entry 2, stock `0x40112b84`) drops the
first NO release, then passes everything to the stock handler. A fresh NO
press clears the drop first, so a real answer is never lost. Other prompts
keep the stock vtable; ours is only retargeted if it still holds
`0x40206264` after construction.

## Where the toggle lives

PERSONALIZE's values are one-byte fields of the settings block at `0x405cd85c`:
magic `COKi`, checksum, version 6, payload length 66, payload from `0x405cd86c`
(defaults `0x400bb394`, migration `0x400bb532`, every setter through
`0x400bb4f8(dst, src, n)`, which re-signs the block). The block heads the
working state that is saved to the +Drive whole (`0x400f1ebe`) and read back at
start-up (`0x400f2004`): a 256-byte header read, then 0xc4b114 bytes, through
`0x41218970`. So every byte from `0x405cd85c` on is persisted.

The block is 256 bytes (the header read), and the C library's rand seed
follows it at `0x405cd95c` (`0x40150670`). Its payload ends at `0x405cd8ad`;
**no instruction in the image addresses `0x405cd8ae..0x405cd95b`**, absolutely
or by an immediate. The toggle is the byte at `FLAG` (`0x405cd8ae`): saved and
restored with the block, outside its checksum, ignored by stock (so flashing
stock back is harmless), and zero on a fresh instrument (BSS). Only the value 1
means on.

Not reset by the settings defaults (`0x400bb394` clears 0x52 bytes): a block
reset leaves the toggle as it was.

## The PERSONALIZE item

`PersonalizeMenuView`'s constructor `0x40097d48` builds its eleven items one
block each: four `std::function`s (16 bytes: functor, -, manager, invoker),
`new(0x54)`, `0x401170d8(item, &name, &press, &value, &adjust, -1, 8)`,
`0x4011690e(view, item)`, then each function's destructor `0x40188086`. PAGE
AUTOCOPY (`0x40098166`) is the model, an on/off item whose press and adjust
capture the view:

| function | PAGE AUTOCOPY's invoker / manager | this build's |
|---|---|---|
| name | `0x40096464` / `0x40096ee2` | `name`, the same manager |
| press | `0x400966d8` / `0x40096f34` (captures the view) | `press` |
| value | `0x40097802` / `0x40096f90` (ON/OFF from `*0x44644d84 + 28 * on`) | `value` |
| adjust | `0x4009670a` / `0x40096fe2` (captures the view) | `adjust` |

The stock managers are reused: they only allocate, copy and free the 1- or
4-byte functor, so they are right for ours. The item is appended last, by a
hook on the constructor's epilogue (`0x4009863e`, its `movem.l` displaced).
"""

from __future__ import annotations

import argparse
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dnfw.cli.files import read_image
from dnfw.container.section import compress
from dnfw.firmware import build as fwbuild
from dnfw.firmware.load import load
from dnfw.mods import platform
from dnfw.patch.assemble import assemble, available

MAIN_OS = 3
BASE = 0x40000400

# RAM above BSS, given to this mod: above layermidi's chunk (0x467d8000).
CODE_VA = 0x467E0000

FLAG = 0x405CD8AE               # the toggle: the settings block's unaddressed tail
SETTINGS_WRITE = 0x400BB4F8     # (dst, src, n): write a setting, re-sign the block
NEW = 0x40120264                # operator new(size)
STR_CTOR = 0x401CE69E           # std::string(this, const char *, const alloc &)
STR_DTOR = 0x401CCBEE
FUNC_DTOR = 0x40188086          # std::function destructor(this)
SP_RELEASE = 0x401880CC         # shared_ptr count release(&count)
SP_GET = 0x4018816A             # make_shared's object from its control block
SP_MOVE = 0x401A54AA            # shared_ptr move(dst, src)
ITEM_BUILD = 0x401170D8
ITEM_APPEND = 0x4011690E
REDRAW = 0x4011C7BA             # the view's redraw(view + 56)
VALUE_DRAW = 0x401157FC
ONOFF = 0x44644D84              # -> OFF; ON at +28
MGR_NAME, MGR_PRESS, MGR_VALUE, MGR_ADJUST = 0x40096EE2, 0x40096F34, 0x40096F90, 0x40096FE2
PROMPT = 0x40112A2E             # the YES/NO prompt's constructor(this, line1, line2, &fn, 0)
PROMPT_CTRL = 0x401DD3D4        # its make_shared control block's vtable
PROMPT_TAG = 0x401D3B60         # make_shared's tag type
PROMPT_MGR = 0x401A4358         # a 1-byte functor's manager (the menu prompt's)
VIEWS = 0x4018C8DC              # -> the UI ...
VIEW_STACK = 0x4002C47A         # ... -> its view stack
VIEW_PUSH = 0x4011D71E          # (stack, &shared_ptr<view>, 0)
UI_STATE = 0x4018AA20           # what the menu prompt's YES passes to PATTERN_OF
PATTERN_OF = 0x400F6DF8
SEQUENCER = 0x4018A97A          # the reload's first argument
RELOAD = 0x400444DA             # (sequencer, temporary, pattern, 1, 1)

KEY_SITE = 0x4005F1A2           # FUNC + NO, pressed: the reload's first two instructions
KEY_DISPLACED = bytes.fromhex("2f2a00a0" "4eb9400f6df8")  # move.l 160(%a2),-(%sp) ; jsr 0x400f6df8
KEY_BACK = KEY_SITE + len(KEY_DISPLACED)
HANDLED = 0x4005EF52            # the handler's exit: key handled
KEY_CODE = 0x40116018           # key event: its code (+12)
PRESSED = 0x401160BC            # ...pressed, not a repeat (+16 bit 0, not bit 3)
RELEASED = 0x40116040           # ...the event a prompt answers on (+16 bit 4): the release
PROMPT_VTABLE = 0x40206264      # the prompt's primary vtable (offset-to-top, typeinfo before it)
PROMPT_KEYS_SLOT = 2            # its key handler's entry ...
PROMPT_KEYS = 0x40112B84        # ... this one
VTABLE_LONGS = 19               # the two header longs and the 17 entries, to 0x402062a4
MENU_SITE = 0x4009863E          # PersonalizeMenuView's constructor, its epilogue
MENU_DISPLACED = bytes.fromhex("4cef7c7c0018")    # movem.l 24(%sp),%d2-%d6/%a2-%a6
MENU_BACK = MENU_SITE + len(MENU_DISPLACED)

NAME = "RELOAD CONFIRM"
LINE1 = "ARE YOU SURE YOU WANT TO"
LINE2 = "RELOAD THE PATTERN? Y/N"

LABELS = ("key_hook", "menu_hook")

SOURCE = f"""
| FUNC + NO, pressed, reached by jmp. Off: the stock reload. On: the prompt.
key_hook:
    mvz.b   {FLAG:#x},%d0
    moveq   #1,%d1
    cmp.l   %d1,%d0
    beq.s   1f
    move.l  160(%a2),-(%sp)             | the displaced instructions
    jsr     {PATTERN_OF:#x}
    jmp     {KEY_BACK:#x}
1:  bsr.w   confirm
    jmp     {HANDLED:#x}

| The prompt's key handler, for our prompt only (`confirm` points its vtable
| here). The prompt opens on NO's press, and a prompt answers on a release
| (0x40112bee): left alone, the release of the NO that opened it would answer
| NO. So that one release is dropped; a fresh NO press first clears the drop.
prompt_keys:
    tst.b   swallow
    beq.s   9f
    move.l  8(%sp),-(%sp)
    jsr     {KEY_CODE:#x}
    addq.l  #4,%sp
    moveq   #12,%d1                     | NO
    cmp.l   %d1,%d0
    bne.s   9f
    move.l  8(%sp),-(%sp)
    jsr     {RELEASED:#x}
    addq.l  #4,%sp
    tst.l   %d0
    beq.s   1f
    clr.b   swallow                     | the opening NO's release: dropped
    moveq   #1,%d0                      | handled
    rts
1:  move.l  8(%sp),-(%sp)
    jsr     {PRESSED:#x}
    addq.l  #4,%sp
    tst.b   %d0
    beq.s   9f
    clr.b   swallow                     | a new NO press: the answer to come
9:  jmp     {PROMPT_KEYS:#x}

| The YES/NO prompt, as the pattern menu's RELOAD builds it (0x401a5e2c).
| Frame: -16 the callback (then the view's shared_ptr), -24 the made one,
| -28 and -32 the two lines, -33 and -34 their allocators.
confirm:
    link    %a6,#-64
    lea     -16(%sp),%sp
    movem.l %d2/%d5/%a2-%a3,(%sp)
    pea     0x8c
    jsr     {NEW:#x}
    addq.l  #4,%sp
    move.l  %d0,%a2
    tst.l   %d0
    beq.w   9f
    moveq   #1,%d0
    move.l  %d0,4(%a2)
    move.l  %d0,8(%a2)
    move.l  #{PROMPT_CTRL:#x},(%a2)
    move.l  %a2,%d5
    addi.l  #16,%d5
    move.l  %d5,12(%a2)
    pea     -33(%a6)
    pea     line1
    pea     -28(%a6)
    jsr     {STR_CTOR:#x}
    pea     -34(%a6)
    pea     line2
    pea     -32(%a6)
    jsr     {STR_CTOR:#x}
    pea     1
    jsr     {NEW:#x}
    lea     28(%sp),%sp
    move.l  %d0,-16(%a6)
    lea     {PROMPT_MGR:#x},%a0
    move.l  %a0,-8(%a6)
    lea     on_answer,%a0
    move.l  %a0,-4(%a6)
    clr.l   -(%sp)
    pea     -16(%a6)
    pea     -32(%a6)
    pea     -28(%a6)
    move.l  %d5,-(%sp)
    jsr     {PROMPT:#x}
    move.l  %d5,%a1                     | our instance's vtable: a copy, with
    move.l  (%a1),%d0                   | the key handler ours
    cmpi.l  #{PROMPT_VTABLE:#x},%d0
    bne.s   2f                          | not the class read: leave it stock
    lea     vtable,%a0
    lea     {PROMPT_VTABLE - 8:#x},%a1
    moveq   #{VTABLE_LONGS},%d0
1:  move.l  (%a1)+,(%a0)+
    subq.l  #1,%d0
    bne.s   1b
    lea     vtable+8,%a0
    lea     prompt_keys,%a1
    move.l  %a1,{4 * PROMPT_KEYS_SLOT}(%a0)
    move.l  %d5,%a1
    move.l  %a0,(%a1)
    moveq   #1,%d0
    move.b  %d0,swallow
2:
    pea     -16(%a6)
    jsr     {FUNC_DTOR:#x}
    pea     -32(%a6)
    jsr     {STR_DTOR:#x}
    pea     -28(%a6)
    jsr     {STR_DTOR:#x}
    lea     32(%sp),%sp
    move.l  %a2,-20(%a6)
    pea     {PROMPT_TAG:#x}
    pea     -20(%a6)
    jsr     {SP_GET:#x}
    move.l  %d0,-24(%a6)
    pea     -24(%a6)
    pea     -16(%a6)
    jsr     {SP_MOVE:#x}
    lea     16(%sp),%sp
    jsr     {VIEWS:#x}
    move.l  %d0,-(%sp)
    jsr     {VIEW_STACK:#x}
    addq.l  #4,%sp
    clr.l   -(%sp)
    pea     -16(%a6)
    move.l  %d0,-(%sp)
    jsr     {VIEW_PUSH:#x}
    pea     -12(%a6)
    jsr     {SP_RELEASE:#x}
    pea     -20(%a6)
    jsr     {SP_RELEASE:#x}
    lea     20(%sp),%sp
9:  movem.l (%sp),%d2/%d5/%a2-%a3
    lea     16(%sp),%sp
    unlk    %a6
    rts

| The prompt's answer (functor, yes): YES reloads as FUNC + NO does.
on_answer:
    tst.b   11(%sp)
    beq.s   1f
    move.l  %d2,-(%sp)
    jsr     {UI_STATE:#x}
    move.l  %d0,-(%sp)
    jsr     {PATTERN_OF:#x}
    addq.l  #4,%sp
    move.l  %d0,%d2
    jsr     {SEQUENCER:#x}
    pea     1
    pea     1
    move.l  %d2,-(%sp)
    pea     1                           | 1: from the temporary save
    move.l  %d0,-(%sp)
    jsr     {RELOAD:#x}
    lea     20(%sp),%sp
    move.l  (%sp)+,%d2
1:  rts

| -> %d0 1 when the toggle is on, else 0.
get:
    mvz.b   {FLAG:#x},%d0
    subq.l  #1,%d0
    seq     %d0
    andi.l  #1,%d0
    rts

| (on): the toggle, through the stock setting writer.
set:
    link    %a6,#-4
    moveq   #0,%d0
    tst.b   11(%a6)
    sne     %d0
    andi.l  #1,%d0
    move.b  %d0,-4(%a6)
    pea     1
    pea     -4(%a6)
    pea     {FLAG:#x}
    jsr     {SETTINGS_WRITE:#x}
    lea     12(%sp),%sp
    unlk    %a6
    rts

| name(&string, functor): the item's name (0x40096464).
name:
    link    %a6,#-4
    move.l  %d2,-(%sp)
    move.l  %a0,%d2
    pea     -1(%a6)
    pea     item_name
    move.l  %a0,-(%sp)
    jsr     {STR_CTOR:#x}
    lea     12(%sp),%sp
    move.l  %d2,%d0
    move.l  -8(%a6),%d2
    unlk    %a6
    rts

| press(functor): flip, redraw the view (0x400966d8).
press:
    move.l  %a2,-(%sp)
    move.l  8(%sp),%a0
    move.l  (%a0),%a2
    bsr.w   get
    eori.l  #1,%d0
    move.l  %d0,-(%sp)
    bsr.w   set
    addq.l  #4,%sp
    move.l  (%a2),%a2
    lea     56(%a2),%a2
    move.l  %a2,8(%sp)
    move.l  (%sp)+,%a2
    jmp     {REDRAW:#x}

| value(functor, out, x, y): ON or OFF (0x40097802).
value:
    bsr.w   get
    move.l  12(%sp),4(%sp)
    move.l  %d0,%d1
    lsl.l   #5,%d0
    lsl.l   #2,%d1
    sub.l   %d1,%d0
    add.l   {ONOFF:#x},%d0
    move.l  %d0,8(%sp)
    move.l  16(%sp),%d1
    addi.l  #11,%d1
    move.l  %d1,12(%sp)
    move.l  20(%sp),16(%sp)
    clr.l   20(%sp)
    jmp     {VALUE_DRAW:#x}

| adjust(functor, -, delta): on for a positive turn, off for a negative one
| (0x4009670a), and redraw.
adjust:
    move.l  %a2,-(%sp)
    move.l  %d2,-(%sp)
    move.l  12(%sp),%a0
    move.l  20(%sp),%d2
    move.l  (%a0),%a2
    bsr.w   get
    add.l   %d2,%d0
    bpl.s   1f
    moveq   #0,%d0
1:  moveq   #1,%d1
    cmp.l   %d1,%d0
    ble.s   2f
    move.l  %d1,%d0
2:  move.l  %d0,-(%sp)
    bsr.w   set
    addq.l  #4,%sp
    move.l  (%a2),%a2
    lea     56(%a2),%a2
    move.l  %a2,12(%sp)
    move.l  (%sp)+,%d2
    move.l  (%sp)+,%a2
    jmp     {REDRAW:#x}

| PersonalizeMenuView's constructor, its epilogue, reached by jmp: append the
| twelfth item, then the displaced movem.l and back. %a4 is the view.
menu_hook:
    lea     -64(%sp),%sp
    move.l  %sp,%a3
    pea     1
    jsr     {NEW:#x}
    move.l  %d0,(%a3)
    clr.l   4(%a3)
    lea     {MGR_NAME:#x},%a0
    move.l  %a0,8(%a3)
    lea     name,%a0
    move.l  %a0,12(%a3)
    pea     4
    jsr     {NEW:#x}
    move.l  %d0,%a0
    move.l  %a4,(%a0)
    move.l  %d0,16(%a3)
    clr.l   20(%a3)
    lea     {MGR_PRESS:#x},%a0
    move.l  %a0,24(%a3)
    lea     press,%a0
    move.l  %a0,28(%a3)
    pea     1
    jsr     {NEW:#x}
    move.l  %d0,32(%a3)
    clr.l   36(%a3)
    lea     {MGR_VALUE:#x},%a0
    move.l  %a0,40(%a3)
    lea     value,%a0
    move.l  %a0,44(%a3)
    pea     4
    jsr     {NEW:#x}
    move.l  %d0,%a0
    move.l  %a4,(%a0)
    move.l  %d0,48(%a3)
    clr.l   52(%a3)
    lea     {MGR_ADJUST:#x},%a0
    move.l  %a0,56(%a3)
    lea     adjust,%a0
    move.l  %a0,60(%a3)
    pea     0x54
    jsr     {NEW:#x}
    lea     20(%sp),%sp
    move.l  %d0,%d6
    pea     8
    pea     -1
    pea     48(%a3)
    pea     32(%a3)
    pea     16(%a3)
    move.l  %a3,-(%sp)
    move.l  %d6,-(%sp)
    jsr     {ITEM_BUILD:#x}
    move.l  %d6,-(%sp)
    move.l  %a4,-(%sp)
    jsr     {ITEM_APPEND:#x}
    pea     48(%a3)
    jsr     {FUNC_DTOR:#x}
    pea     32(%a3)
    jsr     {FUNC_DTOR:#x}
    pea     16(%a3)
    jsr     {FUNC_DTOR:#x}
    move.l  %a3,-(%sp)
    jsr     {FUNC_DTOR:#x}
    lea     52(%sp),%sp
    lea     64(%sp),%sp
    movem.l 24(%sp),%d2-%d6/%a2-%a6     | the displaced instruction
    jmp     {MENU_BACK:#x}

item_name:
    .asciz  "{NAME}"
line1:
    .asciz  "{LINE1}"
line2:
    .asciz  "{LINE2}"
swallow:
    .byte   0
    .align  2
vtable:
    .space  {4 * VTABLE_LONGS}
"""

# (va, stock bytes, label): each site becomes `jmp label`, nop-padded.
HOOKS = (
    (KEY_SITE, KEY_DISPLACED, "key_hook"),
    (MENU_SITE, MENU_DISPLACED, "menu_hook"),
)

# Read, not written: the code the hooks rely on.
CONTEXT = (
    (0x4005ED3A, bytes.fromhex("303b4a08"), "key handler: the jump table by code - 1"),
    (0x4005ED5A, bytes.fromhex("0428"), "...NO (code 12) -> 0x4005f16c"),
    (0x4005F184, bytes.fromhex("4eb9401160ac"), "NO: FUNC held?"),
    (0x40112BEE, bytes.fromhex("2f024eb940116040"), "prompt: NO answers on the release (bit 4)"),
    (0x40112B92, bytes.fromhex("4eb940116018"), "prompt keys: the code"),
    (0x4020625C, bytes.fromhex("000000004020623c401b99ba401b9a5c40112b84"),
     "the prompt's vtable: offset-to-top, typeinfo, two destructors, the key handler"),
    (0x402062A8, bytes.fromhex("fffffffc"), "...ends where its second vtable starts"),
    (0x4005F198, bytes.fromhex("4e90"), "NO + FUNC: pressed? (0x401160bc in %a0)"),
    (0x4005F1AC, bytes.fromhex("48780001487800012f00487800012f2a0098"),
     "NO + FUNC: the reload's arguments (sequencer %a2@(152), 1, pattern, 1, 1)"),
    (0x4005F1BE, bytes.fromhex("4eb9400444da"), "NO + FUNC: the reload"),
    (0x4005EF52, bytes.fromhex("7601"), "key handler: handled"),
    (0x401A5E5A, bytes.fromhex("7001"), "menu RELOAD: the prompt's control block counts"),
    (0x401A5E6C, bytes.fromhex("24bc401dd3d4"), "menu RELOAD: the control block's vtable"),
    (0x401A5EBE, bytes.fromhex("203c401a528a"), "menu RELOAD: its answer"),
    (0x401A5EC8, bytes.fromhex("203c401a4358"), "menu RELOAD: its functor's manager"),
    (0x401A5ED4, bytes.fromhex("4eb940112a2e"), "menu RELOAD: the prompt's constructor"),
    (0x401A5EF8, bytes.fromhex("4879401d3b60"), "menu RELOAD: make_shared's tag"),
    (0x401A5F3C, bytes.fromhex("4eb94011d71e"), "menu RELOAD: the push"),
    (0x401A52B6, bytes.fromhex("4eb9400444da"), "menu RELOAD's YES: the same reload"),
    (0x400BB4F8, bytes.fromhex("206f0008"), "the setting writer"),
    (0x400BB866, bytes.fromhex("4a39405cd8a3"), "PAGE AUTOCOPY's getter: a byte of the block"),
    (0x400BB3A2, bytes.fromhex("4eb940133ebc"), "settings defaults: clear 0x52 bytes"),
    (0x40098174, bytes.fromhex("41fae2ee"), "PAGE AUTOCOPY: name 0x40096464"),
    (0x40098178, bytes.fromhex("43faed68"), "...its manager 0x40096ee2"),
    (0x40098622, bytes.fromhex("4e96"), "constructor: the item builder (%fp = 0x401170d8)"),
    (0x4009862C, bytes.fromhex("4e95"), "constructor: the append (%a5 = 0x4011690e)"),
    (0x40098644, bytes.fromhex("4fef00804e75"), "constructor: the rest of its epilogue"),
    (0x40097846, bytes.fromhex("d0b944644d84"), "value text: the ON/OFF strings"),
    (0x40150670, bytes.fromhex("41f9405cd95c"), "the rand seed: the block's neighbour"),
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
OUT = ROOT / "00_Resources/02_Builds/reload-confirm_DN2_1.11.syx"


def assemble_stubs(source: str, base: int) -> tuple[bytes, dict[str, int]]:
    """Assemble once and read each label's address off a trailing table."""
    table = "\n".join(f"    .long {name}" for name in LABELS)
    blob = assemble(source + "\n    .align 2\n" + table + "\n", base=base)
    width = 4 * len(LABELS)
    addrs = struct.unpack(">%dI" % len(LABELS), blob[-width:])
    return blob[:-width], dict(zip(LABELS, addrs))


def check(content: bytes, va: int, want: bytes, why: str) -> None:
    have = bytes(content[va - BASE:va - BASE + len(want)])
    if have != want:
        raise SystemExit(f"{va:#010x}: expected {want.hex()}, found {have.hex()} "
                         f"-- not the image this build was written against ({why})")


def compose(stock: bytes, log=print) -> dict:
    """Apply the build to a stock MAIN OS. -> {content, blob}: the hooked image
    and the code, 4-padded, for a platform `CODE` chunk at CODE_VA."""
    if not available():
        raise SystemExit("no m68k assembler found")
    content = bytearray(stock)
    if any(content[FLAG - BASE:FLAG - BASE + 1]):
        raise SystemExit("the toggle's byte is not zero in the image")

    log("part 1 -- the code this relies on, asserted")
    for va, want, why in CONTEXT:
        check(content, va, want, why)
        log(f"  {va:#010x}  {want.hex():<14}  {why}")

    log(f"part 2 -- the code, from {CODE_VA:#010x}")
    payload, at = assemble_stubs(SOURCE, CODE_VA)
    blob = payload + bytes(-len(payload) % 4)
    log(f"  {len(payload)} bytes: " + ", ".join(f"{k} {v:#010x}" for k, v in at.items()))

    log("part 3 -- the hooks")
    for va, stock_bytes, label in HOOKS:
        check(content, va, stock_bytes, label)
        new = bytes.fromhex("4ef9") + struct.pack(">I", at[label])
        new += bytes.fromhex("4e71") * ((len(stock_bytes) - len(new)) // 2)
        if len(new) != len(stock_bytes):
            raise SystemExit(f"hook at {va:#010x} does not fit {len(stock_bytes)} bytes")
        content[va - BASE:va - BASE + len(new)] = new
        log(f"  {va:#010x}  {stock_bytes.hex()} -> {new.hex()}  jmp {label}")

    return {"content": bytes(content), "blob": blob, "labels": at}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", type=pathlib.Path, default=OUT)
    a = p.parse_args()
    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    if section is None:
        raise SystemExit("image has no MAIN OS section")
    built = compose(section.unpack())
    chunk = platform.area.CodeChunk(CODE_VA, built["blob"]).pack()
    content = platform.join(built["content"], [(platform.area.CODE, chunk)])

    print("part 4 -- repack")
    if a.out.exists():
        raise SystemExit(f"{a.out} exists; builds are never overwritten")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    replacement = compress(section.id, section.dest, content)
    a.out.write_bytes(fwbuild.build(firmware, {MAIN_OS: replacement}))
    print(f"  wrote {a.out} ({a.out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
