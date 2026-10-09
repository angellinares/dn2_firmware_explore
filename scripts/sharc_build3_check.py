"""build3.asm in digikit's SHARC runner: the pool's levels, built in the idle task, against the model.

    python scripts/sharc_build3_check.py [--set quick|test] [--calls N]

On the section 7 the mod ships (`dnfw.waverider.dsp.section7`), from the engine-init
snapshot: each case's tables go into the load area as pool.c sends them (int16 as
stored, entry j at POOL_RAW + j x 512 KiB), then the request directory (geometry words,
count, generation, the magic last). Then the idle loop's back edge runs, call after call
(`wr_build3` to its JUMP to wr_idle and on to the idle loop's top), until nothing is
left. Checks:

- every built entry's bytes are `table3`'s layout of the model's levels
  (`geometry.table_levels`, rint, clipped to int16): the header exactly, every row
  within 1 LSB (a float32 transform puts a value on the other side of .5 now and then);
- BUILT[j] is the entry's levels | 1 for a playable geometry, 0 for an empty entry or
  one outside 1..64 frames of 64..4096 points;
- each call leaves every R, I, M, L and B register and MODE1 as it found them (the idle
  loop's; the audio interrupt's constants among them);
- no word of DDR is read on the other bus than the one that last wrote it
  (sharc_bus_check: the DM and PM caches are not coherent on the silicon);
- with the magic cleared nothing is built; a new generation rebuilds, and an entry
  being rebuilt reads 0 until its last pair.

Prints the calls, the cycle model's cycles per pair and per table.
"""

from __future__ import annotations

import argparse
import pathlib
import struct
import sys
import tempfile

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import sharc_fft_check as F                                     # noqa: E402
from dnfw import progress, sharcemu                             # noqa: E402
from dnfw.sharccycles import costs as C                         # noqa: E402
from dnfw.waverider import dsp                                  # noqa: E402
from dnfw.waverider import geometry as G                        # noqa: E402
from dnfw.waverider import table3 as T3                         # noqa: E402

m5 = F.m5
UREGS = list(range(0, 80))                         # R0-R15, I0-I15, M0-M15, L0-L15, B0-B15 (digikit codes)
SETS = {
    # (frames, points) per entry; None an empty entry
    "quick": [(16, 512), (5, 64), None, (3, 256), (7, 100), (2, 4096)],
    "test": [(64, 2048), (64, 512), (16, 2048), (16, 512)],   # waverider_geometry_set's tables
    "odd": [(3, 256), (5, 64), (1, 4096)],
    "one": [(1, 4096)],
}


def table(frames: int, n: int, seed: int) -> np.ndarray:
    """Saws near full scale (the levels overshoot: the clip works) plus a little noise."""
    rng = np.random.default_rng(seed)
    t = np.arange(n) / n
    rows = [np.clip(np.rint(31000 * (2 * ((t * (1 + f % 3) + f / max(frames, 1)) % 1.0) - 1)
                            + 600 * rng.standard_normal(n)), -32768, 32767) for f in range(frames)]
    return np.array(rows, dtype=np.int16)


def model(tab: np.ndarray) -> bytes:
    levels = [np.clip(np.rint(lv), -32768, 32767).astype(int) for lv in G.table_levels(tab.astype(float))]
    return T3.dsp_bytes([[list(f) for f in lv] for lv in levels])


def poke_bytes(st, at: int, data: bytes) -> None:
    data = data + bytes(-len(data) % 4)
    for k in range(0, len(data), 4):
        m5.m2.poke(st, at + k, int.from_bytes(data[k:k + 4], "little"))


def read_bytes(st, at: int, n: int) -> bytes:
    """N bytes of DDR, read 16 bits at a time: the runner reads a 32-bit word only half
    written (the table's last int16 can share a word with nothing) as 0."""
    out = bytearray()
    for k in range(0, n, 2):
        v = m5.fx._dm_read(st, at + k, 2)
        out += struct.pack("<H", v.value & 0xFFFF if isinstance(v, m5.fx.Const) else 0)
    return bytes(out[:n])


