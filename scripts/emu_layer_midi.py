"""Run the frame ISR's own per-note loop on real layered records, with layer-midi installed.

    # with digikit's venv; paths from scripts/emulib/paths.py (docs/emulator.md):
    <digikit>/.venv/bin/python -u scripts/emu_layer_midi.py [build dir] [--post] [--control]

The frame ISR does not run under the emulator (no DSP link), so nothing reaches
the hook by playing. layer-midi1..4 were checked by calling the hook directly,
once per chord note -- which is how I *assumed* the ISR called it, and it does
not: the voice trigger is called once per record, and the bench sent the lowest
note only. So this does not call the hook. It runs **the ISR's own code**:

- the layered copy is made by the firmware's `0x400255b4`, from a source record
  taken from the engine pool (`0x401389d6`);
- its notes are a list as the loop reads it: entries at `+28` (6 bytes:
  `+2` note, `+3` velocity, `+4` length, `+5` group), the next index of entry i
  at `+28 + 0xd000 + 2*i` (`0x40026ca0..0x40026cc0`), -1 ends it;
- execution starts at `0x4002695a` with the ISR's frame laid out as the code
  before it leaves it (`0x40026922..0x40026956`), and stops when the loop
  leaves for `0x40026e50`.

The note-on ends up wherever the ISR's code takes it: the hook at `0x40026980`
(counted), the batch at `-180(%fp)`/`%a5`. Checked: every chord note once, in
order, with its velocity and length; an audio destination and the source
itself untouched; the pool guard; every register the hook must keep.

`--post` then hands the batch to the MIDI task as the ISR does
(`0x40026f2c..0x40026f60`) and checks the records come back. `--control` is
stock's own MIDI note from the panel, to show whether any MIDI byte is visible
under the emulator at all (it is not: see the result).
"""

from __future__ import annotations

import argparse
import pathlib
import struct
import sys

from emulib import paths  # noqa: E402

paths.use_digikit(tools=True)

from emulib import code_chunks, image          # noqa: E402
from emulib.machine import Machine             # noqa: E402
from unicorn import UC_HOOK_CODE               # noqa: E402
from unicorn.m68k_const import (UC_M68K_REG_A2, UC_M68K_REG_A5,  # noqa: E402
                                UC_M68K_REG_A6, UC_M68K_REG_A7, UC_M68K_REG_D0,
                                UC_M68K_REG_D1, UC_M68K_REG_D3, UC_M68K_REG_D5,
                                UC_M68K_REG_D7, UC_M68K_REG_PC)

HOOK = 0x402D0664               # the note hook: layer-midi1..6's cave; from the build otherwise
NOTE_SITE = 0x40026980
LOOP = 0x4002695A
LOOP_EXIT = 0x40026E50
ENGINE_ALLOC = 0x401389D6
LAYER_COPY = 0x400255B4
MIDI_FREE = 0x4460E4B8
MIDI_MASK = 0x8000537C
STACK = 0x46A0F000
FRAME = 0x46A20000               # the ISR's %fp
REGS = ("d0", "d2", "d3", "d4", "d5", "d6", "d7", "a0", "a1", "a2", "a3", "a4", "a6")

failures = []


