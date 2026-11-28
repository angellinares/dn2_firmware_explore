"""SETTINGS > SYSTEM > MODS: the page that lists the mods a build holds, with their versions.

    python scripts/build_mods_page.py --out out/modspage.syx [--os 1.12]

The owner's request (2026-11-15): it is hard to know which firmware an instrument runs. Every
build made with `dnfw mods apply` gets this page, so a user can read the mods and their versions
from the instrument, with no file to keep.

## What the user sees

SYSTEM gets a last entry, MODS. [YES] opens a menu. Its first rows are general: the OS version,
the build's name and the commit the tool was at. Then one row for each mod: its name on the
left, its version on the right. [UP] and [DOWN] move, [NO] goes back. [YES] and a turn on a row do nothing.

## How

Stock builds each menu of SETTINGS once, at start-up, and keeps it. `SystemSettings`' constructor
(`0x4010b96e`) appends its entries one block each, and ends with the epilogue at `0x4010bde4`.
One hook there, reached by `jmp`, does three things with stock's own routines, then runs the
displaced `movem.l` and goes back:

1. It builds a menu: `new(0x1e8)`, then the menu base's constructor `0x4011b600` with the title
   MODS, as the SYSTEM constructor calls it for itself (`0x4010b9b2`).
2. It appends one value item for each row of the table: four `std::function`s and
   `0x401170d8(item, &name, &press, &value, &adjust, -1, 8)`, then `0x4011690e(menu, item)`, as
   `scripts/build_personalize_toggle.py` does for a PERSONALIZE item. Each function's functor is
   4 bytes and holds the row's address, so one `name` and one `value` routine serve every row.
   PAGE AUTOCOPY's press manager (`0x40096f34`) copies and frees a 4-byte functor, so it is right
   for all four. `value` draws the text as MASTER TUNE draws its number (`0x4010b8f0`): the text
   routine `0x40115668` with the font `0x402941d0`, at x + 78 and y + 2.
3. It keeps the menu and appends the MODS entry. The keeping is what the SYSTEM constructor does
   for its own sub-menus (`0x4010ba88`): `0x4011b74e(parent, menu + 56)` gives a shared pointer,
   `0x401a54c8` stores it, `0x401880cc` releases the temporary. The entry is an action item
   (`0x40117224(item, text, &press, icon, &empty)`), and its press shows the kept menu as
   SETTINGS shows SYSTEM (`0x4009fa36`): copy the pointer (`0x4019e76e`), `0x4011bc26(parent,
   &pointer)`, release.

The menu's art is SYSTEM's own (`0x446447ec`), and the entry borrows OS UPGRADE's icon
(`0x446464ec`). Both are objects stock already holds; the build ships no image.

## The table

The code ends at `table`. The rows are data that `dnfw.mods.modspage` writes after the code when
it applies the page: a 32-bit count, then 32 bytes for each row, the name in 20 (NUL-ended) and
the value in 12 (NUL-ended, empty for a row with a name only).

Checked in the emulator from reset on OS 1.11 (`scripts/emu_mods_page.py`).
"""

from __future__ import annotations

import argparse
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dnfw import osport
from dnfw.checkout import resources_dir
from dnfw.cli.files import read_image
from dnfw.container.section import compress
from dnfw.firmware import build as fwbuild
from dnfw.firmware.load import load
from dnfw.mods import platform
from dnfw.patch.assemble import assemble, available

MAIN_OS = 3
BASE = 0x40000400

# RAM above BSS, given to the page: between directjump's chunk (0x46790000, 1,196 B) and
# arpmodes' RAM (0x467a0000).
CODE_VA = 0x46798000

MENU_SITE = 0x4010BDE4          # SystemSettings' constructor, its epilogue
MENU_BACK = 0x4010BDEA