def directory(st, entries, generation: int, magic: bool = True) -> None:
    words = [(f | n << 16) if g else 0 for g in entries for f, n in [g or (0, 0)]]
    words += [0] * (dsp.POOL_SLOTS - len(words))
    poke_bytes(st, dsp.POOL_DIR + 4, struct.pack("<II", dsp.POOL_SLOTS, generation))
    poke_bytes(st, dsp.POOL_GEOMETRY, struct.pack(f"<{dsp.POOL_SLOTS}I", *words))
    m5.m2.poke(st, dsp.POOL_DIR, dsp.POOL_MAGIC if magic else 0)


def built(st) -> list[int]:
    return [(m5.m2.word(st, dsp.BUILT_DM + 4 * j) or 0) & 0xFFFFFFFF for j in range(dsp.POOL_SLOTS)]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--image", type=pathlib.Path, default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    p.add_argument("--digikit", type=pathlib.Path, default=sharcemu.path())
    p.add_argument("--set", choices=sorted(SETS), default="quick")
    p.add_argument("--calls", type=int, default=2000, help="give up after this many idle calls")
    p.add_argument("--parts", action="store_true", help="the cycle model's largest parts of each long call")
    a = p.parse_args(argv)
    from sharc_bus_check import BusCheck             # noqa: PLC0415
    entries = SETS[a.set]
    dk = m5.m1.Digikit(a.digikit)
    m5.fx.bind(str(a.digikit / "tools"))
    m5.m4.IMAGE = a.image
    stock = m5.m1.dn2_section7(a.image)
    image = m5.Image(dk, dsp.section7(stock))
    costs = C.load(F.COSTS)
    tabs = {j: table(*g, seed=j) for j, g in enumerate(entries) if g}
    ok = True
    pair_cycles: dict[int, list[float]] = {}

    def call(r, what):
        """One pass of the idle loop's back edge -> (runner, changed registers, cycles)."""
        r = r.fresh_call(dsp.BUILD3_SW, return_address=F.RETURN)
        before = {c: r.state.uregs.get(c) for c in UREGS}
        mode1 = r.state.mode1 if hasattr(r.state, "mode1") else None
        with BusCheck(m5.fx) as rec:
            res = m5.fx.run(r, 200_000_000, m5.fixups({}), stop_at=(F.RETURN,))
        if res[0] != "stop":
            raise SystemExit(f"{what}: {res[0]} {res[1]}")
        if rec.count:
            raise SystemExit(f"{what}: " + rec.report())
        changed = [c for c in UREGS if r.state.uregs.get(c) != before[c]]
        if mode1 is not None and r.state.mode1 != mode1:
            changed.append("MODE1")
        cycles, parts, _ = C.estimate(dict(rec.model.counts), costs)
        if a.parts and cycles > 100_000:
            print(f"    {what}: ~{cycles:,.0f} cycles: " + ", ".join(
                f"{k} {v:,.0f}" for k, v in sorted(parts.items(), key=lambda kv: -kv[1])[:8]))
        return r, changed, cycles

    with progress.Job("build3 check", total=4) as job, tempfile.TemporaryDirectory(dir=m5.OUT) as tmp:
        snap, m2mach = m5.snapshot_path(dk, stock, pathlib.Path(tmp))
        r = m5.init_on(snap, m2mach, image)

        # 1. no directory: a call builds nothing and costs a few cycles
        job.update(step="no directory")
        r, changed, cycles = call(r, "no directory")
        quiet = not any(built(r.state)) and not changed
        print(f"  no directory: nothing built, registers kept: {'PASS' if quiet else 'FAIL'} (~{cycles:,.0f} cycles)")
        ok &= quiet
        job.advance()

        # 2. the tables, then the directory with its magic cleared: still nothing
        job.update(step="tables in, magic clear")
        for j, tab in tabs.items():
            poke_bytes(r.state, dsp.POOL_RAW + j * dsp.POOL_RAW_BYTES, tab.astype("<i2").tobytes())
        directory(r.state, entries, 1, magic=False)
        r, changed, _ = call(r, "magic clear")
        held = not any(built(r.state)) and not changed
        print(f"  the magic clear: nothing built: {'PASS' if held else 'FAIL'}")
        ok &= held
        job.advance()

        # 3. generation 1: build everything
        job.update(step="generation 1")
        directory(r.state, entries, 1)
        calls, kept, zero_while = 0, True, True
        while calls < a.calls:
            j = (m5.m2.word(r.state, dsp.BUILD_STATE_DM + 4) or 0)
            if j >= dsp.POOL_SLOTS:
                break
            r, changed, cycles = call(r, f"call {calls + 1}")
            calls += 1
            kept &= not changed
            if changed:
                print(f"    call {calls}: changed {changed}")
            f_after = m5.m2.word(r.state, dsp.BUILD_STATE_DM + 8) or 0
            if j < len(entries) and entries[j] and f_after:      # mid-table: not named yet
                zero_while &= built(r.state)[j] == 0
            if j < len(entries) and entries[j]:
                pair_cycles.setdefault(j, []).append(cycles)
        print(f"  generation 1: {calls} calls; every call kept the registers: {'PASS' if kept else 'FAIL'}; "
              f"an entry under way reads 0: {'PASS' if zero_while else 'FAIL'}")
        ok &= kept and zero_while and calls < a.calls
        b = built(r.state)
        for j, g in enumerate(entries):
            slot = dsp.LEVELS_AT + j * dsp.LEVELS_SLOT
            playable = g is not None and T3.playable(*g)
            want_ptr = slot | 1 if playable else 0
            line = f"    entry {j} {('%d x %d' % g) if g else 'empty':>10s}: BUILT {b[j]:#010x}"
            good = b[j] == want_ptr
            if playable:
                want = model(tabs[j])
                got = read_bytes(r.state, slot, len(want))
                head_ok = got[:T3.HEADER_BYTES] == want[:T3.HEADER_BYTES]
                gw = np.frombuffer(got[T3.HEADER_BYTES:], "<i2").astype(int)
                ww = np.frombuffer(want[T3.HEADER_BYTES:], "<i2").astype(int)
                worst = int(np.max(np.abs(gw - ww)))
                good &= head_ok and worst <= 1
                if worst > 1:
                    fr, pts = g
                    at = 0
                    for k in range(G.levels(pts)):
                        width = T3.row_bytes(pts, k) // 2
                        for f in range(fr):
                            d = int(np.max(np.abs(gw[at:at + width] - ww[at:at + width])))
                            if d > 1:
                                print(f"      level {k} frame {f}: {d} LSB")
                            at += width
                per = pair_cycles.get(j, [])
                line += (f", header {'=' if head_ok else '!='} table3's, rows {len(gw):,} int16, largest difference "
                         f"{worst} LSB; ~{sum(per):,.0f} cycles in {len(per)} calls")
            print(line + f"  {'PASS' if good else 'FAIL'}")
            ok &= good
        b1 = b
        job.advance()

        # 4. generation 2: everything again, entry 0 cleared while it is rebuilt
        job.update(step="generation 2")
        directory(r.state, entries, 2)
        first = entries[0] and T3.playable(*entries[0]) and entries[0][0] > 2
        r, changed, _ = call(r, "generation 2, first call")
        cleared = (built(r.state)[0] == 0) if first else True
        n = 1
        while (m5.m2.word(r.state, dsp.BUILD_STATE_DM + 4) or 0) < dsp.POOL_SLOTS and n < a.calls:
            r, changed, _ = call(r, f"generation 2, call {n + 1}")
            n += 1
        again = built(r.state) == b1 and cleared
        print(f"  generation 2: {n} calls; entry 0 read 0 while rebuilt, then all as before: {'PASS' if again else 'FAIL'}")
        ok &= again
        job.advance()
    print("  PASS" if ok else "  FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