def check(what, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {what}{'  -- ' + detail if detail and not ok else ''}")
    if not ok:
        failures.append(what)


def be(v):
    return struct.pack(">I", v & 0xFFFFFFFF)


def reg(name):
    from unicorn import m68k_const as k
    return getattr(k, f"UC_M68K_REG_{name.upper()}")


class Rig:
    def __init__(self, m: Machine, sound: int):
        self.m, self.uc, self.sound = m, m.uc, sound
        self.hooked = []
        m.write(FRAME - 512, bytes(1024))
        m.write(0x467E0000, bytes(64))     # layer-midi3/4's last-entry table, mapped
        m.write(STACK - 0x4000, bytes(0x4100))
        self.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, d: self.hooked.append(
            uc.reg_read(UC_M68K_REG_A2)), begin=HOOK, end=HOOK)

        def leave(uc, a, s, d):
            uc.emu_stop()
        self.uc.hook_add(UC_HOOK_CODE, leave, begin=LOOP_EXIT, end=LOOP_EXIT)

    def free(self, limit=4096):
        n, p = 0, self.m.long(MIDI_FREE)
        while p and n < limit:
            n += 1
            p = self.m.long(p + 92)
        return n

    def chord(self, track, notes):
        """A source record whose notes are a list, as the loop reads one."""
        lst = self.m.alloc(0xD000 + 2 * len(notes) + 16)
        for i, (note, vel, length) in enumerate(notes):
            self.m.write(lst + 6 * i, bytes([0, 0, note, vel & 0xFF, length & 0xFF, 0]))
            nxt = i + 1 if i + 1 < len(notes) else -1
            self.m.write(lst + 0xD000 + 2 * i, struct.pack(">h", nxt))
        r = self.m.call(ENGINE_ALLOC)
        if not r:
            raise SystemExit("the engine pool gave nothing")
        self.m.write(r, bytes(0x6C))
        self.m.write(r + 4, be(1))
        self.m.write(r + 16, be(track))
        self.m.write(r + 28, be(lst))
        self.m.write(r + 32, be(0))
        self.m.write(r + 44, be(self.sound))
        return r, lst

    def copy(self, src, dest):
        before = self.m.long(src + 104)
        self.m.call(LAYER_COPY, src, dest)
        c = self.m.long(src + 104)
        if c == before or not c:
            raise SystemExit("0x400255b4 made no copy")
        return c

    def from_trigger(self, rec, lst, timing):
        """Enter one step earlier, at 0x400268de: the voice-trigger call
        (0x400268f8) and then the loop, as the ISR runs them for a note.
        -> (stop pc, batch notes)."""
        m = self.m
        m.write(FRAME - 36, be(rec))
        m.write(FRAME - 44, be(timing))
        m.write(FRAME - 180, be(0))
        self.uc.reg_write(UC_M68K_REG_A5, 0)
        self.uc.reg_write(UC_M68K_REG_A6, FRAME)
        self.uc.reg_write(UC_M68K_REG_A7, STACK)
        self.uc.reg_write(UC_M68K_REG_A2, lst)
        self.uc.reg_write(UC_M68K_REG_D3, m.long(rec + 16))
        self.uc.reg_write(UC_M68K_REG_D7, 0)          # the group, kept at -96(%fp)
        m.flush()
        self.uc.emu_start(0x400268DE, LOOP_EXIT, count=5_000_000)
        return self.uc.reg_read(UC_M68K_REG_PC), self.batch_notes(m.long(FRAME - 180))

    def run_loop(self, rec, lst, timing):
        """Enter the ISR's per-note loop at 0x4002695a for `rec`, its first entry
        in %a2, with the frame 0x40026922..0x40026956 leaves. Stops at 0x40026e50."""
        track = self.m.long(rec + 16)
        m = self.m
        m.write(FRAME - 36, be(rec))                  # the record
        m.write(FRAME - 44, be(timing))               # the voice trigger's time source
        m.write(FRAME - 96, be(0))                    # the group being played (+5)
        m.write(FRAME - 106, struct.pack(">H", 1 << track))
        m.write(FRAME - 92, be(track + 10))
        m.write(FRAME - 112, be(52 + 1163 * track))
        m.write(FRAME - 128, be(0))                   # the voice trigger's answer
        m.write(FRAME - 156, be(self.sound))
        self.uc.reg_write(UC_M68K_REG_A6, FRAME)
        self.uc.reg_write(UC_M68K_REG_A7, STACK)
        self.uc.reg_write(UC_M68K_REG_A2, lst)
        self.uc.reg_write(UC_M68K_REG_D3, track)
        self.uc.reg_write(UC_M68K_REG_D5, 1 << track)
        self.uc.reg_write(UC_M68K_REG_D7, 0)
        self.hooked.clear()
        m.flush()
        self.uc.emu_start(LOOP, LOOP_EXIT, count=5_000_000)
        return self.uc.reg_read(UC_M68K_REG_PC)

    def batch_notes(self, head):
        out, r = [], head
        while r and len(out) < 32:
            rd = self.m.read(r + 38, 3)
            out.append((self.m.long(r + 8), rd[0], rd[1], rd[2]))
            r = self.m.long(r + 92)
        return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("build", nargs="?", default=str(paths.ROOT / "out/layer-midi7"))
    p.add_argument("--post", action="store_true")
    p.add_argument("--control", action="store_true")
    p.add_argument("--trigger-only", action="store_true",
                   help="only the from-the-voice-trigger chord run (any layer-midi build)")
    args = p.parse_args()

    stock = (paths.SECTIONS / "section_3_MAIN_OS.bin").read_bytes()
    built = (pathlib.Path(args.build) / "section_3_MAIN_OS.aplib.bin").read_bytes()
    runs = image.differences(stock, built)
    m = Machine()
    m.apply(runs)
    # A snapshot never runs the platform loader: put each CODE chunk where it
    # would have copied it.
    chunks = code_chunks(built) if len(built) > len(stock) else []
    for c in chunks:
        m.load_code_chunk(c)
    m.flush()
    print(f"  installed {len(runs)} run(s) and {len(chunks)} CODE chunk(s) from {args.build}")
    global HOOK
    site = m.read(NOTE_SITE, 6)
    if site[:2] == bytes.fromhex("4eb9"):
        HOOK = struct.unpack(">I", site[2:])[0]
    if args.control:
        control(m)
        return 0
    if args.trigger_only:
        sound = m.alloc(0x500)
        m.write(sound + 0x480, bytes([90, 20]))
        rig = Rig(m, sound)
        m.write(MIDI_MASK, struct.pack(">H", 1 << 8))
        timing = m.alloc(16)
        m.write(timing, be(0) + be(0x5555))
        src, lst = rig.chord(0, [(60, 100, 8), (64, 90, 12), (67, 100, 6)])
        c = rig.copy(src, 8)
        pc, notes = rig.from_trigger(c, lst, timing)
        print(f"  from the voice-trigger call: stopped at {pc:#x}; "
              f"MIDI notes on the batch: {[n for _, n, _, _ in notes]}")
        return 0
    check(f"the hook site 0x40026980 now calls the note hook ({HOOK:#x})",
          m.read(NOTE_SITE, 6) == bytes.fromhex("4eb9") + be(HOOK))
    if chunks:
        check("the note hook is inside a loaded CODE chunk",
              any(load <= HOOK < load + length for load, length, *_ in chunks))
    check("the voice-trigger call 0x400268f8 is stock",
          m.read(0x400268F8, 6) == bytes.fromhex("4eb9400db524"))

    sound = m.alloc(0x500)
    m.write(sound + 0x480, bytes([90, 20]))
    rig = Rig(m, sound)
    MIDI_T, AUDIO_T = 8, 1
    m.write(MIDI_MASK, struct.pack(">H", 1 << MIDI_T))
    timing = m.alloc(16)
    m.write(timing, be(0) + be(0x5555))           # first long 0 -> the time is +4
    pool0 = rig.free()
    print(f"  MIDI pool: {pool0} free; T{MIDI_T + 1} is MIDI, T{AUDIO_T + 1} audio\n")

    print("the ISR's own loop, a 3-note chord layered onto the MIDI track")
    chord = [(60, 100, 8), (64, 90, 12), (67, -1, -1)]
    src, lst = rig.chord(0, chord)
    c = rig.copy(src, MIDI_T)
    pc = rig.run_loop(c, lst, timing)
    check("the loop ran to its exit 0x40026e50", pc == LOOP_EXIT, f"stopped at {pc:#x}")
    check("the hook ran once per chord note, on each entry",
          rig.hooked == [lst, lst + 6, lst + 12], str([hex(a) for a in rig.hooked]))
    head = m.long(FRAME - 180)
    notes = rig.batch_notes(head)
    check("the batch: T9 60/100/8, 64/90/12, 67/sound's 90/sound's 20",
          notes == [(MIDI_T, 60, 100, 8), (MIDI_T, 64, 90, 12), (MIDI_T, 67, 90, 20)], str(notes))
    check("%a5 is the last of them", rig.uc.reg_read(UC_M68K_REG_A5) and
          m.long(rig.uc.reg_read(UC_M68K_REG_A5) + 92) == 0)
    check("each carries the time the voice trigger would get (0x5555)",
          all(m.long(r + 48) == 0x5555 for r in _chain(m, head)))
    check("three records taken", rig.free() == pool0 - 3, f"{pool0} -> {rig.free()}")

    print("\nthe same chord layered onto an audio track, and the source itself")
    m.write(FRAME - 180, be(0))
    rig.uc.reg_write(UC_M68K_REG_A5, 0)
    n0 = rig.free()
    src, lst = rig.chord(0, chord)
    c = rig.copy(src, AUDIO_T)
    pc = rig.run_loop(c, lst, timing)
    check("audio destination: the loop ran, the hook passed each note through",
          pc == LOOP_EXIT and len(rig.hooked) == 3, f"pc {pc:#x}, {len(rig.hooked)}")
    pc = rig.run_loop(src, lst, timing)
    check("the source (not a copy): likewise", pc == LOOP_EXIT and len(rig.hooked) == 3)
    check("neither sent anything nor took a record",
          m.long(FRAME - 180) == 0 and rig.free() == n0)

    print("\nthe registers the loop relies on")
    saved = {r: 0x1000 + i for i, r in enumerate(REGS)}
    for r, v in saved.items():
        rig.uc.reg_write(reg(r), v)
    rig.uc.reg_write(UC_M68K_REG_A6, FRAME)
    rig.uc.reg_write(UC_M68K_REG_A2, lst)
    rig.uc.reg_write(UC_M68K_REG_A7, STACK)
    m.write(STACK, be(0x46A30000))
    m.write(0x46A30000, b"\x4e\x71" * 4)
    m.write(FRAME - 36, be(c))                    # the audio copy: the stock path
    rig.uc.emu_start(HOOK, 0x46A30000, count=10_000)
    changed = [r for r, v in saved.items() if r not in ("a2", "a6")
               and rig.uc.reg_read(reg(r)) != v]
    check("every register kept but %d1 (set by the displaced instruction)", not changed,
          str(changed))
    want_d1 = m.word(0x8000537E)
    check("%d1 = mvz.w 0x8000537e, as the stock instruction leaves it",
          rig.uc.reg_read(UC_M68K_REG_D1) == want_d1)

    release_checks(m, rig, timing, MIDI_T)

    print("\nthe pool guard")
    head0, low0 = m.long(MIDI_FREE), _low(m)
    m.write(FRAME - 180, be(0))
    rig.uc.reg_write(UC_M68K_REG_A5, 0)
    for label, free in (("empty", be(0)), ("one left", None)):
        if free is None:
            one = m.alloc(0x60)
            m.write(MIDI_FREE, be(one))
        else:
            m.write(MIDI_FREE, free)
        before = m.long(MIDI_FREE)
        src, lst = rig.chord(0, chord)
        c = rig.copy(src, MIDI_T)
        pc = rig.run_loop(c, lst, timing)
        check(f"{label}: the loop finished, nothing sent, the free list as it was, "
              "low memory untouched",
              pc == LOOP_EXIT and m.long(FRAME - 180) == 0 and m.long(MIDI_FREE) == before
              and _low(m) == low0)
    m.write(MIDI_FREE, be(head0))

    if args.post:
        post(m, rig, timing)

    print(f"\n{len(failures)} failure(s)" if failures else "\nall checks pass")
    return 1 if failures else 0


