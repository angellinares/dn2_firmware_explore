"""midiarp's voice-trigger hook on layered copies and on an empty MIDI record pool, before and after.

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python -u \\
        scripts/emu_midiarp_layered.py --old out/midiarp-old/section_3_MAIN_OS.bin \\
                                       --new out/midiarp-new/section_3_MAIN_OS.bin

Two bugs, reported on 2026-10-02 by the contributor of PR #176 (`layermidi`) and
confirmed here in the firmware before they were fixed (2026-10-03):

1. **Layered copies.** TRACK WILL TRIGGER makes the frame ISR copy a note record onto
   the destination track (`0x400255b4`: it copies the source's 0x6c bytes and sets
   `+56` bit 17). midiarp's hook on the voice trigger (`0x400268f8`) turned every
   record of a MIDI track into a MIDI note from the record's *inline* entry
   (`+38..+40`). A sequencer trig keeps its notes in a list (`+28`), so a copy's
   inline entry is whatever the engine record held before: random notes.
2. **The MIDI record pool.** The hook takes a record with `0x4012a408`, which pops
   `0x4460e4b8` with no empty check: an empty pop reads address 92 as the new head
   and clears 0, 4 and 92.

**How it is run.** The frame ISR does not run under the emulator (no DSP link), so
nothing reaches the hook by playing. This enters the ISR's own code at
`0x400268f8` -- the call the hook replaces -- with the ISR's frame as it has it
there (`%fp`, the batch head `-180(%fp)` and tail `%a5`, the entry in `%a2`, the
record and time on the stack) and stops at its return `0x400268fe`, or when the
code reaches the stock voice trigger `0x400db524` (the hook passing the record on).
The layered copy is made by the firmware's own `0x400255b4` from a source record
taken from the engine pool, so it has exactly the flags and bytes the ISR gives it.
What the hook put on the batch is read back from the records.

**Controls.** Each negative has its positive beside it, in the same build: the
hook is entered and sends a note for an arp step on a MIDI track (3), and the same
layered copy onto an *audio* track reaches the stock trigger (2), so "nothing sent"
means the hook ran and decided, not that it never ran. The unchanged cases (3, 4)
must give the same record before and after.

`--old` is the build before the fixes (`arp-midi-play4`'s hook in its cave), `--new`
the fixed one on the platform (its code is a `CODE` chunk the loader would have
copied; this does the loader's job). Either alone is run; with both, every
"unchanged" case is compared.
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from emulib import code_chunks, differences, check, report      # noqa: E402
from emulib.machine import Machine                              # noqa: E402

HOOK_SITE, HOOK_RET = 0x400268F8, 0x400268FE
VOICE_TRIGGER = 0x400DB524
ENGINE_ALLOC, LAYER_COPY = 0x401389D6, 0x400255B4
KIT_PTR, MIDI_MASK = 0x800052A0, 0x8000537C
FREE_LIST = 0x4460E4B8
SOUND_BASE, SOUND_STRIDE = 52, 1163
ARP_MODE, ARP_NLEN, DEF_VEL, DEF_LEN = 0x15F, 0x162, 0x480, 0x481
FRAME, STACKTOP = 0x46A40000, 0x46A3F000
MIDI_T, AUDIO_T, SRC_T = 8, 1, 0            # T9 is the MIDI track, T2 audio, the source is T1
TIME = 0x5555
SENTINEL = {f"d{i}": 0x1000 + i for i in range(2, 8)} | {f"a{i}": 0x2000 + i for i in (3, 4)}
JUNK = bytes([0x00, 0x00, 0x7B, 0x03, 0x59, 0x00])     # what an engine record held before: a trig never fills +36

BIT_ARP, BIT_COPY, BIT_LEGATO = 1 << 19, 1 << 17, 1 << 18


def be(v):
    return struct.pack(">I", v & 0xFFFFFFFF)


def reg(name):
    from unicorn import m68k_const as k
    return getattr(k, f"UC_M68K_REG_{name.upper()}")


class Rig:
    """One machine with one build installed, and the ISR's frame around the hook."""

    def __init__(self, section: bytes, stock: bytes):
        from unicorn import UC_HOOK_CODE

        self.m = Machine()
        self.uc = self.m.uc
        self.m.apply(differences(stock, section))
        chunks = code_chunks(section) if len(section) > len(stock) else []
        for c in chunks:
            self.m.load_code_chunk(c)
        self.m.flush()
        self.chunks = chunks
        self.m.write(FRAME - 0x400, bytes(0x800))
        self.m.write(STACKTOP - 0x100, bytes(0x200))
        self.trigger = {"hit": False, "regs": {}, "sp": 0}
        self.uc.hook_add(UC_HOOK_CODE, self._at_trigger, begin=VOICE_TRIGGER, end=VOICE_TRIGGER)
        self.kit = self.m.long(KIT_PTR)
        self.m.write(MIDI_MASK, struct.pack(">H", 1 << MIDI_T))
        self.pool0 = self.pool_chain()
        # Low memory holds zeros here, which an empty pop's clears would leave as they
        # are: a known pattern makes any write to it visible.
        self.m.write(0, bytes([0xA5]) * 128)

    def _at_trigger(self, uc, address, size, user):
        t = self.trigger
        t["hit"] = True
        t["regs"] = {r: uc.reg_read(reg(r)) for r in SENTINEL}
        t["sp"] = uc.reg_read(reg("a7"))
        uc.emu_stop()

    # -- the kit's sounds and the MIDI record pool ------------------------------
    def sound(self, track):
        return self.kit + SOUND_BASE + SOUND_STRIDE * track

    def configure(self, track, arp_mode, nlen=0):
        s = self.sound(track)
        self.m.write(s + ARP_MODE, bytes([arp_mode]))
        self.m.write(s + ARP_NLEN, bytes([nlen]))
        self.m.write(s + DEF_VEL, bytes([90, 20]))

    def pool_chain(self):
        """The free list, or None when it leads off the map (a corrupted head)."""
        out, p = [], self.m.long(FREE_LIST)
        try:
            while p and len(out) < 4096:
                out.append(p)
                p = self.m.long(p + 92)
        except Exception:                                     # noqa: BLE001
            return None
        return out

    def free_count(self):
        chain = self.pool_chain()
        return None if chain is None else len(chain)

    def set_pool(self, free):
        """Leave `free` records on the free list (the rest are set aside)."""
        chain = self.pool0
        assert free <= len(chain)
        for i, r in enumerate(chain):
            self.m.write(r + 92, be(chain[i + 1] if i + 1 < free else 0) if i < free else be(0))
        self.m.write(FREE_LIST, be(chain[0] if free else 0))

    def restore_pool(self):
        self.set_pool(len(self.pool0))
        for i, r in enumerate(self.pool0):
            self.m.write(r + 92, be(self.pool0[i + 1] if i + 1 < len(self.pool0) else 0))

    def low_memory(self):
        try:
            return self.m.read(0, 128)
        except Exception:                                     # noqa: BLE001
            return None

    # -- records ----------------------------------------------------------------
    def engine_record(self, track, flags=0, entries=None, inline=JUNK):
        """A record as the ISR gets it from the sequencer: its notes a list at +28 (read
        from index +32 = 0), the inline entry at +36 never filled."""
        r = self.m.call(ENGINE_ALLOC)
        assert r, "the engine pool gave nothing"
        self.m.write(r, bytes(0x6C))
        self.m.write(r + 4, be(1))
        self.m.write(r + 16, be(track))
        self.m.write(r + 56, be(flags))
        self.m.write(r + 36, inline)
        lst = 0
        if entries:
            lst = self.m.alloc(0xD000 + 64)
            for i, (note, vel, length) in enumerate(entries):
                self.m.write(lst + 6 * i, bytes([0, 0, note, vel & 0xFF, length & 0xFF, 0]))
                self.m.write(lst + 0xD000 + 2 * i,
                             struct.pack(">h", i + 1 if i + 1 < len(entries) else -1))
            self.m.write(r + 28, be(lst))
            self.m.write(r + 32, be(0))
        else:
            self.m.write(r + 32, be(0xFFFFFFFF))
        return r, lst

    def layered_copy(self, src, dest):
        before = self.m.long(src + 104)
        self.m.call(LAYER_COPY, src, dest)
        c = self.m.long(src + 104)
        assert c and c != before, "0x400255b4 made no copy"
        return c

    # -- the call -----------------------------------------------------------------
    def call_hook(self, rec, entry):
        """Run the ISR's `jsr 0x400db524` with the hook in place. -> what happened."""
        m, uc = self.m, self.uc
        track = m.long(rec + 16)
        m.write(FRAME - 180, be(0))
        m.write(FRAME - 36, be(rec))
        m.write(STACKTOP, be(rec) + be(TIME))
        uc.reg_write(reg("a5"), 0)
        uc.reg_write(reg("a6"), FRAME)
        uc.reg_write(reg("a7"), STACKTOP)
        uc.reg_write(reg("a2"), entry)
        uc.reg_write(reg("d3"), track)
        for r, v in SENTINEL.items():
            uc.reg_write(reg(r), v)
        uc.reg_write(reg("d0"), 0xDEAD)
        self.trigger.update(hit=False, regs={}, sp=0)
        free0, low0 = self.free_count(), self.low_memory()
        fault = None
        m.flush()
        try:
            uc.emu_start(HOOK_SITE, HOOK_RET, count=200_000)
        except Exception as exc:                              # noqa: BLE001
            fault = type(exc).__name__ + f": {exc}"
        pc = uc.reg_read(reg("pc"))
        out = {"fault": fault, "stock": self.trigger["hit"], "returned": pc == HOOK_RET and not fault,
               "d0": uc.reg_read(reg("d0")), "free_before": free0, "free_after": None, "head": 0,
               "low_changed": None, "sent": []}
        if fault is None:
            out["free_after"] = self.free_count()
            out["head"] = m.long(FREE_LIST)
            low = self.low_memory()
            out["low_changed"] = low != low0
            r = m.long(FRAME - 180)
            while r and len(out["sent"]) < 16:
                out["sent"].append({"track": m.long(r + 8), "kind": m.long(r + 12),
                                    "note": m.read(r + 38, 1)[0], "vel": m.read(r + 39, 1)[0],
                                    "len": m.read(r + 40, 1)[0], "sound": m.long(r + 44),
                                    "time": m.long(r + 48), "tail": r})
                r = m.long(r + 92)
            out["a5"] = uc.reg_read(reg("a5"))
            out["regs"] = {x: uc.reg_read(reg(x)) for x in SENTINEL}
            out["sp"] = uc.reg_read(reg("a7"))
        else:
            out["low_changed"] = "unreadable" if low0 is None else "faulted"
        if self.trigger["hit"]:
            out["regs"], out["sp"] = self.trigger["regs"], self.trigger["sp"]
        return out


