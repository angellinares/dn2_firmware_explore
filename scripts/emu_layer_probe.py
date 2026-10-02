"""Where track layering fans a note out, and why a MIDI destination gets nothing.

    # with digikit's venv; paths from scripts/emulib/paths.py (docs/emulator.md):
    <digikit>/.venv/bin/python -u scripts/emu_layer_probe.py [--key CODE] [--dest N] [--midi]

**The question.** With T1 layered onto a MIDI track, playing T1 sends no MIDI
(bench, 2026-10-01). Where does the firmware read the layering table, and does
the destination track ever reach the key-down handler, the voice starter or
the MIDI sender?

**How.** Restore `ui1200M`, find the active kit (`0x42c5a9ac`, written by
`0x400d8584` as `0x4210c08c + 0x5d71*index`), set the source track's
layering mask (kit `+0x2ca0`, assumed 16 x 16-bit: one destination mask per
source track) and optionally mark the destination MIDI (kit `+0x5cda`). Then
tap the source track's trig key on the panel and log:

- every read of the layering table and the choke table after it (PC, caller);
- every entry to the key-down handler `0x40121ad2` (track, note), the voice
  starter `0x40137d3c` and the MIDI sender `0x4012b8b0`.

Run once with `--dest 2` (audio, the control) and once with `--dest 9 --midi`.
The emulator does not play the sequencer (docs/ideas-backlog.md §20), so this
covers live play only; it tells us whether layering applies there at all.
"""

from __future__ import annotations

import argparse
import struct

from emulib import paths  # noqa: E402

paths.use_digikit(tools=True)

from emulib.machine import Machine            # noqa: E402
from emulib.panel import Panel                 # noqa: E402
from unicorn import UC_HOOK_MEM_READ           # noqa: E402
from unicorn.m68k_const import UC_M68K_REG_A7, UC_M68K_REG_PC  # noqa: E402

KIT_PTR = 0x42C5A9AC
# The TRACK WILL TRIGGER / CHOKES screen (strings at 0x4021f87d, 0x4021f890;
# drawn by 0x4010fb0a) asks 0x4010f764(owner, src, dest) per cell, which tests
# two bit tables in the kit (owner vtable +52, a 0x5d71-byte kit):
#   0x400315dc: word at +0x5ce0 + 2*src, bit dest   (setter 0x40031620)
#   0x40031758: word at +0x5d00 + 2*src, bit dest   (setter 0x400316b8)
# Which is "will trigger" and which "chokes" is what this probe settles.
# SYXGRID's +0x2ca0 is not read in RAM (probe, 2026-10-01).
LAYER, CHOKE, MIDI_MASK = 0x5CE0, 0x5D00, 0x5CDA
KEY_DOWN, VOICE_START, MIDI_SEND = 0x40121AD2, 0x40137D3C, 0x4012B8B0


def caller(uc, depth=48):
    """-> the first few return addresses on the stack that point into code."""
    sp = uc.reg_read(UC_M68K_REG_A7)
    words = struct.unpack(f">{depth}I", bytes(uc.mem_read(sp, depth * 4)))
    return [hex(w) for w in words if 0x40000400 <= w < 0x401D0000][:4]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--src", type=int, default=1, help="source track, 1-based")
    p.add_argument("--dest", type=int, default=2, help="destination track, 1-based")
    p.add_argument("--midi", action="store_true", help="mark the destination a MIDI track")
    p.add_argument("--no-layer", action="store_true", help="control: leave the table stock")
    p.add_argument("--table", choices=("a", "b"), default="a",
                   help="a = +0x5ce0 table, b = +0x5d00 table")
    p.add_argument("--key", type=int, required=True,
                   help="panel code of the source track's trig key (scripts/emu_panel_map.py --all)")
    p.add_argument("--settle", type=int, default=20_000_000)
    args = p.parse_args()

    machine = Machine()
    panel = Panel(machine)
    kit = machine.long(KIT_PTR)
    src, dest = args.src - 1, args.dest - 1
    print(f"  kit at {kit:#010x}")
    print(f"  layering table: {machine.read(kit + LAYER, 32).hex(' ', 2)}")
    print(f"  choke table:    {machine.read(kit + CHOKE, 32).hex(' ', 2)}")
    print(f"  MIDI mask:      {machine.word(kit + MIDI_MASK):#06x}")

    if not args.no_layer:
        row = kit + (CHOKE if args.table == "b" else LAYER) + 2 * src
        old = machine.word(row)
        machine.write(row, struct.pack(">H", old | (1 << src) | (1 << dest)))
        print(f"  T{args.src} layer mask {old:#06x} -> {machine.word(row):#06x}")
    if args.midi:
        mask = machine.word(kit + MIDI_MASK)
        machine.write(kit + MIDI_MASK, struct.pack(">H", mask | (1 << dest)))
        print(f"  MIDI mask -> {machine.word(kit + MIDI_MASK):#06x}")

    reads, calls = {}, []

    def on_read(uc, access, address, size, value, user):
        pc = uc.reg_read(UC_M68K_REG_PC)
        off = address - kit
        key = (pc, off)
        if key not in reads:
            reads[key] = caller(uc)

    machine.uc.hook_add(UC_HOOK_MEM_READ, on_read, begin=kit + LAYER, end=kit + CHOKE + 31)

    def arg(uc, n):
        sp = uc.reg_read(UC_M68K_REG_A7)
        return struct.unpack(">i", bytes(uc.mem_read(sp + 4 * n, 4)))[0]

    def on_key_down(uc, a, s, d):
        calls.append(("key-down", f"track {arg(uc, 1)} note {arg(uc, 2)}", caller(uc)))

    def on_voice(uc, a, s, d):
        calls.append(("voice-start", "", caller(uc)))

    def on_midi(uc, a, s, d):
        calls.append(("midi-send", "", caller(uc)))

    machine.hook_at(KEY_DOWN, on_key_down)
    machine.hook_at(VOICE_START, on_voice)
    machine.hook_at(MIDI_SEND, on_midi)

    machine.flush()
    code = args.key - 1
    panel.tap((code // 8, code % 8), after=args.settle)

    print(f"\n  reads of the layering/choke tables ({len(reads)} distinct pc/offset):")
    for (pc, off), up in sorted(reads.items()):
        table = "layer" if off < CHOKE else "choke"
        print(f"    pc {pc:#010x}  {table} +{off - (LAYER if table == 'layer' else CHOKE):#04x}"
              f"  callers {up}")
    print(f"\n  calls ({len(calls)}):")
    for name, what, up in calls:
        print(f"    {name:12} {what:22} callers {up}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