RELEASE_ENTRY = 0x40026CD6        # tstl %d0: the copy flag, then the release
RELEASE_HOOK_SITE = 0x40026D32
RELEASE_RESUME = 0x40026D38
LAYER_MASKS = 0x4058F3A0          # word per (track * 128 + note)


def release_checks(m: Machine, rig: Rig, timing: int, midi_t: int) -> None:
    """A key-up: the source's release record runs the ISR's release path,
    which makes the release copies itself (0x40026cee..0x40026d30); each
    copy's release then runs the per-note release loop, where the hook is."""
    print("\nrelease: the ISR's own release path, a live note layered onto the MIDI track")
    m.write(FRAME - 180, be(0))
    rig.uc.reg_write(UC_M68K_REG_A5, 0)
    src, lst = rig.chord(0, [(62, 100, 127)])
    m.write(src + 4, be(0))                       # a release record, not kind 1
    m.write(LAYER_MASKS + 2 * (0 * 128 + 62), struct.pack(">H", 1 << midi_t))
    pool = rig.free()

    def release(rec, copy_flag):
        m.write(FRAME - 36, be(rec))
        rig.uc.reg_write(UC_M68K_REG_D0, copy_flag)
        rig.uc.reg_write(UC_M68K_REG_D3, m.long(rec + 16))
        rig.uc.reg_write(UC_M68K_REG_A2, lst)
        rig.uc.reg_write(UC_M68K_REG_A6, FRAME)
        rig.uc.reg_write(UC_M68K_REG_A7, STACK)
        rig.hooked.clear()
        m.flush()
        rig.uc.emu_start(RELEASE_ENTRY, LOOP_EXIT, count=5_000_000)
        return rig.uc.reg_read(UC_M68K_REG_PC)

    before = m.long(src + 104)
    pc = release(src, 0)
    copy = m.long(src + 104)
    check("the source's release ran, and the firmware made a release copy for T9",
          pc == LOOP_EXIT and copy and copy != before and m.long(copy + 16) == midi_t,
          f"pc {pc:#x}, copy {copy:#x}")
    check("the source's own release sent nothing", m.long(FRAME - 180) == 0)
    check("the saved mask was consumed", m.word(LAYER_MASKS + 2 * 62) == 0)
    pc = release(copy, 0x20000)
    head = m.long(FRAME - 180)
    got = (m.long(head + 8), m.long(head + 12), m.read(head + 38, 1)[0]) if head else None
    check("the copy's release: one MIDI record, T9, kind 0 (note-off), note 62",
          pc == LOOP_EXIT and got == (midi_t, 0, 62) and m.long(head + 92) == 0, str(got))
    check("one record taken", rig.free() == pool - 1)

    print("\nthe release hook's registers and stack")
    saved = {r: 0x2000 + i for i, r in enumerate(REGS)}
    for r, v in saved.items():
        rig.uc.reg_write(reg(r), v)
    m.write(FRAME - 36, be(src))                  # not a copy: the stock path
    rig.uc.reg_write(UC_M68K_REG_A6, FRAME)
    rig.uc.reg_write(UC_M68K_REG_A2, lst)
    rig.uc.reg_write(UC_M68K_REG_A7, STACK)
    m.flush()
    rig.uc.emu_start(RELEASE_HOOK_SITE, RELEASE_RESUME, count=10_000)
    changed = [r for r, v in saved.items() if r not in ("a2", "a6", "d4")
               and rig.uc.reg_read(reg(r)) != v]
    sp = rig.uc.reg_read(UC_M68K_REG_A7)
    check("it resumes at 0x40026d38 with every register kept",
          rig.uc.reg_read(UC_M68K_REG_PC) == RELEASE_RESUME and not changed, str(changed))
    check("%d4 = the note, pushed once: the stack exactly as stock leaves it",
          rig.uc.reg_read(reg("d4")) == 62 and sp == STACK - 4 and m.long(sp) == 62,
          f"d4 {rig.uc.reg_read(reg('d4'))}, sp {STACK - sp} below, top {m.long(sp)}")


