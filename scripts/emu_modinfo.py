"""The /modinfo route in the emulator, with stock firmware beside it as the control.

    python scripts/emu_modinfo.py BUILD.syx [--stock STOCK.syx] [--card out/dk-dn2-card.img]

Through digikit's sysex_bridge, DNX's own frames (docs/for-dnx-modinfo.md):
1. `/` lists `modinfo`, after `wavepool`; `/modinfo` lists index 0, `info`, used, 256 bytes;
2. a read of `/modinfo/0` is the record the build wrote into the image, byte for byte
   (dnfw.mods.modinfo, from the build's own MAIN OS): magic, hash, the capabilities, the
   pool's 128 slots and record version 2, the mods, the tag, the image id;
3. a write to `/modinfo/0` is refused (the session's own "Write: Permission denied", as the
   file is listed write-protected), and the record reads back unchanged;
4. `/modinfo/1` is refused;
5. the control, stock 1.11: `/` has no `modinfo`, and the open of `/modinfo/0` is
   answered with the stock refusal, which this prints in full: the answer DNX reads
   as "not supported", as opposed to no answer at all.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import struct
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dnfw.mods import modinfo as MI                       # noqa: E402
from emu_waverider_rename import ARGS, BRIDGE, Frames, crc0, dec   # noqa: E402
from emu_waverider_wavepool import listing                # noqa: E402

PIECES = 1 + (31 + MI.BYTES + 12 + 15) // 16
STOCK = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist/Digitone_II_OS1.11.syx"


def container(body: bytes, kind: int, version: int = 1) -> bytes:
    """the transfer container, as emu_waverider_wavepool builds it"""
    head = (bytes.fromhex("ac11d303" "02000500" "0f") + b"0059"
            + struct.pack(">IIII", kind, version, 0, len(body)) + bytes([0, 12]))
    whole = head + body
    return whole + struct.pack(">II", crc0(whole[0x1F:]), len(body)) + bytes.fromhex("aaa1daaa")


def built_record(build: pathlib.Path) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["dnfw", "extract", str(build), "-o", tmp], capture_output=True, check=True, timeout=600)
        main = next(pathlib.Path(tmp).glob("section_3_*.bin")).read_bytes()
    at = main.find(MI.MAGIC + struct.pack(">HH", MI.VERSION, MI.BYTES))
    return main[at:at + MI.BYTES] if at >= 0 else b""


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
    ap.add_argument("--card", default=str(ROOT / "out/dk-dn2-card.img"))
    a = ap.parse_args()

    f = Frames()
    f.frame("root", 0x53, b"/\0")
    f.frame("list", 0x53, b"/modinfo\0")
    f.read("r0", "/modinfo/0", PIECES)
    f.write("w0", "/modinfo/0", container(bytes(MI.BYTES), 0x4D))
    f.read("r1", "/modinfo/0", PIECES)
    f.frame("open1", 0x54, b"/modinfo/1\0")
    replies = run(a.build, a.card, f)

    s = Frames()
    s.frame("root", 0x53, b"/\0")
    s.frame("open0", 0x54, b"/modinfo/0\0")
    stock = run(a.stock, a.card, s)

    def answer(rep, label):
        return dec(rep[label][0])[5:] if rep[label] else b""

    def read_back(label):
        raw = b"".join(answer(replies, f"{label}:chunk{k}")[22:] for k in range(1, PIECES))
        at = raw.find(bytes.fromhex("ac11d303"))
        return (raw[at:at + 31], raw[at + 31:at + 31 + MI.BYTES]) if at >= 0 else (b"", b"")

    ok = True

    def check(what, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + what + (f"  ({detail})" if detail else ""))

    root = [n for _, n, _ in listing(replies["root"][0])]
    check("/ lists modinfo after wavepool", root[-2:] == ["wavepool", "modinfo"], root)
    lst = listing(replies["list"][0])
    check("/modinfo lists index 0, info, used", lst == [(0, "info", 1)], lst)

    want = built_record(pathlib.Path(a.build))
    head, rec = read_back("r0")
    info = MI.parse(rec) if len(rec) == MI.BYTES else {}
    check("/modinfo/0 reads the record the build wrote, byte for byte", rec and rec == want,
          f"{len(rec)} B, {len(want)} B in the image")
    check("its container: kind 0x4D, version 1, 256 bytes, raw",
          len(head) == 31 and struct.unpack(">III", head[13:25])[:2] == (0x4D, 1)
          and struct.unpack(">I", head[25:29])[0] == MI.BYTES and head[29] == 0, head.hex())
    check("the record checks out and is filled: magic, version, hash", info.get("ok") and info.get("filled"), info)
    check("capabilities: store, pool, rename, pool_cas, page",
          info.get("capabilities") == ["store", "pool", "rename", "pool_cas", "page"], info.get("capabilities"))
    check("names: the pool keeps 15 characters, TBL's header shows 14",
          (info.get("name_kept"), info.get("name_shown")) == (15, 14), (info.get("name_kept"), info.get("name_shown")))
    check("pool: 128 slots, record version 2; store: 256 slots",
          (info.get("pool_slots"), info.get("pool_version"), info.get("store_slots")) == (128, 2, 256))
    check("the mods include waverider", any(m == "waverider" for m, _ in info.get("mods", [])), info.get("mods"))

    w_open, w_first = answer(replies, "w0:open"), answer(replies, "w0:chunk0")
    # the session itself refuses: the file is listed write-protected (0x12), so the
    # header check (modinfo is read-only) is only the second line of defence
    check("a write is refused (the session's Permission denied, or the route's read-only)",
          any(b"Permission denied" in m or b"read-only" in m for m in (w_open, w_first)), (w_open[:60], w_first[:60]))
    _, rec1 = read_back("r1")
    check("and the record reads back unchanged", rec1 == rec)
    o1 = answer(replies, "open1")
    check("/modinfo/1 is refused", b"only file is 0" in o1, o1[:80])

    sroot = [n for _, n, _ in listing(stock["root"][0])]
    check("control, stock 1.11: / has no modinfo", "modinfo" not in sroot and "waverider" not in sroot, sroot)
    s_open = answer(stock, "open0")
    check("control: the open of /modinfo/0 is answered (a refusal, not silence)", bool(s_open), s_open.hex())
    print("  stock's answer to the open, for DNX:", s_open.hex(), repr(s_open))
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