def describe(o):
    if o["fault"]:
        return f"FAULT {o['fault']}"
    if o["free_after"] is None:
        return f"the free list now leads off the map (head {o['head']:#x}); sent {len(o['sent'])}"
    if o["stock"]:
        return "passed to the stock voice trigger, nothing sent"
    notes = [(s["note"], s["vel"], s["len"]) for s in o["sent"]]
    return f"sent {notes} (note, velocity, length); pool {o['free_before']} -> {o['free_after']}"


def scenarios(rig: Rig, label: str):
    """-> {case: observation}, for one build. Nothing is judged here."""
    obs = {}
    rig.configure(MIDI_T, 0)
    rig.configure(AUDIO_T, 0)
    chord = [(60, 100, 8), (64, 90, 12), (67, 100, 6)]

    # 1. the bug: a layered copy of a sequencer trig on a MIDI track, its arp off
    src, lst = rig.engine_record(SRC_T, entries=chord)
    c = rig.layered_copy(src, MIDI_T)
    obs["copy_arp_off"] = rig.call_hook(c, lst)
    obs["copy_arp_off"]["flags"] = rig.m.long(c + 56)
    obs["copy_arp_off"]["inline"] = tuple(rig.m.read(c + 38, 3))

    # 2. control: the same copy onto an audio track
    c = rig.layered_copy(src, AUDIO_T)
    obs["copy_audio"] = rig.call_hook(c, lst)

    # 3. control: an arp step on a MIDI track (inline entry filled by the ISR, bit 19, a2 = +36)
    rig.configure(MIDI_T, 1, nlen=20)
    r, _ = rig.engine_record(MIDI_T, flags=BIT_ARP, inline=bytes([0, 0, 62, 100, 0x7F, 0]))
    obs["arp_step"] = rig.call_hook(r, r + 36)
    r, _ = rig.engine_record(MIDI_T, flags=BIT_ARP, inline=bytes([0, 0, 55, 0x80, 0x7F, 0]))
    obs["arp_step_defaults"] = rig.call_hook(r, r + 36)

    # 4. a layered copy onto a MIDI track whose arp is on, played by that arp (bit 19)
    r, _ = rig.engine_record(MIDI_T, flags=BIT_ARP | BIT_COPY, inline=bytes([0, 0, 65, 80, 0x7F, 0]))
    obs["copy_arp_step"] = rig.call_hook(r, r + 36)

    # 5. the same copy, arp on, but not an arp step: a list entry and a stale inline entry
    src, lst = rig.engine_record(SRC_T, entries=chord)
    c = rig.layered_copy(src, MIDI_T)
    obs["copy_arp_on_not_step"] = rig.call_hook(c, lst)

    # 6. not a copy, not an arp step (legato): the entry is the list's
    r, lst = rig.engine_record(MIDI_T, flags=BIT_LEGATO, entries=chord)
    obs["legato_list_entry"] = rig.call_hook(r, lst)

    # 7. the pool: empty, then one record, three, four -- an arp step each time
    for free in (0, 1, 3, 4):
        rig.set_pool(free)
        low0 = rig.low_memory()
        r, _ = rig.engine_record(MIDI_T, flags=BIT_ARP, inline=bytes([0, 0, 62, 100, 6, 0]))
        obs[f"pool_{free}"] = rig.call_hook(r, r + 36)
        obs[f"pool_{free}"]["low_same"] = rig.low_memory() == low0
        rig.restore_pool()
        rig.m.write(0, bytes([0xA5]) * 128)

    # 8. a flood: more arp steps than the pool has records, none given back
    n0 = len(rig.pool0)
    sent, faults, lows = 0, None, []
    low0 = rig.low_memory()
    r, _ = rig.engine_record(MIDI_T, flags=BIT_ARP, inline=bytes([0, 0, 62, 100, 6, 0]))
    for _ in range(n0 + 4):
        o = rig.call_hook(r, r + 36)
        if o["fault"]:
            faults = o["fault"]
            break
        sent += len(o["sent"])
    obs["flood"] = {"sent": sent, "pool_start": n0, "free_end": rig.free_count() if not faults else None,
                    "fault": faults, "low_same": (rig.low_memory() == low0) if not faults else False,
                    "head_end": rig.m.long(FREE_LIST)}
    rig.restore_pool()
    return obs


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--old", help="the build before the fixes (section_3_MAIN_OS.bin)")
    p.add_argument("--new", help="the fixed build")
    args = p.parse_args()
    if not (args.old or args.new):
        p.error("give --old, --new, or both")
    stock = open(os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"), "rb").read()
    results = {}
    for label, path in (("old", args.old), ("new", args.new)):
        if not path:
            continue
        print(f"== {label}: {path}")
        rig = Rig(open(path, "rb").read(), stock)
        print(f"   MIDI pool: {len(rig.pool0)} free; T{MIDI_T + 1} is MIDI, T{AUDIO_T + 1} audio; "
              f"{len(rig.chunks)} CODE chunk(s) loaded")
        results[label] = scenarios(rig, label)
        for case, o in results[label].items():
            if case == "flood":
                print(f"   {case:<22} sent {o['sent']} of {o['pool_start'] + 4} steps; "
                      f"free list head {o['head_end']:#x}, fault {o['fault']}, low memory same: {o['low_same']}")
            else:
                print(f"   {case:<22} {describe(o)}")

    chord_notes = {60, 64, 67}
    for label, o in results.items():
        print(f"\n== judging {label}")
        c = o["copy_arp_off"]
        check(f"[{label}] copy has bit 17 and the source's stale inline entry (the input arrives)",
              bool(c["flags"] & BIT_COPY) and c["inline"] == tuple(JUNK[2:5]), f"flags {c['flags']:#x}, inline {c['inline']}")
        check(f"[{label}] control: copy onto an audio track reaches the stock trigger, nothing sent",
              o["copy_audio"]["stock"] and not o["copy_audio"]["sent"])
        check(f"[{label}] control: an arp step on a MIDI track is sent (the hook runs and sends)",
              len(o["arp_step"]["sent"]) == 1 and o["arp_step"]["sent"][0]["note"] == 62
              and o["arp_step"]["sent"][0]["track"] == MIDI_T and o["arp_step"]["sent"][0]["vel"] == 100)
        if label == "old":
            sent = c["sent"]
            check("[old] BUG: the layered copy (arp off) is sent as a MIDI note from the stale inline entry",
                  len(sent) == 1 and sent[0]["note"] not in chord_notes
                  and (sent[0]["note"], sent[0]["vel"]) == (JUNK[2], JUNK[3]),
                  describe(c))
        else:
            check("[new] a layered copy on a MIDI track with its arp off is not turned into a note: "
                  "stock trigger, nothing sent, no record taken",
                  c["stock"] and not c["sent"] and c["free_after"] == c["free_before"], describe(c))
            n = o["copy_arp_on_not_step"]
            check("[new] a layered copy that is not an arp step is not turned into a note either",
                  n["stock"] and not n["sent"], describe(n))
            check("[new] a layered copy played by its own track's arp (bit 19) is sent: the arp's note",
                  len(o["copy_arp_step"]["sent"]) == 1 and o["copy_arp_step"]["sent"][0]["note"] == 65)
            l = o["legato_list_entry"]
            check("[new] a non-arp record reads the ISR's entry, not the inline one: the list's first note",
                  len(l["sent"]) == 1 and (l["sent"][0]["note"], l["sent"][0]["vel"], l["sent"][0]["len"]) == (60, 100, 8),
                  describe(l))
            for case in ("copy_arp_off", "copy_arp_on_not_step", "copy_audio"):
                x = o[case]
                same = all(x["regs"].get(r) == v for r, v in SENTINEL.items())
                check(f"[new] {case}: reached the stock trigger with every callee-saved register kept and the "
                      "stack as the ISR left it", x["stock"] and same and x["sp"] == STACKTOP - 4,
                      f"sp {STACKTOP - x['sp']} below the top")
            x = o["arp_step"]
            check("[new] the sent step: every callee-saved register kept, d0 = 0, stack balanced, batch tail %a5 "
                  "is the new record",
                  x["returned"] and x["d0"] == 0 and all(x["regs"][r] == v for r, v in SENTINEL.items())
                  and x["sp"] == STACKTOP and x["a5"] == x["sent"][0]["tail"], str(x["regs"]))
        # the pool
        e = o["pool_0"]
        if label == "old":
            check("[old] BUG: an empty pool: the hook pops it anyway and corrupts low memory (or faults)",
                  bool(e["fault"]) or e["low_changed"] is True or not e["low_same"] or
                  bool(e["sent"]) and e["sent"][0]["tail"] == 0,
                  f"{describe(e)}, low memory changed: {e['low_changed']}, same: {e['low_same']}")
        else:
            check("[new] an empty pool: nothing taken, nothing sent, low memory untouched, no fault",
                  not e["fault"] and not e["sent"] and e["low_same"] and e["free_after"] == 0
                  , describe(e))
            check("[new] one record free: not taken (two or three: likewise)",
                  all(not o[f"pool_{k}"]["fault"] and not o[f"pool_{k}"]["sent"] and o[f"pool_{k}"]["free_after"] == k
                      for k in (1, 3)), "; ".join(describe(o[f"pool_{k}"]) for k in (1, 3)))
            check("[new] four free: taken (a note is sent) and three are left",
                  len(o["pool_4"]["sent"]) == 1 and o["pool_4"]["free_after"] == 3, describe(o["pool_4"]))
            f = o["flood"]
            check("[new] a flood of arp steps: never faults, the pool never empties (3 left), low memory untouched",
                  not f["fault"] and f["low_same"] and f["free_end"] == 3 and f["sent"] == f["pool_start"] - 3,
                  f"sent {f['sent']} of {f['pool_start'] + 4}, {f['free_end']} left")
        if label == "old":
            f = o["flood"]
            check("[old] BUG: a flood of arp steps empties the pool and the next one corrupts low memory (or faults)",
                  bool(f["fault"]) or not f["low_same"] or f["free_end"] is None,
                  f"sent {f['sent']} of {f['pool_start'] + 4}, {f['free_end']} left, head {f['head_end']:#x}, "
                  f"fault {f['fault']}, low same {f['low_same']}")

    if "old" in results and "new" in results:
        print("\n== before and after, the cases that must not change")
        for case in ("arp_step", "arp_step_defaults", "copy_arp_step", "copy_audio"):
            a, b = results["old"][case], results["new"][case]
            ka = [(s["track"], s["kind"], s["note"], s["vel"], s["len"], s["time"]) for s in a["sent"]]
            kb = [(s["track"], s["kind"], s["note"], s["vel"], s["len"], s["time"]) for s in b["sent"]]
            check(f"{case}: the same record before and after", ka == kb and a["stock"] == b["stock"],
                  f"{ka} vs {kb}")
        a, b = results["old"]["arp_step"]["sent"][0], results["new"]["arp_step"]["sent"][0]
        check("an arp step's length is N.LEN converted through the lookup (index 20), the same in both",
              a["len"] == b["len"] and a["len"] not in (0, 0x7F), f"length index {a['len']}")
        d = results["new"]["arp_step_defaults"]["sent"][0]
        check("a negative velocity and length resolve to the sound's defaults (90, 20), N.LEN applying only "
              "while the arp runs", d["vel"] == 90, f"velocity {d['vel']}")
    return report()


if __name__ == "__main__":
    sys.exit(main())