def _chain(m, r):
    out = []
    while r and len(out) < 32:
        out.append(r)
        r = m.long(r + 92)
    return out


def _low(m):
    try:
        return m.read(0, 96)
    except Exception:                                         # noqa: BLE001
        return None


MSG_ALLOC, QUEUE_POST, MIDI_QUEUE = 0x40025E0A, 0x40001896, 0x445FE870
NOW, MSG_12 = 0x80005398, 0x4058E554


def post(m: Machine, rig: Rig, timing: int) -> None:
    """Hand a batch to the MIDI task exactly as the ISR does, and run."""
    from emulib.panel import Panel

    print("\nthe MIDI task takes the batch")
    panel = Panel(m)
    m.write(FRAME - 180, be(0))
    rig.uc.reg_write(UC_M68K_REG_A5, 0)
    pool0 = rig.free()
    now = m.long(NOW)
    m.write(timing, be(1))                         # first long nonzero -> now
    src, lst = rig.chord(0, [(48, 100, 4), (52, 100, 4), (55, 100, 4)])
    c = rig.copy(src, 8)
    m.write(NOW, be(now))
    rig.run_loop(c, lst, timing)
    head = m.long(FRAME - 180)
    check("three records on the batch", rig.free() == pool0 - 3, f"{pool0} -> {rig.free()}")
    msg = m.call(MSG_ALLOC)
    for off, v in ((0, 1), (4, now), (8, now), (12, m.long(MSG_12)), (16, head)):
        m.write(msg + off, be(v))
    m.call(QUEUE_POST, MIDI_QUEUE, msg)
    m.flush()
    seen = []
    for _ in range(6):
        panel.settle(10_000_000)
        seen.append(rig.free())
    print(f"  free records, per 10M instructions: {seen}")
    check("the MIDI task took the batch and gave every record back", rig.free() == pool0)


