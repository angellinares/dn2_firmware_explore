"""DNX's pool files through the firmware: written, read back, compared byte for byte.

    python scripts/emu_wavepool_vectors.py BUILD.syx DIR [--card out/dk-dn2-card.img] [--out DIR2]

Each DIR/*.bin is a whole /wavepool file from DNX's codec (31-byte container header, the
512-byte record, the 12-byte trailer), written as DNX writes it to the project slot its
header names, then read back. A firmware read differs from what was written in the
generation only, which the firmware assigns (spec §2): so the read-back, with its
generation set to the sent one and the record hash and trailer recomputed, must equal
the sent file byte for byte. A version 1 file (rev 3, 127 entries) is stored as version 2
(rev 4), so it must equal the sent file converted: the same entries and an empty 128th,
both version fields 2. The firmware's own read-backs go to --out, unaltered, for DNX to
pin. On an empty store an automatic record reads back with no entries, so it compares as
sent too.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import struct
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dnfw.waverider import poolrecord as PR                             # noqa: E402
from dnfw.waverider import store as S                                   # noqa: E402
from emu_waverider_rename import ARGS, BRIDGE, Frames, crc0, dec        # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("build")
    ap.add_argument("dir")
    ap.add_argument("--card", default=str(ROOT / "out/dk-dn2-card.img"))
    ap.add_argument("--out", default=str(ROOT / "out/wavepool_vectors"))
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    files = sorted(pathlib.Path(a.dir).glob("*.bin"))

    f = Frames()
    plan = []
    for path in files:
        data = path.read_bytes()
        p = struct.unpack_from(">I", data, 0x15)[0]
        f.write(path.stem, f"/wavepool/{p}", data)
        f.handle += 1
        f.frame(path.stem + ":open", 0x54, f"/wavepool/{p}\0".encode() + struct.pack(">I", 0x4000))
        f.frame(path.stem + ":seq1", 0x55, struct.pack(">II", f.handle, 1))
        plan.append((path, p, data))
    proc = subprocess.run([str(BRIDGE), a.build, *ARGS, "--card-image", a.card],
                          input="\n".join(h for _, h in f.lines) + "\n",
                          capture_output=True, text=True, timeout=1800)
    got = [json.loads(x) for x in proc.stdout.splitlines() if '"request"' in x]
    replies = {label: o["replies"] for (label, _), o in zip(f.lines, got)}
    ok = len(got) == len(f.lines)
    for path, p, sent in plan:
        d = dec(replies[path.stem + ":seq1"][0])[5:] if replies.get(path.stem + ":seq1") else b""
        length = struct.unpack_from(">I", d, 18)[0] if len(d) >= 22 else 0
        back = d[22:22 + length]
        (out / path.name).write_bytes(back)
        gen_back = struct.unpack_from(">I", back, 31 + 8)[0] if len(back) == 555 else None
        # the read-back with the sent generation: record hash, then the trailer's CRC
        fixed = bytearray(back)
        if len(fixed) == 555:
            fixed[31 + 8:31 + 12] = sent[31 + 8:31 + 12]
            fixed[31 + 508:31 + 512] = struct.pack(">I", S.xxh32(bytes(fixed[31:31 + 508])))
            fixed[543:547] = struct.pack(">I", crc0(bytes(fixed[31:543])))
        want = sent
        if struct.unpack_from(">H", sent, 31 + 4)[0] == 1:          # version 1: as converted
            rec, _ = PR.from_bytes(sent[31:31 + 512])
            body = rec.to_bytes(count=struct.unpack_from(">H", sent, 31 + 12)[0])
            w = bytearray(sent)
            w[0x11:0x15] = struct.pack(">I", PR.VERSION)
            w[31:31 + 512] = body
            w[543:547] = struct.pack(">I", crc0(bytes(w[31:543])))
            want = bytes(w)
        same = bytes(fixed) == want
        first_diff = next((i for i in range(min(len(fixed), len(want))) if fixed[i] != want[i]), None)
        ok &= same
        print(f"{'PASS' if same else 'FAIL'} {path.name}: project slot {p}, {len(back)} bytes back, "
              f"generation {gen_back}" + ("" if same else f", first difference at {first_diff}"))
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