NEW = 0x40120264                # operator new(size)
STR_CTOR = 0x401CE69E           # std::string(this, const char *, const alloc &)
STR_DTOR = 0x401CCBEE           # its destructor
FUNC_DTOR = 0x40188086          # std::function destructor(this)
ITEM_BUILD = 0x401170D8         # a value item: (item, &name, &press, &value, &adjust, -1, 8)
ITEM_ACTION = 0x40117224        # an action item: (item, text, &press, icon, &empty)
ITEM_APPEND = 0x4011690E        # (menu, item)
MGR4 = 0x40096F34               # PAGE AUTOCOPY's press manager: a 4-byte functor
FONT = 0x402941D0               # MASTER TUNE's value font
TEXT_DRAW = 0x40115668          # (out, font, x, y, 2, 0, template, format, ...)
MENU_BASE = 0x4011B600          # the menu base's constructor: (menu, class name, 1, &title, art, 1)
ADOPT = 0x4011B74E              # (parent, menu + 56), %a0 = &out: a shared pointer to the menu
SP_ASSIGN = 0x401A54C8          # (&kept, &pointer)
SP_RELEASE = 0x401880CC         # (&pointer's count)
SP_COPY = 0x4019E76E            # (&out, &kept)
SHOW = 0x4011BC26               # (parent, &pointer): show the menu
VIEW_SIZE = 0x1E8               # the size SETTINGS allocates for SYSTEM
MENU_ART = 0x446447EC           # SYSTEM's art
ENTRY_ICON = 0x446464EC         # OS UPGRADE's icon

ROW, NAME_BYTES, VALUE_BYTES = 32, 20, 12
TITLE = "MODS"
# The name a mod's row shows, 12 characters at most: a longer one runs into the value's column.
# A mod with none shows its id. The generator writes the list into the spec, for Python and the site.
MENU_NAMES = {
    "arpmodes": "ARP MODES",
    "arpplocks": "ARP P-LOCKS",
    "arpscale": "ARP SCALE",
    "bootscreen": "BOOT SCREEN",
    "degreetranspose": "DEGREE TRANS",
    "directjump": "DIRECT JUMP",
    "fxmod": "FX MOD",
    "layermidi": "LAYER MIDI",
    "lfo4": "LFO 4",
    "lfohold": "LFO HOLD",
    "lfolength": "LFO LENGTH",
    "lfowaves": "LFO WAVES",
    "midiarp": "MIDI ARP",
    "moddest": "MOD DEST",
    "pslide": "PARAM SLIDES",
    "reloadconfirm": "RELOAD CONF",
    "sendloop": "SEND LOOP",
    "songguard": "SONG GUARD",
    "transients": "TRANSIENTS",
    "usbprobe": "USB PROBE",
    "waverider": "WAVERIDER",
}
LABELS = ("menu_hook", "mods_open", "name", "value", "noop", "kept", "table")

