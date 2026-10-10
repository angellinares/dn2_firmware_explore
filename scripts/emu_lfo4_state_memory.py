"""LFO4's state arrays in the heap's first block: boot, then a project save, in the emulator.

    python scripts/emu_lfo4_state_memory.py BUILD.syx [--stock STOCK.syx] [--out DIR]

Until 2026-10-11 the arrays sat at 0x46700000, inside stock's eMMC bounce buffer
(0x4e6f1300, the uncached window of RAM 0x466f1300), and every project saved on an LFO4
unit carried LFO state (docs/lfo4-state-memory.md). They now live in the first block of
stock's heap, taken by `reserve` (scripts/build_lfo4_tick.py) when the allocator
initialises.

One panel_drive boot from reset. After the boot the three arrays are filled with a
marker, standing in for the state the evaluator writes (it does not run here), and the
project is saved with SAVE PROJECT AS. Every return of the allocator is recorded.

| check | pass |
|---|---|
| the first block the allocator returns | the arena's base, to `reserve` |
| every later block recorded | outside the 16 KiB the arrays live in |
| the arrays after the save | still the marker: stock wrote nothing there |
| the save | seen: a project's worth of eMMC writes, the bounce buffer not empty |
| the marker in the bounce buffer | absent |

panel_drive keeps the first 4,096 register records, and a boot and a save make about
38,000 allocations. The later ones are covered by the marker: a block handed out inside
the arrays would be written by whoever asked for it.

`--stock` runs stock beside it: there the first block goes to stock's own caller, so
without `reserve` the memory is stock's to hand out, and the check above means something.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_lfo4_tick as tick                              # noqa: E402

PANEL = ROOT.parent / "digikit-rust/out/native/target-host/release/examples/panel_drive.exe"
CARD = ROOT.parent / "dn2_firmware/out/dk-dn2-card.img"

BLOCK = 0x4000                                              # what the allocator makes of RESERVE
ARRAYS = (tick.LIVE, tick.SECOND, tick.BACKUP)
MARKER = b"LFO4" * (tick.STATE_LEN // 4)
ALLOC_RETURN = 0x401201BA                                   # the allocator's rts: %d0 is the block
EMMC_WRITE = 0x4012C780
BOUNCE = 0x4E6F1300
IMAGE_BYTES, PIECE = 12_890_116, 0x10000
PIECES = -(-IMAGE_BYTES // PIECE)                           # 197 eMMC writes a project
NO, SETTINGS, YES, DOWN = 12, 8, 10, 14
SAVE_AS = [f"tap:{NO}", "wait:30M", f"tap:{SETTINGS}", "wait:30M", f"tap:{YES}", "wait:30M",
           f"tap:{DOWN}", "wait:20M", f"tap:{YES}", "wait:60M", f"tap:{DOWN}", "wait:20M",
           f"tap:{YES}", "wait:60M", f"tap:{YES}", "wait:900M"]


def steps(marked: bool) -> list[str]:
    arrays = [f"peek:0x{a:08x}:{tick.STATE_LEN}" for a in ARRAYS]
    pokes = [f"poke:0x{a:08x}:{MARKER.hex()}" for a in ARRAYS] if marked else []
    return pokes + SAVE_AS + arrays + [f"peek:0x{BOUNCE:08x}:{PIECE}"]


def run(build: str, out: pathlib.Path, marked: bool) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    card = out / "card.img"
    shutil.copyfile(CARD, card)                             # the save writes the card: never the shared one
    script = out / "steps"
    script.write_text("\n".join(steps(marked)) + "\n", newline="\n")
    r = subprocess.run([str(PANEL), build, "--card-image", str(card), "--out", str(out),
                        "--regs-at", f"0x{ALLOC_RETURN:08x}", "--count", f"0x{EMMC_WRITE:08x}",
                        "--steps", f"@{script}"],
                       capture_output=True, text=True, timeout=3000, stdin=subprocess.DEVNULL)
    if not r.stdout.strip():
        raise SystemExit(f"{build}: no output: {r.stderr[-800:]}")
    d = json.loads(r.stdout.strip().splitlines()[-1])
    if d["outcome"] != "done":
        raise SystemExit(f"{build}: {d['outcome']} {d['fault']}")
    peeks = [bytes.fromhex(x["hex"]) for x in d["results"] if "hex" in x]
    blocks = [(int(x["d"][0], 16), int(x["stack"][0], 16)) for x in d["regs"]]
    return {"arrays": peeks[:3], "bounce": peeks[3], "blocks": blocks,
            "dropped": d.get("regs_dropped", 0), "writes": {w["pc"]: w["hits"] for w in d["watched"]}}


def report(name: str, checks: dict[str, bool]) -> bool:
    for what, ok in checks.items():
        print(f"  {'ok  ' if ok else 'FAIL'} {name}: {what}")
    return all(checks.values())


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("build")
    p.add_argument("--stock", help="stock 1.11 (or a probe build of it), run beside it as the control")
    p.add_argument("--out", default=str(ROOT / "out/lfo4-state-memory"))
    a = p.parse_args(argv)

    r = run(a.build, pathlib.Path(a.out) / pathlib.Path(a.build).stem, marked=True)
    first, later = r["blocks"][0], r["blocks"][1:]
    inside = [b for b, _ in later if tick.POOL <= b < tick.POOL + BLOCK]
    writes = r["writes"].get(f"0x{EMMC_WRITE:08x}", 0)
    ok = report("lfo4", {
        f"the first block is the arena's base, {first[0]:#010x}": first[0] == tick.POOL,
        f"and it went to `reserve` (return address {first[1]:#010x})": 0x402DFA1C <= first[1] < 0x402DFA1C + 896,
        f"none of the {len(later)} later blocks recorded is inside the arrays' 16 KiB "
        f"({r['dropped']} more not recorded)": not inside,
        "the arrays still hold the marker after the save": all(x == MARKER for x in r["arrays"]),
        f"the save was seen: {writes} eMMC writes (a project is {PIECES} pieces), the bounce buffer not empty":
            writes >= PIECES and any(r["bounce"]),
        "the marker is not in the bounce buffer": MARKER[:16] not in r["bounce"],
    })
    if a.stock:
        s = run(a.stock, pathlib.Path(a.out) / pathlib.Path(a.stock).stem, marked=False)
        first = s["blocks"][0]
        ok &= report("stock", {
            f"the first block is the arena's base, {first[0]:#010x}": first[0] == tick.POOL,
            f"and it went to stock's own caller (return address {first[1]:#010x})":
                not 0x402DFA1C <= first[1] < 0x402DFA1C + 896,
        })
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
