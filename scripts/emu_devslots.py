"""The /devslots route in the emulator, with stock firmware beside it as the control.

    python scripts/emu_devslots.py BUILD.syx [--stock STOCK.syx] [--card out/devslots/card.img]

Through digikit's sysex_bridge, DNX's own frames (docs/for-dnx-devslots.md). The card is
a copy of out/dk-dn2-card.img with a different marker in each slot's bytes 32..47 (made
here when missing), so a swapped or stale read shows:
1. `/` lists `devslots`, after `modinfo`; `/devslots` lists 0 `slot-40000`, 1 `slot-48000`
   and 2 `ram`, used;
2. `/devslots/0` and `/1` are the card's sectors 0x40000 and 0x48000, 272 bytes, byte for
   byte, each with its own marker;
3. `/devslots/2` is a settings block (`COKi`), not either slot (the card's slots are an
   old version, so the unit starts from defaults);
4. a write to `/devslots/0` is refused, and slot 0 reads back unchanged; `/devslots/3` is
   refused;
5. the control, stock 1.11: `/` has no `devslots`, and the open of `/devslots/0` is answered
   with the stock refusal.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import struct
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from emu_modinfo import STOCK, container                  # noqa: E402
from emu_waverider_rename import ARGS, BRIDGE, Frames, dec   # noqa: E402
from emu_waverider_wavepool import listing                # noqa: E402

BYTES = 272
SECTORS = (0x40000, 0x48000)
MARKS = (b"DEVSLOTS-TEST-A0", b"DEVSLOTS-TEST-B1")
MARK_AT = 32
PIECES = 1 + (31 + BYTES + 12 + 15) // 16


def make_card(card: pathlib.Path) -> None:
    card.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "out/dk-dn2-card.img", card)
    with open(card, "r+b") as f:
        for sector, mark in zip(SECTORS, MARKS):
            f.seek(sector * 512 + MARK_AT)
            f.write(mark)


def card_slots(card: pathlib.Path) -> list[bytes]:
    with open(card, "rb") as f:
        out = []
        for sector in SECTORS:
            f.seek(sector * 512)
            out.append(f.read(BYTES))
        return out


def run(build: str, card: str, f: Frames) -> dict:
    proc = subprocess.run([str(BRIDGE), build, *ARGS, "--card-image", card],
                          input="\n".join(h for _, h in f.lines) + "\n",
                          capture_output=True, text=True, timeout=3600)
    out = [json.loads(x) for x in proc.stdout.splitlines() if x.startswith("{") and '"request"' in x]
    if len(out) != len(f.lines):
        raise SystemExit(f"FAIL: the bridge answered {len(out)} of {len(f.lines)}: {proc.stderr[-2000:]}")
    return {label: o["replies"] for (label, _), o in zip(f.lines, out)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("build")
    ap.add_argument("--stock", default=str(STOCK))
    ap.add_argument("--card", type=pathlib.Path, default=ROOT / "out/devslots/card.img")
    a = ap.parse_args()
    if not a.card.exists():
        make_card(a.card)
    want = card_slots(a.card)

    f = Frames()
    f.frame("root", 0x53, b"/\0")
    f.frame("list", 0x53, b"/devslots\0")
    for i in range(3):
        f.read(f"r{i}", f"/devslots/{i}", PIECES)
    f.write("w0", "/devslots/0", container(bytes(BYTES), 0x53))
    f.read("r0b", "/devslots/0", PIECES)
    f.frame("open3", 0x54, b"/devslots/3\0")
    replies = run(a.build, str(a.card), f)

    s = Frames()
    s.frame("root", 0x53, b"/\0")
    s.frame("open0", 0x54, b"/devslots/0\0")
    stock = run(a.stock, str(a.card), s)

    def answer(rep, label):
        return dec(rep[label][0])[5:] if rep[label] else b""

    def read_back(label):
        raw = b"".join(answer(replies, f"{label}:chunk{k}")[22:] for k in range(1, PIECES))
        at = raw.find(bytes.fromhex("ac11d303"))
        return (raw[at:at + 31], raw[at + 31:at + 31 + BYTES]) if at >= 0 else (b"", b"")

    ok = True

    def check(what, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + what + (f"  ({detail})" if detail else ""))

    root = [n for _, n, _ in listing(replies["root"][0])]
    check("/ lists devslots after modinfo", root[-2:] == ["modinfo", "devslots"], root)
    lst = listing(replies["list"][0])
    check("/devslots lists 0 slot-40000, 1 slot-48000, 2 ram, used",
          lst == [(0, "slot-40000", 1), (1, "slot-48000", 1), (2, "ram", 1)], lst)

    got = [read_back(f"r{i}") for i in range(3)]
    for i in range(2):
        head, body = got[i]
        check(f"/devslots/{i} is sector {SECTORS[i]:#x}'s first {BYTES} bytes, byte for byte",
              body == want[i] and MARKS[i] in body, f"{len(body)} B, {body[:48].hex()}")
        check(f"  its container: kind 0x53, version 1, {BYTES} bytes, raw",
              len(head) == 31 and struct.unpack(">III", head[13:25])[:2] == (0x53, 1)
              and struct.unpack(">I", head[25:29])[0] == BYTES and head[29] == 0, head.hex())
    ram = got[2][1]
    check("/devslots/2 is a settings block (COKi) and neither slot",
          len(ram) == BYTES and ram[:4] == b"COKi" and ram not in want, ram[:32].hex())
    print("  the running copy's header:", ram[:16].hex())

    w_open, w_first = answer(replies, "w0:open"), answer(replies, "w0:chunk0")
    check("a write is refused (the session's Permission denied, or the route's read-only)",
          any(b"Permission denied" in m or b"read-only" in m for m in (w_open, w_first)), (w_open[:60], w_first[:60]))
    check("and slot 0 reads back unchanged", read_back("r0b")[1] == want[0])
    check("the card's slots are unchanged after the run", card_slots(a.card) == want)
    o3 = answer(replies, "open3")
    check("/devslots/3 is refused", b"files are 0, 1 and 2" in o3, o3[:80])

    sroot = [n for _, n, _ in listing(stock["root"][0])]
    check("control, stock 1.11: / has no devslots", "devslots" not in sroot, sroot)
    s_open = answer(stock, "open0")
    check("control: the open of /devslots/0 is answered (a refusal, not silence)", bool(s_open), s_open.hex())
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
