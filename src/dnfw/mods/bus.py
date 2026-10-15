"""The hook bus: the sites and counts the platform owns, so two mods can share them.

Two mods that patch the same stock instruction cannot both apply: the second one
finds the first one's jump where it checks for stock bytes. elekloader's core
solves this for the Digitone mk1 (`docs/references.md`): the core owns each shared
site, and mods subscribe to it. This module is that idea for the Digitone II, with
elekloader's names, so that it can become a `core-dn2`.

## Events

The platform patches an event's site once, with a jump to its dispatcher. The
dispatcher calls each handler that a mod subscribed, in order (lower `order` first,
then the lower handler address). Handlers use the C calling convention: the
arguments on the stack, d0-d1/a0-a1 free, the result in d0.

| event | site | handler |
|---|---|---|
| `ev_param_slot` | `0x400dc02a`, `param_set_slot_to_id(slot, type, filter)` | `int f(slot, type, filter)`; nonzero: taken, the parameter entry for the slot |

When no handler takes it, the dispatcher runs the stock instructions it displaced
and goes on in the stock routine. fxmod answers the FX slots 101..124 there, and
Waverider answers its page 3 and page 5 slots on a Waverider track.

## Counts

Some stock limits are one number checked in many places: the parameter table's
size (320 records, 53 bounds) and the number of machine types (5, six bounds). A
mod that adds parameters or machines does not write those bounds. It adds to the
count (`contribute`), and the platform writes every bound for the total.

| count | stock | bounds |
|---|---|---|
| `PARM` | 320 parameter records | the 53 `cmpi.l #320` / `#321` of `dnfw.patch.paramtable.bound_sites` |
| `MACH` | 5 machine types | the five `moveq #4` of the name and attribute rows, and the stored-sound LOAD's `moveq #6` |

Only one mod may add to each count. A mod that adds parameters must also give the
records a place (lfo4 moves the table), and a mod that adds a machine must give
it its name and attribute rows (Waverider moves them). shortcut: one contributor
per count; a second needs a shared record table, like elekloader's `core_params`.

## Order does not matter

`detach` (from `platform.split`) puts every owned byte back to stock and removes
the dispatchers, so each mod checks and edits a stock image. `attach` (from
`platform.join`) writes them again for every mod in the area. An owned byte that a
mod's hook displaced is found in the copy that mod recorded (`platform.displace`),
so lfo4's bound inside Waverider's group-getter hook, and Waverider's machine bound
inside lfo4's stored-sound LOAD hook, are written wherever they run.

A set of mods that subscribes to nothing and adds nothing builds byte for byte as
before. The dispatcher's code is assembled once (`scripts/gen_platform_code.py`,
the `bus` entry of `platform_code.json`), so the browser applies the same bytes.
"""

from __future__ import annotations

import struct

from . import Extent, ModError
from ..patch import area

SECTION, BASE = 3, 0x40000400
EVNT = b"EVNT"      # a mod's subscriptions: (event, order, handler), 12 bytes each
ADDS = b"ADDS"      # a mod's contributions: (count, amount), 8 bytes each

# Where the dispatchers run. Region A, clear of every mod (docs/mod-memory-regions.md).
BUS_VA = 0x46E00000
TABLE_SLOTS = 8     # per event: up to seven handlers, then 0

# The dispatcher, assembled at BUS_VA by scripts/gen_platform_code.py. One table
# per event comes first, at a fixed place; the code follows.
SOURCE = """
| ev_param_slot's handlers, in order, then 0. The platform fills it at apply time.
param_slot_table:
    .space  32
| param_set_slot_to_id(slot, type, filter), from 0x400dc02a by jmp: each handler in
| turn, int f(slot, type, filter). The first nonzero answer is the answer. None: the
| three stock instructions the jmp displaced, then on at 0x400dc032.
    .globl  ev_param_slot
ev_param_slot:
    move.l  %a2,%sp@-
    lea     param_slot_table,%a2
1:  move.l  %a2@+,%d0
    beq.s   9f
    move.l  %sp@(16),%sp@-          | filter
    move.l  %sp@(16),%sp@-          | type
    move.l  %sp@(16),%sp@-          | slot
    movea.l %d0,%a0
    jsr     %a0@
    lea     %sp@(12),%sp
    tst.l   %d0
    beq.s   1b
    movea.l %sp@+,%a2
    rts
9:  movea.l %sp@+,%a2
    move.l  %d2,%sp@-
    moveq   #100,%d1
    movea.l %sp@(8),%a0
    jmp     0x400dc032
"""

# The events: their sites, the stock bytes the jump replaces, and the table's place.
EVENTS = {
    b"PSLT": {"name": "ev_param_slot", "site": 0x400DC02A, "stock": "2f027264206f0008",
              "table": 0, "entry": "ev_param_slot",
              "what": "param_set_slot_to_id -> the bus's ev_param_slot"},
}

# The counts: the stock value, and the bounds that spell it (va, width, stock value).
# PARM's 53 are found in the stock image by gen_platform_code.py (paramtable.bound_sites).
MACHINE_BOUNDS = ((0x400DC15D, 1, 4, "the attribute rows' byte getter: moveq #4"),
                  (0x400DC19D, 1, 4, "the permission test: moveq #4"),
                  (0x400DC333, 1, 4, "the long-name getter: moveq #4"),
                  (0x400DC359, 1, 4, "the short-name getter: moveq #4"),
                  (0x400DC37F, 1, 4, "the third name column: moveq #4"),
                  (0x400DD287, 1, 6, "the stored-sound LOAD: moveq #6"))
