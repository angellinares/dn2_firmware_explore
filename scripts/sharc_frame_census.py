"""A read census of the ColdFire frame on the stock DSP: which frame words are read, and by what.

Runs the unmodified section 7 of OS 1.12 (the same bytes as 1.11) in digikit's runner over blocks whose frames carry
random words, with read watchpoints over the whole frame twice (where it lands in the receive
page, and in the DSP's frame copy). Every read is recorded by frame word and PC, so a word's
consumers are named. The method follows naturarum/dn2-cfw notes/T6.0 section 1.2 (their
interpreter is faster; the cases here are ours, seeded).

    # one case group, in this process
    python scripts/sharc_frame_census.py run --machine 1 --filters 0,1,2 --blocks 4 --seed 7 --out out/census/m1.json
    # many groups in parallel, then the map
    python scripts/sharc_frame_census.py all --blocks 4 --jobs 10 --out out/census
    python scripts/sharc_frame_census.py report out/census [--word 0x2a --word 0xa18]

A case is one machine type on all 16 tracks (0..4), one filter type (0..5), a note on, and
every payload word from 0x34 up random except the structural header words. `report` merges
the groups: words never read, words read only by the unpack copy loops, and the consumers.
"""
import argparse
import collections
import json
import pathlib
import random
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

FRAME_COPY = 0x25C48C
PAYLOAD = 0xA80                     # the frame's payload bytes (the copy is 672 32-bit words)
FRAME_LEN = 0xABC                   # what the SPI carries each way: the payload and a 30-word tail
# regions of the frame, as naturarum/dn2-cfw notes/T3.3 lays it out (byte offsets)
HEADER_FLAGS = (0x22, 0x34)         # handler locals and settings words
VOICE_SLOTS = (0xDA, 0x9FA)         # 16 per-voice slots of 0x92 bytes
FX_BLOCK = (0x9FA, 0xA54)           # the global FX block
OWNERS = (0xA5A, 0xA7A)             # owner track of each row
COPY_LOOPS = {0x1C287D, 0x1C3030}   # the two unpack copy loops (naturarum T6.0 1.2)
RANDOM_FROM = 0x34                  # words below carry the structural header
OWNERS = 0xA5A                      # row r's owning track at +2r: the voice-mix loops' I0 = 0x258f68 + 0x100 x owner (naturarum T6.0c 4.1)
ALIAS = 0x28000000                  # the memory layer's alias of DM (sharcldr.SW_ALIAS_BASE)
# section 7 is byte for byte the same in OS 1.11 and 1.12 (issue #382), so either stock image serves.

from dnfw.checkout import resources_dir   # noqa: E402  (DNFW_RESOURCES, or 00_Resources beside the repo)
STOCK = resources_dir(ROOT) / "00_Firmware/Digitone_II_OS1.12.syx"