# Read, not written: the stock code the page relies on.
CONTEXT = (
    (0x4010B96E, bytes.fromhex("4fefff9048d77cfc"), "SystemSettings' constructor"),
    (0x4010B9B2, bytes.fromhex("4eb94011b600"), "...its call of the menu base's constructor"),
    (0x4010BA8E, bytes.fromhex("49f94011b74e4e94"), "...how it keeps a sub-menu"),
    (0x4010BDEA, bytes.fromhex("4fef00884e75"), "...the rest of its epilogue"),
    (0x4010B90E, bytes.fromhex("4879402941d02f024eb940115668"), "MASTER TUNE: its value's font and text routine"),
    (0x4009FA4A, bytes.fromhex("41e801d82f082f024eb94019e76e2f022f124eb94011bc26"),
     "SETTINGS: how the SYSTEM entry shows its menu"),
    (0x40120264, bytes.fromhex("4ef94011ffe8"), "operator new"),
    (0x401CE69E, bytes.fromhex("4e5600002f02"), "the string constructor"),
    (0x401CCBEE, bytes.fromhex("4e56fffc206e"), "the string destructor"),
    (0x40188086, bytes.fromhex("206f00042268"), "the function destructor"),
    (0x401170D8, bytes.fromhex("2f0b70ff2f0a"), "the value item's builder"),
    (0x40117224, bytes.fromhex("4fefffb048d7"), "the action item's builder"),
    (0x4011690E, bytes.fromhex("4e56fff82f0a"), "the append"),
    (0x40096F34, bytes.fromhex("2f0b72012f0a"), "PAGE AUTOCOPY's press manager"),
    (0x40115668, bytes.fromhex("4e56ff44202e"), "the text routine"),
    (0x4011B600, bytes.fromhex("4fefffe048d7"), "the menu base's constructor"),
    (0x4011B74E, bytes.fromhex("4fefffdc48d7"), "the shared pointer to a menu"),
    (0x401A54C8, bytes.fromhex("518f2f0e2f0a"), "the shared pointer's assignment"),
    (0x401880CC, bytes.fromhex("2f0a206f0008"), "the shared pointer's release"),
    (0x4019E76E, bytes.fromhex("206f0004226f"), "the shared pointer's copy"),
    (0x4011BC26, bytes.fromhex("4e56fff42f0b"), "the menu's show"),
)

# (va, stock bytes, label): each site becomes `jmp label`, nop-padded.
HOOKS = (
    (MENU_SITE, bytes.fromhex("4cef7cfc0018"), "menu_hook"),
)


def functor(offset: int, invoker: str) -> str:
    """Assembly: the std::function at OFFSET(%a3), its 4-byte functor the row in %a5"""
    return f"""    pea     4
    jsr     {{NEW:#x}}
    addq.l  #4,%sp
    move.l  %d0,%a0
    move.l  %a5,(%a0)
    move.l  %d0,{offset}(%a3)
    clr.l   {offset + 4}(%a3)
    lea     {{MGR4:#x}},%a0
    move.l  %a0,{offset + 8}(%a3)
    lea     {invoker},%a0
    move.l  %a0,{offset + 12}(%a3)
"""


