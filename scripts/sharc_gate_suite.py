"""Run the DSP gate suite against one digikit worktree, saving every gate's output; or compare two runs.

    python scripts/sharc_gate_suite.py run --digikit ../digikit-wt-sharcemu3 --label new
    python scripts/sharc_gate_suite.py compare old new

`run` executes each gate below with DNFW_DIGIKIT_SHARC (and --digikit where the gate takes
it) set to the worktree, one after another, and writes out/digikit_compare/LABEL/GATE.txt
plus LABEL/summary.json (exit codes, seconds). `compare` puts two labels side by side: the
exit codes, and each gate's output with times, paths and the run's tag normalised, so a
line that differs is a behaviour difference between the two emulators, not noise.

The gates are the ones that clear a Waverider build (out/waverider/gates_*.log) plus the
stage 3 checks (the FFTs, the two-frame levels, the int16 ends, the self-test, the idle-time
builder) and the DDR scanner's check. Nothing here touches an instrument.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import pathlib
import re
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "out" / "digikit_compare"

from dnfw import progress  # noqa: E402

GATES = {                                       # name -> arguments after the script
    "m5": ["scripts/sharc_waverider_m5.py", "--tag", "{label}"],
    "pool": ["scripts/sharc_waverider_pool.py"],
    "sub": ["scripts/sharc_waverider_sub.py"],
    "noise": ["scripts/sharc_waverider_noise.py"],
    "dclk_hold": ["scripts/sharc_waverider_dclk_hold.py"],
    "idle_load": ["scripts/sharc_idle_load_check.py"],
    "ddrscan": ["scripts/sharc_ddrscan_check.py"],
    "fft": ["scripts/sharc_fft_check.py", "--sizes", "16", "256"],
    "rfft": ["scripts/sharc_rfft_check.py", "--sizes", "32", "512"],
    "fft2": ["scripts/sharc_fft2_check.py", "--sizes", "8", "128", "--compact", "--parts"],
    "fft3": ["scripts/sharc_fft3_check.py"],
    "levels3": ["scripts/sharc_levels3_check.py", "--points", "256"],
    "mipb3": ["scripts/sharc_mipb3_check.py", "--points", "256"],
    "selftest": ["scripts/sharc_selftest_check.py"],
    "build3": ["scripts/sharc_build3_check.py"],
}
NOISE = [(re.compile(r"\(\d+(\.\d+)? s"), "(T s"), (re.compile(r"\d+(\.\d+)? s\b"), "T s"),
         (re.compile(r"m5_report_\w+\.json"), "m5_report_TAG.json"),
         (re.compile(r"[A-Za-z]:[\\/][^\s'\"]*"), "PATH")]


def run(a) -> int:
    dest = OUT / a.label
    dest.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, DNFW_DIGIKIT_SHARC=str(a.digikit.resolve()))
    summary = {"digikit": str(a.digikit.resolve()), "gates": {}}
    head = subprocess.run(["git", "-C", str(a.digikit), "log", "--oneline", "-1"], capture_output=True, text=True)
    summary["digikit_head"] = head.stdout.strip()
    names = list(a.only or GATES)
    with progress.Job(f"gate suite {a.label}", total=len(names)) as job:
        for k, name in enumerate(names):
            job.update(done=k, step=name, detail=summary.get("digikit_head", ""))
            env[progress.PARENT_ENV] = job.id          # each gate's own progress nests under the suite
            secs = _run_gate(a, name, env, dest, summary)
            job.update(done=k + 1, detail=f"{name}: exit {summary['gates'][name]['exit']} in {secs} s")
    return 0


def _run_gate(a, name: str, env: dict, dest: pathlib.Path, summary: dict) -> float:
    """One gate as a child process: its output to DEST/NAME.txt, its exit and time to SUMMARY."""
    args = [x.format(label=a.label) for x in GATES[name]]
    t = time.perf_counter()
    r = subprocess.run([sys.executable, *args, "--digikit", str(a.digikit.resolve())], cwd=ROOT, env=env,
                       capture_output=True, text=True)
    secs = round(time.perf_counter() - t, 1)
    (dest / f"{name}.txt").write_text(r.stdout + ("\n--- stderr ---\n" + r.stderr if r.stderr.strip() else ""),
                                      encoding="utf-8")
    summary["gates"][name] = {"exit": r.returncode, "seconds": secs}
    print(f"  {a.label:6s} {name:10s} exit {r.returncode}  {secs:7.1f} s", flush=True)
    (dest / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return secs


def normalised(path: pathlib.Path) -> list[str]:
    text = path.read_text(encoding="utf-8") if path.exists() else "(missing)\n"
    text = text.split("\n--- stderr ---\n")[0]
    for pat, rep in NOISE:
        text = pat.sub(rep, text)
    return text.splitlines()


def compare(a) -> int:
    sa = json.loads((OUT / a.a / "summary.json").read_text())
    sb = json.loads((OUT / a.b / "summary.json").read_text())
    print(f"  {a.a}: {sa['digikit_head']}\n  {a.b}: {sb['digikit_head']}\n")
    same_all = True
    for name in GATES:
        ga, gb = sa["gates"].get(name), sb["gates"].get(name)
        if not ga or not gb:
            print(f"  {name:10s} not run in both")
            same_all = False
            continue
        la, lb = normalised(OUT / a.a / f"{name}.txt"), normalised(OUT / a.b / f"{name}.txt")
        same = la == lb and ga["exit"] == gb["exit"]
        same_all &= same
        print(f"  {name:10s} exit {ga['exit']} / {gb['exit']}   {ga['seconds']:7.1f} / {gb['seconds']:7.1f} s   "
              f"{'identical' if same else 'DIFFERS'}")
        if not same:
            for line in list(difflib.unified_diff(la, lb, a.a, a.b, lineterm="", n=0))[:40]:
                print("      " + line)
    return 0 if same_all else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--digikit", type=pathlib.Path, required=True)
    r.add_argument("--label", required=True)
    r.add_argument("--only", nargs="+", choices=sorted(GATES))
    c = sub.add_parser("compare")
    c.add_argument("a")
    c.add_argument("b")
    a = p.parse_args(argv)
    return run(a) if a.cmd == "run" else compare(a)


if __name__ == "__main__":
    raise SystemExit(main())
