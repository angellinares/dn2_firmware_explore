"""Which of the reply's 28 x 24-bit channels carries track 0's audio (page 4's scope).

    python scripts/sharc_reply_channels.py

Runs 6 blocks in digikit's SHARC runner with a note on a Waverider track 0, then reads
both reply pages (DM 0x2c49d0 + page << 12, 0xabc bytes) and correlates each of the
32 records' 28 channels, both byte orders, against the track buffer and the amp's
output. Result 2026-10-07: every record is 0; the runner's call doesn't fill them
(docs/waverider-pages34.md, "The scope's data"). Writes out/waverider/reply_probe.json.
"""
import sys, pathlib, json, tempfile, os
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
import sharc_waverider_m5 as g
from dnfw.waverider import dsp
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from dnfw import sharcemu  # noqa: E402
dkp = sharcemu.path()
dk = g.m1.Digikit(dkp); g.fx.bind(str(dkp / "tools"))
image = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
g.m4.IMAGE = image
stock = g.m1.dn2_section7(image)
sound, machines = g.m4.init_sound(image)
wr = g.Image(dk, dsp.section7(stock))
out = {}
with tempfile.TemporaryDirectory(dir=g.OUT) as tmp:
    snap, m2mach = g.snapshot_path(dk, stock, pathlib.Path(tmp))
    init = g.init_on(snap, m2mach, wr)
    def fb(b):
        return g.base_frame(sound, machines, trigger=(b == 1), overrides={g.WAV1: 0x4000}).to_bytes()
    pages = []
    def at_count(r):   # start of a block: the reply the previous block left
        pages.append([bytes((g.m2.word(r.state, 0x2C49D0 + (p << 12) + 4 * k) or 0).to_bytes(4, "little"))
                      for p in (0, 1) for k in range(0xABC // 4)])
    run = g.run_blocks(init, fb, 6, extra_hooks={dsp.COUNT_SW: at_count})
    print("ok", run["ok"], len(pages))
    st = run["state"].state
    page = g.m2.word(st, g.REPLY_PAGE_DM)
    raws = []
    for p in (0, 1):
        raws.append(b"".join((g.m2.word(st, 0x2C49D0 + (p << 12) + 4 * k) or 0).to_bytes(4, "little") for k in range(0xABC // 4)))
    last = run["buffers"][-1][0]; amp = run["amp_out"][-32:]
    print("page word", page, "track0 buf peak", max(map(abs, last)), "amp_out peak", max(map(abs, amp)))
    def chans(raw, order):
        recs = []
        for k in range(32):
            rec = raw[0x1C + 84 * k: 0x1C + 84 * (k + 1)]
            row = []
            for c in range(28):
                b3 = rec[3 * c: 3 * c + 3]
                v = int.from_bytes(b3, order, signed=True)
                row.append(v)
            recs.append(row)
        return recs
    import math
    def corr(a, b):
        ma, mb = sum(a) / len(a), sum(b) / len(b)
        sa = math.sqrt(sum((x - ma) ** 2 for x in a)); sb = math.sqrt(sum((y - mb) ** 2 for y in b))
        return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sa * sb) if sa and sb else 0
    for p, raw in enumerate(raws):
        for order in ("little", "big"):
            recs = chans(raw, order)
            for c in range(28):
                col = [recs[k][c] for k in range(32)]
                if any(col):
                    for name, ref in (("buf", last), ("amp", amp)):
                        r = corr(col, ref)
                        if abs(r) > 0.8:
                            print(f"page {p} {order} ch {c}: corr {name} {r:.3f} col {col[:4]} ref {[round(x,4) for x in ref[:4]]}")
            nz = sum(1 for k in range(32) for c in range(28) if recs[k][c])
            print(f"page {p} {order}: nonzero cells {nz}")
    json.dump({"raw0": raws[0].hex(), "raw1": raws[1].hex(), "buf": last, "amp": amp}, open(g.OUT / "reply_probe.json", "w"))