def run_group(a) -> int:
    import sharc_waverider_m5 as g
    from dnfw import sharcemu
    sharcemu.alias_main_layout(sharcemu.path())     # digikit main: tools.sharc_dev
    import sharc_run as SR
    from dnfw.waverider import frame as FR

    dk = g.m1.Digikit(sharcemu.path())
    g.fx.bind(str(sharcemu.path() / "tools"))
    image = STOCK
    g.m4.IMAGE = image
    stock = g.m1.dn2_section7(image)
    sound, machines = g.m4.init_sound(image)
    stock_image = g.Image(dk, stock)
    rng = random.Random(a.seed)
    filters = [int(x) for x in a.filters.split(",")] if a.filters else [0]

    reads = collections.defaultdict(collections.Counter)    # (region, word) -> Counter(pc)
    forms = {}                                              # pc -> the decoded form
    blocks_run = 0
    with tempfile.TemporaryDirectory(dir=g.OUT) as tmp:
        snap, m2mach = g.snapshot_path(dk, stock, pathlib.Path(tmp))
        for flt in filters:
            state = g.init_on(snap, m2mach, stock_image)
            for b in range(a.blocks):
                f = g.base_frame(sound, machines, t0=a.machine, trigger=(b == 0))
                raw = bytearray(f.to_bytes())
                for off in range(RANDOM_FROM, PAYLOAD, 2):
                    raw[off:off + 2] = rng.getrandbits(16).to_bytes(2, "little")
                for t in range(FR.TRACKS):              # the machine and filter of every track, back
                    for arr, val in ((FR.MACHINE, a.machine), (FR.FILTER, flt)):
                        o = FR.header_offset(arr, t)
                        raw[o:o + 2] = int(val).to_bytes(2, "little")
                r = g.m4.unpack_call(state, bytes(raw))
                idx = g.m2.word(r.state, g.m4.RX_INDEX) or 0
                rx = g.m4.RX_BASE + (idx << 8)
                r.attach_watchpoints([
                    SR.Watchpoint(rx, rx + PAYLOAD, on_read=True, on_write=False, stop=False, label="rx"),
                    SR.Watchpoint(FRAME_COPY, FRAME_COPY + PAYLOAD, on_read=True, on_write=False,
                                  stop=False, label="copy"),
                ])
                res = g.fx.run(r, 8_000_000, g.fixups({}))
                if not (res[0] == "halt" and res[1].pc_sw == g.m4.UNPACK_RETURN):
                    print(f"machine {a.machine} filter {flt} block {b}: no clean return {res[:2]}", flush=True)
                    break
                base = {"rx": rx, "copy": FRAME_COPY}
                for ev in r.watch_log:
                    forms.setdefault(ev.pc_sw, (ev.form, ev.width))
                    start = ev.address - ALIAS if ev.address >= ALIAS else ev.address   # canonical -> DM
                    for byte in range(start, start + max(ev.width, 1)):
                        w = (byte - base[ev.label]) // 2
                        reads[(ev.label, w)][ev.pc_sw] += 1
                blocks_run += 1
                state = r
            print(f"machine {a.machine} filter {flt}: {a.blocks} blocks", flush=True)
    out = {"machine": a.machine, "filters": filters, "blocks": blocks_run, "seed": a.seed,
           "forms": {str(pc): list(v) for pc, v in forms.items()},
           "reads": {f"{lab}:{w}": dict(c) for (lab, w), c in reads.items()}}
    pathlib.Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(a.out).write_text(json.dumps(out))
    print(f"wrote {a.out}: {blocks_run} blocks, {len(reads)} (region, word) pairs read", flush=True)
    return 0