# The frame at %a3: 0..63 a row's four functions, 64 an allocator, 68..95 the title,
# 96..103 a shared pointer, 104..119 the entry's press, 120..135 its empty function.
TEMPLATE = """| SystemSettings' constructor, its epilogue, reached by jmp. %a2 is the SYSTEM menu.
menu_hook:
    lea     -144(%sp),%sp
    move.l  %sp,%a3
    | the MODS menu: the menu base, with the title
    pea     64(%a3)
    pea     title
    pea     68(%a3)
    jsr     {STR_CTOR:#x}
    pea     {VIEW_SIZE:#x}
    jsr     {NEW:#x}
    move.l  %d0,%a4
    pea     1
    pea     {MENU_ART:#x}
    pea     68(%a3)
    pea     1
    pea     class_name
    move.l  %a4,-(%sp)
    jsr     {MENU_BASE:#x}
    pea     68(%a3)
    jsr     {STR_DTOR:#x}
    lea     44(%sp),%sp
    | one value item for each row of the table
    lea     table,%a5
    move.l  (%a5)+,%d7
    beq.w   2f
1:
""" + functor(0, "name") + functor(16, "noop") + functor(32, "value") + functor(48, "noop") + """    pea     0x54
    jsr     {NEW:#x}
    addq.l  #4,%sp
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
    lea     {ROW}(%a5),%a5
    subq.l  #1,%d7
    bne.w   1b
2:
    | keep the menu, as the SYSTEM constructor keeps its own sub-menus
    pea     56(%a4)
    move.l  %a2,-(%sp)
    lea     96(%a3),%a0
    jsr     {ADOPT:#x}
    pea     96(%a3)
    pea     kept
    jsr     {SP_ASSIGN:#x}
    pea     100(%a3)
    jsr     {SP_RELEASE:#x}
    lea     20(%sp),%sp
    | the MODS entry of SYSTEM: its press captures the SYSTEM menu
    pea     4
    jsr     {NEW:#x}
    addq.l  #4,%sp
    move.l  %d0,%a0
    move.l  %a2,(%a0)
    move.l  %d0,104(%a3)
    clr.l   108(%a3)
    lea     {MGR4:#x},%a0
    move.l  %a0,112(%a3)
    lea     mods_open,%a0
    move.l  %a0,116(%a3)
    clr.l   120(%a3)
    clr.l   124(%a3)
    clr.l   128(%a3)
    clr.l   132(%a3)
    pea     0x54
    jsr     {NEW:#x}
    addq.l  #4,%sp
    move.l  %d0,%d6
    pea     120(%a3)
    pea     {ENTRY_ICON:#x}
    pea     104(%a3)
    pea     title
    move.l  %d6,-(%sp)
    jsr     {ITEM_ACTION:#x}
    move.l  %d6,-(%sp)
    move.l  %a2,-(%sp)
    jsr     {ITEM_APPEND:#x}
    pea     120(%a3)
    jsr     {FUNC_DTOR:#x}
    pea     104(%a3)
    jsr     {FUNC_DTOR:#x}
    lea     36(%sp),%sp
    lea     144(%sp),%sp
    movem.l 24(%sp),%d2-%d7/%a2-%a6     | the displaced instruction
    jmp     {MENU_BACK:#x}

| The entry's press(functor): show the kept menu, as SETTINGS shows SYSTEM (0x4009fa36).
mods_open:
    link    %a6,#-8
    move.l  %a2,-(%sp)
    move.l  8(%a6),%a0
    move.l  (%a0),%a2
    pea     kept
    pea     -8(%a6)
    jsr     {SP_COPY:#x}
    pea     -8(%a6)
    move.l  (%a2),-(%sp)
    jsr     {SHOW:#x}
    pea     -4(%a6)
    jsr     {SP_RELEASE:#x}
    lea     20(%sp),%sp
    move.l  (%sp)+,%a2
    unlk    %a6
    rts

| name(&string in %a0, functor): the row's name.
name:
    link    %a6,#-4
    move.l  %d2,-(%sp)
    move.l  %a0,%d2
    move.l  8(%a6),%a1
    move.l  (%a1),%a1
    move.l  (%a1),%a1                   | the row
    pea     -1(%a6)
    move.l  %a1,-(%sp)
    move.l  %a0,-(%sp)
    jsr     {STR_CTOR:#x}
    lea     12(%sp),%sp
    move.l  %d2,%d0
    move.l  -8(%a6),%d2
    unlk    %a6
    rts

| value(functor, -, out, x, y): the row's value, as MASTER TUNE draws its number (0x4010b8f0).
value:
    move.l  4(%sp),%a0
    move.l  (%a0),%a0
    move.l  (%a0),%a0                   | the row
    lea     {NAME_BYTES}(%a0),%a0       | its value
    move.l  12(%sp),%d0
    move.l  16(%sp),%d1
    move.l  20(%sp),%a1
    move.l  %a0,-(%sp)                  | the text is its own format: `modspage` allows no %
    move.l  %a0,-(%sp)                  | and its own width template
    clr.l   -(%sp)
    pea     2
    pea     2(%a1)
    addi.l  #78,%d1
    move.l  %d1,-(%sp)
    pea     {FONT:#x}
    move.l  %d0,-(%sp)
    jsr     {TEXT_DRAW:#x}
    lea     32(%sp),%sp
    rts

| A row's press and adjust: nothing.
noop:
    rts

title:
    .asciz  "{TITLE}"
class_name:
    .asciz  "ModsMenu"
    .balign 4
kept:
    .long   0, 0
| The rows, written after the code by `dnfw.mods.modspage`: a count, then {ROW} bytes each.
table:
"""