def control(m: Machine) -> None:
    """Stock's own MIDI note from the panel: is any MIDI byte visible here?"""
    import re
    from emulib.panel import Panel

    print("\ncontrol: stock's own MIDI note (T1 MIDI, TRIG 1)")
    panel = Panel(m)
    kit = m.long(0x42C5A9AC)
    m.write(kit + 0x5CDA, struct.pack(">H", m.word(kit + 0x5CDA) | 1))
    m.write(MIDI_MASK, struct.pack(">H", m.word(MIDI_MASK) | 1))   # the ISR's mirror
    sends, downs, io = [], [], []
    m.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, d: sends.append(1),
                  begin=0x4012B8B0, end=0x4012B8B0)
    m.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, d: downs.append(1),
                  begin=0x40121AD2, end=0x40121AD2)
    for lo, hi in ((0xEC000000, 0xECFFFFFF), (0xFC000000, 0xFCFFFFFF)):
        m.watch_writes(lo, hi, lambda pc, a, v, n: io.append((a, v & 0xFF, n)))

    def ram():
        data = bytes(m.uc.mem_read(0x44000000, 0x46700000 - 0x44000000))
        return {(0x44000000 + h.start(), data[h.start() + 2])
                for h in re.finditer(rb"[\x90-\x9f]\x3c[\x01-\x7f]", data)}
    before = ram()
    m.flush()
    panel.tap((3, 0), after=30_000_000)
    new = ram() - before
    status = [v for a, v, n in io if n == 1 and 0x90 <= v <= 0x9F]
    print(f"  key-down {len(downs)}, MIDI sender {len(sends)}; 9n bytes to a peripheral: "
          f"{len(status)}; new 9n 3c vv in RAM: {len(new)}")
    print("  -> " + ("visible" if status or new else
                     "the stock MIDI note reaches the MIDI sender and leaves no visible byte: "
                     "MIDI output is not observable this way under the emulator"))


if __name__ == "__main__":
    sys.exit(main())