def run_diff(a) -> int:
    """The same random frames twice, the words in --words flipped in the second, from the
    same state: any DSP data memory (outside the receive pages) that differs afterwards."""
    import sharc_waverider_m5 as g
    from dnfw import sharcemu
    from dnfw.waverider import frame as FR

    dk = g.m1.Digikit(sharcemu.path())
    g.fx.bind(str(sharcemu.path() / "tools"))
    image = STOCK
    g.m4.IMAGE = image
    stock = g.m1.dn2_section7(image)
    sound, machines = g.m4.init_sound(image)
    stock_image = g.Image(dk, stock)
    words = [int(x, 0) for x in a.words.split(",")]
    skip = [(FRAME_COPY, FRAME_COPY + PAYLOAD), (0x2C29D0, 0x2C29D0 + 0x1000), (0x2C39D0, 0x2C39D0 + 0x1000),
            (0x2C0478, 0x2C0478 + 0x100 + 0xAC0)]
    total_diff = 0
    with tempfile.TemporaryDirectory(dir=g.OUT) as tmp:
        snap, m2mach = g.snapshot_path(dk, stock, pathlib.Path(tmp))
        for flt in [int(x) for x in a.filters.split(",")]:
            rng = random.Random(a.seed)
            chains = [g.init_on(snap, m2mach, stock_image), g.init_on(snap, m2mach, stock_image)]
            for b in range(a.blocks):
                f = g.base_frame(sound, machines, t0=a.machine, trigger=(b == 0))
                raw = bytearray(f.to_bytes())
                for off in range(RANDOM_FROM, PAYLOAD, 2):
                    raw[off:off + 2] = rng.getrandbits(16).to_bytes(2, "little")
                for t in range(FR.TRACKS):
                    for arr, val in ((FR.MACHINE, a.machine), (FR.FILTER, flt)):
                        o = FR.header_offset(arr, t)
                        raw[o:o + 2] = int(val).to_bytes(2, "little")
                wild = [(r, int.from_bytes(raw[OWNERS + 2 * r:OWNERS + 2 * r + 2], "little")) for r in range(16)]
                wild = [(r, v) for r, v in wild if v > 15]
                if a.valid_owners:                      # a real frame: row r's owner is a track, 0..15
                    for r in range(16):
                        raw[OWNERS + 2 * r:OWNERS + 2 * r + 2] = (r).to_bytes(2, "little")
                elif any(0x25 <= v <= 0x3F for _, v in wild):
                    print(f"  block {b}: owners that put a mix row on the frame image: "
                          + ", ".join(f"row {r} {v:#x}" for r, v in wild if 0x25 <= v <= 0x3F), flush=True)
                var = bytearray(raw)
                for w in words:
                    v = int.from_bytes(var[w:w + 2], "little") ^ 0xFFFF
                    var[w:w + 2] = v.to_bytes(2, "little")
                mems = []
                for k, frame in enumerate((bytes(raw), bytes(var))):
                    r = g.m4.unpack_call(chains[k], frame)
                    res = g.fx.run(r, 8_000_000, g.fixups({}))
                    if not (res[0] == "halt" and res[1].pc_sw == g.m4.UNPACK_RETURN):
                        print(f"filter {flt} block {b}: no clean return {res[:2]}", flush=True)
                        return 1
                    chains[k] = r
                    mem = {}
                    for addr in range(0x200000, 0x300000, 4):
                        if any(lo <= addr < hi for lo, hi in skip):
                            continue
                        w = g.m2.word(r.state, addr)
                        if w is not None:
                            mem[addr] = w
                    mems.append(mem)
                diff = [x for x in mems[0] if mems[0][x] != mems[1].get(x)]
                total_diff += len(diff)
                print(f"machine {a.machine} filter {flt} block {b}: {len(diff)} memory words differ"
                      + (" first " + ", ".join(f"{x:#x}" for x in diff[:8]) if diff else ""), flush=True)
    print(f"total differing words over the run: {total_diff}")
    return 0