def source(os: str = "1.11") -> str:
    """The page's code for OS (issue #382): every stock address through `dnfw.osport`"""
    return osport.render(TEMPLATE, globals(), os)


SOURCE = source()            # OS 1.11's

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCKS = {"1.11": "00_Firmware/Digitone_II_OS1.11_dist.zip", "1.12": "00_Firmware/Digitone_II_OS1.12.syx"}


def assemble_stubs(source: str, base: int) -> tuple[bytes, dict[str, int]]:
    """Assemble once and read each label's address off a trailing table."""
    table = "\n".join(f"    .long {name}" for name in LABELS)
    blob = assemble(source + "\n" + table + "\n", base=base)
    width = 4 * len(LABELS)
    addrs = struct.unpack(">%dI" % len(LABELS), blob[-width:])
    return blob[:-width], dict(zip(LABELS, addrs))


def compose(stock: bytes, log=print, os: str = "1.11") -> dict:
    """Apply the page's hook to a stock MAIN OS. -> {content, blob, labels}: the hooked image and
    the code, which ends where the rows' table starts.

    OS is STOCK's version (issue #382): every guard and hook site goes through
    `dnfw.osport.site`, which refuses one whose bytes changed other than by a moved address."""
    if not available():
        raise SystemExit("no m68k assembler found")
    content = bytearray(stock)

    log("part 1 -- the code this relies on, asserted")
    for va, want, why in CONTEXT:
        try:
            at, have = osport.site(os, va, want, content, BASE)
        except osport.NotPorted as exc:
            raise SystemExit(f"{why}: {exc}") from None
        log(f"  {at:#010x}  {have.hex():<14}  {why}")

    log(f"part 2 -- the code, from {CODE_VA:#010x}")
    blob, at = assemble_stubs(source(os), CODE_VA)
    if at["table"] != CODE_VA + len(blob) or len(blob) % 4:
        raise SystemExit("the code does not end at its table, 4-aligned")
    log(f"  {len(blob)} bytes: " + ", ".join(f"{k} {v:#010x}" for k, v in at.items()))

    log("part 3 -- the hook")
    for va, stock_bytes, label in HOOKS:
        try:
            va, stock_bytes = osport.site(os, va, stock_bytes, content, BASE)
        except osport.NotPorted as exc:
            raise SystemExit(f"hook {label}: {exc}") from None
        new = bytes.fromhex("4ef9") + struct.pack(">I", at[label])
        new += bytes.fromhex("4e71") * ((len(stock_bytes) - len(new)) // 2)
        if len(new) != len(stock_bytes):
            raise SystemExit(f"hook at {va:#010x} does not fit {len(stock_bytes)} bytes")
        content[va - BASE:va - BASE + len(new)] = new
        log(f"  {va:#010x}  {stock_bytes.hex()} -> {new.hex()}  jmp {label}")

    return {"content": bytes(content), "blob": blob, "labels": at}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", type=pathlib.Path, required=True)
    p.add_argument("--os", default="1.11", choices=sorted(STOCKS))
    a = p.parse_args()
    firmware = load(read_image(resources_dir(ROOT) / STOCKS[a.os]))
    section = firmware.container.find(MAIN_OS)
    built = compose(section.unpack(), os=a.os)
    from dnfw.mods import modspage  # noqa: PLC0415  (it reads the generated code)
    rows = [("EXAMPLE MOD", "1.0.0"), ("OS", a.os)]
    chunk = platform.area.CodeChunk(CODE_VA, built["blob"] + modspage.table(rows)).pack()
    content = platform.join(built["content"], [(platform.area.CODE, chunk)])
    if a.out.exists():
        raise SystemExit(f"{a.out} exists; builds are never overwritten")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_bytes(fwbuild.build(firmware, {MAIN_OS: compress(section.id, section.dest, content)}))
    print(f"  wrote {a.out} ({a.out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