COUNT_NAMES = {b"PARM": "parameter records", b"MACH": "machine types"}


def subscribe(event: bytes, handler: int, order: int = 50) -> tuple[bytes, bytes]:
    """The chunk that subscribes HANDLER (a run-time address) to EVENT."""
    if event not in EVENTS:
        raise ModError(f"the bus has no event {event.decode()}")
    return EVNT, struct.pack(">4sII", event, order, handler)


def contribute(count: bytes, amount: int) -> tuple[bytes, bytes]:
    """The chunk that adds AMOUNT to COUNT."""
    if count not in COUNT_NAMES:
        raise ModError(f"the bus has no count {count.decode()}")
    return ADDS, struct.pack(">4sI", count, amount)


def _records(chunks, cid: bytes, fmt: str) -> list[tuple]:
    size = struct.calcsize(fmt)
    return [struct.unpack_from(fmt, data, at)
            for c, data in chunks if c == cid for at in range(0, len(data), size)]


def totals(chunks) -> dict[bytes, int]:
    """-> {count: amount}, refusing a count that two mods add to."""
    out: dict[bytes, int] = {}
    for count, amount in _records(chunks, ADDS, ">4sI"):
        if count in out:
            raise ModError(f"two mods add {COUNT_NAMES.get(count, count.decode())}; "
                           "the platform takes one mod's for now")
        out[count] = amount
    return out


def handlers(chunks) -> dict[bytes, list[int]]:
    """-> {event: [handler, ...]} in the order the dispatcher calls them."""
    out: dict[bytes, list[tuple[int, int]]] = {}
    for event, order, handler in _records(chunks, EVNT, ">4sII"):
        out.setdefault(event, []).append((order, handler))
    return {e: [h for _, h in sorted(subs)] for e, subs in out.items()}


def bounds(spec: dict, count: bytes) -> list[tuple[int, int, int]]:
    """-> [(va, width, stock value)] for COUNT, from the generated spec."""
    if count == b"MACH":
        return [(va, w, v) for va, w, v, _ in MACHINE_BOUNDS]
    return [tuple(s) for s in spec["counts"][count.decode()]]


def _hook(spec: dict, event: bytes) -> bytes:
    entry = spec["bus"]["symbols"][EVENTS[event]["entry"]]
    return b"\x4e\xf9" + struct.pack(">I", entry) + b"\x4e\x71"


def _stock(event: bytes) -> bytes:
    return bytes.fromhex(EVENTS[event]["stock"])


def detach(write, content: bytearray, chunks: list, spec: dict) -> list:
    """Put every owned byte back to stock; -> CHUNKS without the dispatchers' chunk.
    WRITE is `platform.write`, which finds a byte another mod's hook displaced."""
    for count, amount in totals(chunks).items():
        for va, width, value in bounds(spec, count):
            write(content, chunks, va, (value + amount).to_bytes(width, "big"),
                  value.to_bytes(width, "big"), f"the {COUNT_NAMES[count]} count")
    for event in handlers(chunks):
        write(content, chunks, EVENTS[event]["site"], _hook(spec, event), _stock(event),
              EVENTS[event]["name"])
    return [(c, d) for c, d in chunks
            if not (c == area.CODE and area.CodeChunk.unpack(d).load == BUS_VA)]


def attach(write, content: bytearray, chunks: list, spec: dict) -> list:
    """Write every count and hook every subscribed event; -> CHUNKS with the dispatchers."""
    for count, amount in totals(chunks).items():
        for va, width, value in bounds(spec, count):
            write(content, chunks, va, value.to_bytes(width, "big"),
                  (value + amount).to_bytes(width, "big"), f"the {COUNT_NAMES[count]} count")
    subs = handlers(chunks)
    if not subs:
        return chunks
    image = bytearray.fromhex(spec["bus"]["code"])
    for event, found in subs.items():
        if len(found) >= TABLE_SLOTS:
            raise ModError(f"{len(found)} mods subscribe to {EVENTS[event]['name']}; "
                           f"the bus takes {TABLE_SLOTS - 1}")
        at = EVENTS[event]["table"]
        image[at:at + 4 * len(found)] = b"".join(struct.pack(">I", h) for h in found)
        write(content, chunks, EVENTS[event]["site"], _stock(event), _hook(spec, event),
              EVENTS[event]["name"])
    return chunks + [(area.CODE, area.CodeChunk(BUS_VA, bytes(image)).pack())]


def extents(spec: dict) -> list[Extent]:
    """The bytes the bus owns. Every mod on the platform declares them, so a mod that
    writes one of them by itself conflicts with all of them."""
    out = [Extent(SECTION, e["site"] - BASE, len(e["stock"]) // 2, e["what"], "platform")
           for e in EVENTS.values()]
    for count in COUNT_NAMES:
        out += [Extent(SECTION, va - BASE, w, f"the {COUNT_NAMES[count]} count", "platform")
                for va, w, _ in bounds(spec, count)]
    return out