def run_flip(a) -> int:
    """A dependence map: flip each frame word of a realistic frame in turn (the instrument's
    sound defaults, a note on at block 0) and compare all DSP memory outside the receive pages
    with the unflipped run, after each of --blocks blocks. A word with no difference matters to
    nothing in these blocks. Words are split across processes with --part K/N."""
    import sharc_waverider_m5 as g
    from dnfw import sharcemu
    from dnfw.waverider import frame as FR

    dk = g.m1.Digikit(sharcemu.path())
    g.fx.bind(str(sharcemu.path() / "tools"))
    image = STOCK
    g.m4.IMAGE = image
    stock = g.m1.dn2_section7(image)
    sound, machines = g.m4.init_sound(image)
    stock_image = g.Image(dk, stock)
    skip = [(FRAME_COPY, FRAME_COPY + PAYLOAD), (0x2C29D0, 0x2C29D0 + 0x1000), (0x2C39D0, 0x2C39D0 + 0x1000),
            (0x2C0478, 0x2C0478 + 0x100 + 0xAC0)]
    k, n = [int(x) for x in a.part.split("/")]
    todo = [w for w in range(0, PAYLOAD, 2) if (w // 2) % n == k]
    if a.only:
        todo = [int(x, 0) for x in a.only.split(",")]

    def snapshot(r):
        mem = {}
        for addr in range(0x200000, 0x300000, 4):
            if any(lo <= addr < hi for lo, hi in skip):
                continue
            v = g.m2.word(r.state, addr)
            if v is not None:
                mem[addr] = v
        return mem

    out = {"machine": a.machine, "filter": a.filter, "blocks": a.blocks, "words": {}}
    with tempfile.TemporaryDirectory(dir=g.OUT) as tmp:
        snap, m2mach = g.snapshot_path(dk, stock, pathlib.Path(tmp))

        def frames(flip):
            fs = []
            for b in range(a.blocks):
                f = g.base_frame(sound, machines, t0=a.machine, trigger=(b == 0))
                raw = bytearray(f.to_bytes())
                for t in range(FR.TRACKS):
                    for arr, val in ((FR.MACHINE, a.machine), (FR.FILTER, a.filter)):
                        o = FR.header_offset(arr, t)
                        raw[o:o + 2] = int(val).to_bytes(2, "little")
                if flip is not None:
                    v = int.from_bytes(raw[flip:flip + 2], "little") ^ 0xFFFF
                    raw[flip:flip + 2] = v.to_bytes(2, "little")
                fs.append(bytes(raw))
            return fs

        def run(flip):
            state = g.init_on(snap, m2mach, stock_image)
            mems = []
            for fr in frames(flip):
                r = g.m4.unpack_call(state, fr)
                res = g.fx.run(r, 8_000_000, g.fixups({}))
                if not (res[0] == "halt" and res[1].pc_sw == g.m4.UNPACK_RETURN):
                    return None
                state = r
                mems.append(snapshot(r))
            return mems

        base = run(None)
        if base is None:
            print("baseline did not run cleanly", flush=True)
            return 1
        for w in todo:
            m = run(w)
            if m is None:
                out["words"][str(w)] = "halt"
                print(f"word {w:#x}: halt", flush=True)
                continue
            d = [sum(1 for x in base[b] if base[b][x] != m[b].get(x)) for b in range(a.blocks)]
            out["words"][str(w)] = d
            print(f"word {w:#x}: {d}", flush=True)
            pathlib.Path(a.out).parent.mkdir(parents=True, exist_ok=True)
            pathlib.Path(a.out).write_text(json.dumps(out))
    return 0


def run_replay(a) -> int:
    """Real frames: each file is a frame as the ColdFire holds it (big-endian 16-bit words,
    2,688 bytes, tools/dn2probe_frame.py). Every file is replayed --blocks times in a row from
    a fresh DSP state, with the same read watchpoints as `run`. With --flip BYTE,...: a
    variant in which a reader outside the copy loops touches one of those frame words is
    replayed twice, the word flipped in the second, and all DSP memory outside the receive
    pages and the frame copy is compared (as `diff` does): a read that carries the word into
    nothing shows as 0 differing words, and the control is any word that matters."""
    import sharc_waverider_m5 as g
    from dnfw import sharcemu
    sharcemu.alias_main_layout(sharcemu.path())     # digikit main: tools.sharc_dev
    import sharc_run as SR

    dk = g.m1.Digikit(sharcemu.path())
    g.fx.bind(str(sharcemu.path() / "tools"))
    image = STOCK
    g.m4.IMAGE = image
    stock = g.m1.dn2_section7(image)
    stock_image = g.Image(dk, stock)
    reads = collections.defaultdict(collections.Counter)
    forms = {}
    blocks_run = 0
    files = sorted(pathlib.Path(x) for pat in a.frames for x in __import__("glob").glob(pat))
    k, n = [int(x) for x in a.shard.split("/")]
    files = files[k::n]
    rng = random.Random(a.seed)
    if a.limit and len(files) > a.limit:                         # an even spread
        files = [files[i * len(files) // a.limit] for i in range(a.limit)]

    def variants(raw):
        """(label, bytes) for the frame as sent and its augmentations."""
        out = [("as-sent", bytes(raw))]
        for v in range(a.variants):
            r = bytearray(raw)
            if a.augment in ("fx", "both"):
                for lo, hi in (HEADER_FLAGS, FX_BLOCK):
                    for off in range(lo, hi, 2):
                        r[off:off + 2] = rng.getrandbits(16).to_bytes(2, "little")
                out.append((f"fx{v}", bytes(r)))
            if a.augment in ("voices", "both"):
                r = bytearray(raw)
                for lo, hi in (VOICE_SLOTS, OWNERS):
                    for off in range(lo, hi, 2):
                        r[off:off + 2] = rng.getrandbits(16).to_bytes(2, "little")
                r += bytes(rng.getrandbits(8) for _ in range(FRAME_LEN - len(r)))     # the tail
                out.append((f"voices{v}", bytes(r)))
        return out if a.augment != "none" or a.variants == 0 else out[:1]
    watch_to = FRAME_LEN
    flip = [int(x, 0) for x in a.flip.split(",")] if a.flip else []
    skip = [(FRAME_COPY, FRAME_COPY + PAYLOAD), (0x2C29D0, 0x2C29D0 + 0x1000), (0x2C39D0, 0x2C39D0 + 0x1000),
            (0x2C0478, 0x2C0478 + 0x100 + 0xAC0)]

    def mem_of(r):
        mem = {}
        for addr in range(0x200000, 0x300000, 4):
            if any(lo <= addr < hi for lo, hi in skip):
                continue
            v = g.m2.word(r.state, addr)
            if v is not None:
                mem[addr] = v
        return mem

    def flipped(framebytes):
        out = bytearray(framebytes)                      # DSP memory order: little-endian words
        for w in flip:
            out[w:w + 2] = (int.from_bytes(out[w:w + 2], "little") ^ 0xFFFF).to_bytes(2, "little")
        return bytes(out)

    def flip_pair(label_of, framebytes):
        chains = [g.init_on(snap, m2mach, stock_image), g.init_on(snap, m2mach, stock_image)]
        for b in range(a.blocks):
            mems = []
            for k, frame in enumerate((framebytes, flipped(framebytes))):
                r = g.m4.unpack_call(chains[k], frame)
                res = g.fx.run(r, 8_000_000, g.fixups({}))
                if not (res[0] == "halt" and res[1].pc_sw == g.m4.UNPACK_RETURN):
                    print(f"  FLIP {label_of} block {b}: no clean return {res[:2]}", flush=True)
                    return
                chains[k] = r
                mems.append(mem_of(r))
            diff = [x for x in mems[0] if mems[0][x] != mems[1].get(x)]
            print(f"  FLIP {label_of} block {b}: {len(diff)} memory words differ"
                  + (" first " + ", ".join(f"{x:#x}" for x in diff[:6]) if diff else ""), flush=True)
    with tempfile.TemporaryDirectory(dir=g.OUT) as tmp:
        snap, m2mach = g.snapshot_path(dk, stock, pathlib.Path(tmp))
        for fpath in files:
            be = fpath.read_bytes()
            raw = bytearray(be)
            raw[0::2], raw[1::2] = be[1::2], be[0::2]            # DSP memory order
            for label, framebytes in variants(raw):
                state = g.init_on(snap, m2mach, stock_image)
                triggered = False
                for b in range(a.blocks):
                    r = g.m4.unpack_call(state, framebytes)
                    idx = g.m2.word(r.state, g.m4.RX_INDEX) or 0
                    rx = g.m4.RX_BASE + (idx << 8)
                    r.attach_watchpoints([
                        SR.Watchpoint(rx, rx + watch_to, on_read=True, on_write=False, stop=False, label="rx"),
                        SR.Watchpoint(FRAME_COPY, FRAME_COPY + PAYLOAD, on_read=True, on_write=False,
                                      stop=False, label="copy"),
                    ])
                    res = g.fx.run(r, 8_000_000, g.fixups({}))
                    if not (res[0] == "halt" and res[1].pc_sw == g.m4.UNPACK_RETURN):
                        print(f"{fpath.name} {label} block {b}: no clean return {res[:2]}", flush=True)
                        break
                    base = {"rx": rx, "copy": FRAME_COPY}
                    for ev in r.watch_log:
                        forms.setdefault(ev.pc_sw, (ev.form, ev.width))
                        begin = ev.address - ALIAS if ev.address >= ALIAS else ev.address
                        for byte in range(begin, begin + max(ev.width, 1)):
                            reads[(ev.label, (byte - base[ev.label]) // 2)][ev.pc_sw] += 1
                            if flip and ev.pc_sw not in COPY_LOOPS and any(
                                    0 <= byte - base[ev.label] - w < 2 for w in flip):
                                triggered = True
                    blocks_run += 1
                    state = r
                if triggered:
                    print(f"{fpath.name} {label}: a reader outside the copy loops touched a flipped word",
                          flush=True)
                    flip_pair(f"{fpath.name} {label}", framebytes)
            print(f"{fpath.name}: {a.blocks} blocks x {len(variants(raw))} variants", flush=True)
    out = {"machine": -1, "filters": [], "blocks": blocks_run, "seed": 0, "real": [f.name for f in files],
           "forms": {str(pc): list(v) for pc, v in forms.items()},
           "reads": {f"{lab}:{w}": dict(c) for (lab, w), c in reads.items()}}
    pathlib.Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(a.out).write_text(json.dumps(out))
    print(f"wrote {a.out}: {blocks_run} blocks from {len(files)} real frames", flush=True)
    return 0


def run_all(a) -> int:
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    jobs = []
    for m in range(5):
        for flt in range(6):
            jobs.append((m, flt))
    procs, running = [], []
    for k, (m, flt) in enumerate(jobs):
        cmd = [sys.executable, str(pathlib.Path(__file__)), "run", "--machine", str(m), "--filters", str(flt),
               "--blocks", str(a.blocks), "--seed", str(a.seed + k), "--out", str(out / f"m{m}f{flt}_s{a.seed}.json")]
        while len(running) >= a.jobs:
            running = [p for p in running if p.poll() is None]
            if len(running) >= a.jobs:
                import time
                time.sleep(2)
        log = open(out / f"m{m}f{flt}_s{a.seed}.log", "w")
        running.append(subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT))
        procs.append(running[-1])
    for p in procs:
        p.wait()
    print(f"{len(jobs)} groups done in {out}")
    return report(argparse.Namespace(dir=str(out), word=[]))


def report(a) -> int:
    d = pathlib.Path(a.dir)
    merged = collections.defaultdict(collections.Counter)
    blocks = 0
    for fpath in sorted(d.glob("*.json")):          # run, replay and real captures alike
        j = json.loads(fpath.read_text())
        blocks += j["blocks"]
        for key, c in j["reads"].items():
            for pc, n in c.items():
                merged[key][int(pc)] += n
    print(f"{blocks} blocks merged from {d}")
    words = range(FRAME_LEN // 2)
    never, copy_only, consumed = [], [], []
    for w in words:
        pcs = set()
        for lab in ("rx", "copy"):
            pcs |= set(merged.get(f"{lab}:{w}", {}))
        if not pcs:
            never.append(w)
        elif pcs <= COPY_LOOPS:
            copy_only.append(w)
        else:
            consumed.append(w)

    def span(ws):
        out, start, prev = [], None, None
        for w in ws:
            if start is None:
                start = prev = w
            elif w == prev + 1:
                prev = w
            else:
                out.append((start, prev)); start = prev = w
        if start is not None:
            out.append((start, prev))
        return ", ".join(f"{s * 2:#x}" if s == e else f"{s * 2:#x}..{e * 2:#x}" for s, e in out) or "none"

    print(f"words never read in the receive page or the copy: {len(never)}: {span(never)}")
    print(f"words read only by the unpack copy loops: {len(copy_only)}: {span(copy_only)}")
    print(f"words with a consumer: {len(consumed)}")
    direct = collections.defaultdict(set)     # reads of the receive page outside the copy loops
    for key, c in merged.items():
        lab, w = key.split(":")
        for pc in c:
            if lab == "rx" and pc not in COPY_LOOPS:
                direct[int(w)].add(pc)
    print("receive-page words read directly (not by the copy loops):",
          ", ".join(f"{w * 2:#x}<-" + "/".join(f"{pc:#x}" for pc in sorted(p)) for w, p in sorted(direct.items())) or "none")
    for ws in a.word:
        w = int(ws, 0) // 2
        for lab in ("rx", "copy"):
            c = merged.get(f"{lab}:{w}", {})
            print(f"word {ws} {lab}: " + (", ".join(f"{pc:#x} x{n}" for pc, n in sorted(c.items())) or "no reads"))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--machine", type=int, required=True)
    r.add_argument("--filters", default="0")
    r.add_argument("--blocks", type=int, default=4)
    r.add_argument("--seed", type=int, default=1)
    r.add_argument("--out", required=True)
    al = sub.add_parser("all")
    al.add_argument("--blocks", type=int, default=4)
    al.add_argument("--jobs", type=int, default=10)
    al.add_argument("--seed", type=int, default=100)
    al.add_argument("--out", required=True)
    df = sub.add_parser("diff")
    df.add_argument("--machine", type=int, required=True)
    df.add_argument("--filters", default="0")
    df.add_argument("--blocks", type=int, default=4)
    df.add_argument("--seed", type=int, default=1)
    df.add_argument("--words", default="0x2a,0xa18", help="frame byte offsets to flip")
    df.add_argument("--valid-owners", action="store_true",
                    help="set row r's owner word to r, as in a real frame (random owners send the mix loops' pointers wild)")
    rpl = sub.add_parser("replay")
    rpl.add_argument("--frames", nargs="+", required=True, help="glob(s) of big-endian frame files")
    rpl.add_argument("--blocks", type=int, default=3)
    rpl.add_argument("--augment", choices=("none", "fx", "voices", "both"), default="none",
                     help="fx: randomise the global FX block and header flags; voices: random slots, "
                          "owners and tail (naturarum T6.0 scenarios 2 and 3)")
    rpl.add_argument("--variants", type=int, default=1, help="random variants per frame and kind")
    rpl.add_argument("--shard", default="0/1", help="K/N: every Nth file from K")
    rpl.add_argument("--limit", type=int, default=0, help="most frames used (an even spread)")
    rpl.add_argument("--seed", type=int, default=1)
    rpl.add_argument("--flip", default="", help="frame byte offsets: replay a variant a reader "
                     "touches twice, the word flipped in the second, and diff DSP memory")
    rpl.add_argument("--out", required=True)
    fl = sub.add_parser("flip")
    fl.add_argument("--machine", type=int, default=1)
    fl.add_argument("--filter", type=int, default=0)
    fl.add_argument("--blocks", type=int, default=2)
    fl.add_argument("--part", default="0/1", help="K/N: words whose index mod N is K")
    fl.add_argument("--only", default="", help="comma-separated byte offsets instead of all")
    fl.add_argument("--out", required=True)
    rp = sub.add_parser("report")
    rp.add_argument("dir")
    rp.add_argument("--word", action="append", default=[])
    a = ap.parse_args()
    return {"run": run_group, "all": run_all, "report": report, "diff": run_diff, "flip": run_flip, "replay": run_replay}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
