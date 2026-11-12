"""Capture a corpus of the frames the ColdFire really sends the DSP, across machines and patterns.

    python scripts/frame_corpus.py --out out/frame_corpus [--machines 0,1,2,3,4] [--run 500M]

Boots a stock OS from reset with SSI0 paced (`panel_drive --ssi-hz`), sets track 1's
machine in MACHINE SEL, enters trigs, presses PLAY, and keeps the whole 2,688-byte frame at
every send (the capture at the exchange routine, tx buffer argument 1: 0x400cf922 on OS 1.12,
0x400cf7be on 1.11, mapped by src/dnfw/osport and checked byte for byte, issue #382). Frames
that differ from the one kept before are written big-endian, the way the ColdFire holds them
(`tools/dn2probe_frame.py`'s format), so `sharc_frame_census.py replay` takes them as they
are. This is the corpus naturarum's T6.0 census calls "every T3.3 capture", made here.

Machines: in MACHINE SEL order the list is FM TONE, FM DRUM, WAVETONE, SWARMER, MIDI, and
track 1 of the start-up project is on FM TONE, so each machine is a number of DOWN taps from
the top. (Until 2026-11-12 this script assumed WAVETONE and counted from it: every corpus it
made held FM TONE, FM DRUM and WAVETONE only, under the wrong names. Read on 1.12's screen.)
Each run saves the machine's page after the selection, `selected.pbm` in its folder, as proof. The pattern's trigs are entered with RECORD and the trig keys as
digikit main's `tools/emulator/seqplay.py` does (it is imported for the key codes and script).
The defaults are OS 1.12 and digikit main's panel_drive. For 1.11: --stock the 1.11 .syx,
--exchange 0x400cf7be.
"""
import argparse
import importlib.util
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from dnfw.checkout import resources_dir   # noqa: E402
RESOURCES = resources_dir(ROOT)
DIGIKIT = pathlib.Path(__import__("os").environ.get("DNFW_DIGIKIT", ROOT.parents[3 if ".claude" in ROOT.parts else 0] / "digikit-main"))
STOCK = RESOURCES / "00_Firmware/Digitone_II_OS1.12.syx"
EXCHANGE = "0x400cf922"                                    # OS 1.12 (1.11: 0x400cf7be)
FRAME = 2688

# MACHINE SEL: DOWN taps (key 14) from FM TONE, where track 1 starts
TO_MACHINE = {0: [], 2: ["tap:14"], 1: ["tap:14"] * 2, 3: ["tap:14"] * 3, 4: ["tap:14"] * 4}
NAMES = {0: "fmtone", 1: "wavetone", 2: "fmdrum", 3: "swarmer", 4: "midi"}


def load_seqplay(digikit: pathlib.Path):
    sys.path.insert(0, str(digikit))                        # seqplay imports tools.emulator
    spec = importlib.util.spec_from_file_location("seqplay", digikit / "tools/emulator/seqplay.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["seqplay"] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=pathlib.Path, required=True)
    ap.add_argument("--machines", default="0,1,2,3,4")
    ap.add_argument("--run", default="500M", help="instructions to play")
    ap.add_argument("--ssi-hz", default="96000")
    ap.add_argument("--patterns", default="1,5,9,13;1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16;1,9",
                    help="track 1 steps, semicolon-separated patterns")
    ap.add_argument("--keep", type=int, default=80, help="most frames kept per run")
    ap.add_argument("--stock", type=pathlib.Path, default=STOCK, help="the stock .syx (default OS 1.12)")
    ap.add_argument("--exchange", default=EXCHANGE, help="the DSP exchange routine in that image")
    ap.add_argument("--digikit", type=pathlib.Path, default=DIGIKIT)
    a = ap.parse_args()
    sp = load_seqplay(a.digikit)
    panel = a.digikit / "target/release/examples/panel_drive.exe"
    a.out.mkdir(parents=True, exist_ok=True)
    total = 0
    for m in [int(x) for x in a.machines.split(",")]:
        for pi, pat in enumerate(a.patterns.split(";")):
            trigs = {1: [int(t) for t in pat.split(",")]}
            steps = sp.script(trigs, a.run, None, 0, None)
            # insert the machine change after the start-up wait and the popup dismissal
            at = 3                                              # wait:1500M, tap:NO, wait:60M
            sel = (["press:17", "tap:2", "release:17", "wait:60M"]
                   + [t for tap in TO_MACHINE[m] for t in (tap, "wait:20M")]
                   + ["tap:10", "wait:100M", "tap:2", "wait:60M", "frame:selected"])
            steps = steps[:at] + sel + steps[at:]
            d = a.out / f"{NAMES[m]}_p{pi}"
            d.mkdir(exist_ok=True)
            cmd = [str(panel), str(a.stock), "--out", str(d), "--ssi-hz", a.ssi_hz, "--capture",
                   f"{a.exchange}:1:{FRAME}", "--steps", ",".join(steps)]
            done = subprocess.run(cmd, capture_output=True, text=True, timeout=3000)
            if not done.stdout.strip():
                print(f"machine {m} pattern {pi}: no output: {done.stderr[-200:]}")
                continue
            result = json.loads(done.stdout.strip().splitlines()[-1])
            frames = [bytes.fromhex(c["hex"]) for c in result["captures"]]
            kept, last = [], None
            for f in frames:
                if len(f) == FRAME and f != last:
                    kept.append(f)
                    last = f
            if len(kept) > a.keep:                               # an even spread over the run
                kept = [kept[i * len(kept) // a.keep] for i in range(a.keep)]
            for i, f in enumerate(kept):
                (d / f"{i:04d}.frame_be.bin").write_bytes(f)
            total += len(kept)
            print(f"machine {m} ({NAMES[m]}) pattern {pi}: {len(frames)} sends, {len(kept)} distinct kept "
                  f"({result['outcome']})", flush=True)
    print(f"{total} frames in {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
