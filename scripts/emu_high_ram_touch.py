"""Which megabytes above stock's data does stock touch, under any address? In the emulator.

    python scripts/emu_high_ram_touch.py STOCK.syx [--out DIR]

The mods live in RAM above stock's DMA section (`0x46701340..0x48000000`). The SDRAM is
128 MB and its decode repeats it every 0x08000000 up to `0x8c000000`, so the same RAM has
nine addresses; stock reaches its DMA section through the second (`0x4e......`).

digikit's board keeps RAM in 1 MiB pages and maps a page the first time the guest touches
it, recording that first touch (panel_drive's `touched` step). So after a run the list is
the megabytes stock touched, in every window, with no list of addresses to get wrong.
One panel_drive boot of plain stock, a project save and a walk through the panel's pages;
then the same run again to read whole the pages that fall in `0x46700000..0x48000000`.

Controls, pages stock is known to touch: `0x46600000` (the end of its data) and
`0x4e600000` (the eMMC bounce buffer, `0x4e6f1300`). Both must answer, or a silent page
means nothing.

What this does not cover: anything the emulator does not run (the sequencer, the audio
engine's full path, USB audio), and a touch finer than a megabyte: a page that answers is
then read whole and its non-zero extent printed.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
PANEL = ROOT.parent / "digikit-rust/out/native/target-host/release/examples/panel_drive.exe"
CARD = ROOT.parent / "dn2_firmware/out/dk-dn2-card.img"    # opened read-only: the save goes to an overlay in memory

MIB, WINDOW = 0x100000, 0x08000000
LO, HI = 0x46700000, 0x48000000
STOCK_DMA_END = 0x46701340
CONTROLS = (0x46600000, 0x4E600000)
NO, SETTINGS, YES, DOWN = 12, 8, 10, 14
SAVE_AS = [f"tap:{NO}", "wait:30M", f"tap:{SETTINGS}", "wait:30M", f"tap:{YES}", "wait:30M",
           f"tap:{DOWN}", "wait:20M", f"tap:{YES}", "wait:60M", f"tap:{DOWN}", "wait:20M",
           f"tap:{YES}", "wait:60M", f"tap:{YES}", "wait:900M"]
# every page key, the preset and kit menu, pattern and song, play, record, stop
WALK = [s for key in (1, 2, 3, 4, 5, 6, 7, 12, 23, 12, 24, 12, 20, 19, 21, 21, 8, 12)
        for s in (f"tap:{key}", "wait:40M")]


def run(build: str, out: pathlib.Path, peeks: list[int]) -> tuple[list[dict], dict[int, bytes]]:
    """One boot and the scenario; then the pages touched, and each of PEEKS read whole."""
    out.mkdir(parents=True, exist_ok=True)
    steps = SAVE_AS + WALK + ["touched"] + [f"peek:0x{a:08x}:{MIB}" for a in peeks]
    script = out / "steps"
    script.write_text(chr(10).join(steps) + chr(10), newline=chr(10))
    r = subprocess.run([str(PANEL), build, "--card-image", str(CARD), "--out", str(out), "--steps", f"@{script}"],
                       capture_output=True, text=True, timeout=3600, stdin=subprocess.DEVNULL)
    if not r.stdout.strip():
        raise SystemExit(f"no output: {r.stderr[-800:]}")
    d = json.loads(r.stdout.strip().splitlines()[-1])
    if d["outcome"] != "done":
        raise SystemExit(f"{d['outcome']} {d.get('fault')}")
    touched = next(x["touched"] for x in d["results"] if "touched" in x)
    whole = [bytes.fromhex(x["hex"]) for x in d["results"] if "hex" in x]
    return touched, dict(zip(peeks, whole))


def ram(address: int) -> int:
    """The RAM address behind ADDRESS, whichever window it is in."""
    return 0x40000000 + (address - 0x40000000) % WINDOW


def extent(data: bytes) -> str:
    first = next((i for i, b in enumerate(data) if b), None)
    if first is None:
        return "all zero"
    last = max(i for i, b in enumerate(data) if b)
    return f"non-zero +{first:#x}..+{last:#x} ({sum(1 for b in data if b):,} bytes)"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("build")
    p.add_argument("--out", default=str(ROOT / "out/high-ram-touch"))
    a = p.parse_args(argv)
    out = pathlib.Path(a.out)
    touched, _ = run(a.build, out, [])
    pages = {int(t["page"], 16): t for t in touched}
    ok = True
    for c in CONTROLS:
        ok &= c in pages
        print(f"  {'ok  ' if c in pages else 'FAIL'} control: page {c:#010x} is among the {len(pages)} touched")
    high = sorted(page for page in pages if LO <= ram(page) < HI)
    _, whole = run(a.build, out, high)                      # the same run again, those pages read whole
    beyond = []
    print(f"  touched pages whose RAM is in {LO:#010x}..{HI:#010x}, under any address: {len(high)}")
    for page in high:
        t, data = pages[page], whole[page]
        above = ram(page) != LO or any(data[STOCK_DMA_END - LO:])
        beyond += [page] if above else []
        print(f"    {page:#010x} (RAM {ram(page):#010x}): first {t['kind']} of {t['addr']} at pc {t['pc']}; "
              f"{extent(data)}; {'ABOVE the DMA section' if above else 'inside the DMA section'}")
    print("  stock touched nothing above its DMA section" if not beyond else
          f"  STOCK TOUCHED RAM ABOVE ITS DMA SECTION: {[hex(x) for x in beyond]}")
    by_window = {}
    for page in pages:
        by_window.setdefault((page - 0x40000000) // WINDOW, []).append(page)
    for k in sorted(by_window):
        v = sorted(by_window[k])
        print(f"  window {0x40000000 + k * WINDOW:#010x}: {len(v)} pages, {v[0]:#010x}..{v[-1] + MIB - 1:#010x}")
    print("PASS" if ok and not beyond else "FAIL")
    return 0 if ok and not beyond else 1


if __name__ == "__main__":
    raise SystemExit(main())
