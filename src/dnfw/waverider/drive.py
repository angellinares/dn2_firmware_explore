"""Waverider's +Drive chunk: the store's route, the table loader and the pool, as one
platform `CODE` chunk, and the two hooks that reach it.

One subject: what the chunk is made of and where it hooks in; `coldfire.compose`
applies the hooks, and `compile_drive` (here) builds the bytes.

- **The sources:** `csrc/wrstore/store.c` (reading the store), `route.c` (DNX lists,
  reads, writes and deletes tables through `/waverider`, `docs/data-api-routes.md`),
  `csrc/waverider/loader.c` (chunks to the DSP through the frame exchange,
  `docs/drive-load-command.md`) and `pool.c` (the store's tables into the DSP's pool).
  Linked at `LOAD`; `pool.c` puts the chunk's head (`wr_drive_head`, pool.h) first, so
  the page, linked in the other chunk, finds the poll and the pool without either link
  knowing the other's addresses.
- **The hooks:**
  - `ROUTE_SITE` (0x4002bb70), in the Data API's start-up builder 0x4002b8c8 right
    after it adds the kits handler: `moveq #1,%d0 ; move.b %d0,0x4059cd20` becomes
    `jsr wr_add ; nop`, and wr_add adds our handler and then sets that flag;
  - `FRAME_SITE` (0x40025e82), in the audio ISR just before the stock send: `move.l
    0x402876f8,%d0` becomes `jmp wr_frame_hook`, which sends the frame or a chunk
    (wr_frame_src) and goes back to 0x40025eb2.
  - The UI pass needs no hook: the page's `wr_poll`, already on the UI loop, calls
    the head's poll.
- **RAM:** the chunk, and the pool's display spans at `SPANS` (pool.h).

For 1.12 (`os-112-support`): each site is recorded with its shape in `GUARDS`.
"""

from __future__ import annotations

import pathlib

LOAD = 0x467F0000                 # above reloadconfirm's chunk and the route test's, below lfo4's C
LIMIT = 0x46800000
SPANS = 0x46A00000                # pool.h: WR_POOL_SPANS
SPANS_BYTES = 127 * 16 * 2 * 96
ROOT = pathlib.Path(__file__).resolve().parents[3]
SOURCES = (ROOT / "csrc/waverider/pool.c", ROOT / "csrc/waverider/loader.c",
           ROOT / "csrc/waverider/events.c",
           ROOT / "csrc/wrstore/store.c", ROOT / "csrc/wrstore/route.c")
ENTRIES = ["wr_drive_head", "wr_drive_poll", "wr_add", "wr_root_entry", "wr_list_invoker",
           "wr_register", "wr_nop", "wr_frame_hook", "wr_frame_src", "wr_clear_type"]
STATUS = ("wr_pool", "wr_load", "wr_store", "wr_route", "wr_write", "wr_events")   # what the probe PEEKs
CLEAR_SITE = 0x40071EB6           # CLEAR TRK PRESET's jsr to the machine-type getter (events.c)

ROUTE_SITE = 0x4002BB70
ROUTE_STOCK = bytes.fromhex("700113c04059cd20")     # moveq #1,%d0 ; move.b %d0,0x4059cd20
FRAME_SITE = 0x40025E82
FRAME_STOCK = bytes.fromhex("2039402876f8")         # move.l 0x402876f8,%d0
# the code the hooks rely on, read and never written (docs/data-api-routes.md,
# docs/drive-load-command.md)
GUARDS = (
    (0x4002BB4C, "48794059cd24", "the builder passes the registry to the add, for the kits"),
    (0x4002BB78, "4cd73cfc203c4059cd24", "after the route hook: restore, return the registry"),
    (0x400EAD92, "2f0b2f0a266f0010246f000c", "the registry's add(registry, &unique_ptr)"),
    (0x4014BE0E, "4fefffd848d73cfc", "XXH32"),
    (0x40025E88, "6620" "4879800053a4" "48780abc" "487980005e60" "48780a80" "4eb9400cf7be" "4fef0010" "6008",
     "after the frame hook: the skip test and the stock send(0xa80, 0x80005e60, 0xabc, "
     "0x800053a4), as wr_frame_hook repeats it"),
    (0x40025EAA, "538023c0402876f8", "the skip counter's count-down, then 0x40025eb2"),
)


class DriveError(ValueError):
    pass


def compile_drive(build, raw_track: int) -> tuple[bytes, dict[str, int]]:
    """BUILD(sources, base=, entries=, defines=) -> a cbuild link; RAW_TRACK the shim that
    answers a track's real machine type; -> (the chunk, its symbols)."""
    linked = build(list(SOURCES), base=LOAD, entries=ENTRIES, defines={"WR_RAW_TRACK": f"{raw_track:#x}"})
    if linked.bss:
        raise DriveError(f"the drive chunk has {linked.bss} bytes of BSS; nothing zeroes it")
    if linked.symbols["wr_drive_head"] != LOAD:
        raise DriveError(f"wr_drive_head is at {linked.symbols['wr_drive_head']:#x}, not the chunk's start")
    image = linked.image + bytes(-len(linked.image) % 4)
    if LOAD + len(image) > LIMIT:
        raise DriveError(f"the drive chunk ends at {LOAD + len(image):#x}, past {LIMIT:#x}")
    return image, dict(linked.symbols)


def hooks(symbols: dict[str, int]) -> list[tuple[int, bytes, bytes, str]]:
    """-> (va, new, stock, what) for each hook."""
    return [
        (CLEAR_SITE, bytes.fromhex("4eb9") + symbols["wr_clear_type"].to_bytes(4, "big"),
         bytes.fromhex("4eb94004b7f2"), "CLEAR TRK PRESET (TRK + PLAY): the real machine type "
         "(the cleared track stays Waverider), and the clear counted for the page"),
        (ROUTE_SITE, bytes.fromhex("4eb9") + symbols["wr_add"].to_bytes(4, "big") + bytes.fromhex("4e71"),
         ROUTE_STOCK, "the Data API's start-up builder: add the /waverider handler (wr_add), "
                      "then set the builder's flag as stock does"),
        (FRAME_SITE, bytes.fromhex("4ef9") + symbols["wr_frame_hook"].to_bytes(4, "big"),
         FRAME_STOCK, "the audio ISR, before the stock send: the frame or a table chunk "
                      "(wr_frame_hook), then on at 0x40025eb2"),
    ]
