"""Does the hook bus answer every slot lookup as the code it replaces did?

    python scripts/emu_bus_slots.py BUS.syx --before WAVERIDER_OLD.syx --fx FXMOD_OLD.syx

`param_set_slot_to_id(slot, type, filter)` at `0x400dc02a` is the platform's event
`ev_param_slot` (`dnfw.mods.bus`) when a mod subscribes to it. This restores the
booted snapshot (`ui1200M`), installs each build as its loader would (the edits in
MAIN OS, then every chunk at its run-time address), and calls the routine directly
for slots 0..130, types 0..6 and filters 0..6: once with the active track as the
snapshot has it, and once with that track's sound set to machine type 5, so that
Waverider's handler answers.

The verdict compares the bus build with the builds it replaces: every answer must be
the old Waverider build's (`--before`), except the FX slots 101..124, which must be
the old fxmod build's (`--fx`). Stock is run as the control: the two old builds must
each differ from it, or the comparison proves nothing.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from emulib import paths                                     # noqa: E402
from emulib.image import differences                         # noqa: E402
from emulib.machine import Machine                           # noqa: E402

sys.path.insert(0, str(paths.ROOT / "src"))
from dnfw.firmware.load import load                          # noqa: E402
from dnfw.mods import platform                               # noqa: E402

SITE = 0x400DC02A
SLOTS, TYPES, FILTERS = range(131), range(7), range(7)
FX = range(101, 125)
WAVERIDER = 5                      # the machine type a Waverider sound stores
# dnfw.waverider.pages (not imported: it needs numpy, which the emulator's venv lacks)
ACTIVE_TRACK = 0x42431A6C          # byte: the UI's active track, 0..15
KIT_POINTER = 0x800052A0           # the live kit; sound t at + 52 + 1163 t
SOUND_BASE, SOUND_STRIDE, SOUND_TYPE = 52, 1163, 0xDE


def main_os(path: pathlib.Path) -> bytes:
    """MAIN OS from a .syx (or a .zip), or a section 3 dump as it is."""
    if path.suffix == ".bin":
        return path.read_bytes()
    from dnfw.cli.files import read_image
    return load(read_image(path)).container.find(3).unpack()


def answers(m: Machine, stock: bytes, build: bytes | None) -> dict:
    """{(waverider_track, slot, type, filter): answer} for BUILD installed in M."""
    if build is not None:
        m.apply(differences(stock, build[:platform.STOCK_LENGTH]))
        for va, data in platform.runtime(build):
            m.write(va, data)
        m.flush()
    track = m.read(ACTIVE_TRACK, 1)[0]
    kit = m.long(KIT_POINTER)
    at = kit + SOUND_BASE + SOUND_STRIDE * track + SOUND_TYPE
    out = {}
    for wr in (False, True):
        saved = m.read(at, 1)
        if wr:
            m.write(at, bytes([WAVERIDER]))
        for s in SLOTS:
            for t in TYPES:
                for f in FILTERS:
                    out[(wr, s, t, f)] = m.call(SITE, s, t, f) & 0xFFFFFFFF
        m.write(at, saved)
    return out


def run(path: pathlib.Path | None, stock: bytes) -> dict:
    m = Machine()
    return answers(m, stock, None if path is None else main_os(path))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("bus", type=pathlib.Path)
    ap.add_argument("--before", type=pathlib.Path, required=True, help="the old Waverider build")
    ap.add_argument("--fx", type=pathlib.Path, required=True, help="the old fxmod build")
    args = ap.parse_args()

    stock = main_os(pathlib.Path(paths.SYX))
    control, before, fx, bus = (run(None, stock), run(args.before, stock),
                                run(args.fx, stock), run(args.bus, stock))
    n = len(control)
    moved_wr = sum(before[k] != control[k] for k in control)
    moved_fx = sum(fx[k] != control[k] for k in control)
    print(f"{n} calls per build ({len(SLOTS)} slots x {len(TYPES)} types x {len(FILTERS)} "
          "filters, active track as saved and as Waverider)")
    print(f"control: the old Waverider build differs from stock in {moved_wr}, "
          f"the old fxmod build in {moved_fx}")
    wrong = [k for k in control
             if bus[k] != (fx[k] if k[1] in FX else before[k])]
    fx_moved = sum(bus[k] != control[k] for k in control if k[1] in FX)
    wr_moved = sum(bus[k] != control[k] for k in control if k[1] not in FX)
    print(f"bus build: differs from stock in {wr_moved} outside the FX slots and {fx_moved} in them")
    for k in wrong[:20]:
        print(f"  WRONG wr_track={k[0]} slot={k[1]} type={k[2]} filter={k[3]}: bus {bus[k]:#x}, "
              f"expected {(fx[k] if k[1] in FX else before[k]):#x}")
    ok = not wrong and moved_wr and moved_fx
    print("PASS: every answer is the replaced code's" if ok else
          f"FAIL: {len(wrong)} answers differ" if wrong else "FAIL: a control did not move")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
