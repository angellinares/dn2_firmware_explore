"""pslide's load in the emulator: the slide stress patterns on the build and on the same image
without pslide, frame by frame, and digikit's gate set.

    python scripts/emu_pslide_load.py BUILD.syx [--control CONTROL.syx] [--mixed MIXED.syx
        --mixed-control MIXED_CONTROL.syx] [--case NAME ...] [--gates] [--jobs N] [--keep DIR]

BUILD is a Digitone II 1.11 image with pslide (`dnfw mods apply --mod pslide`), CONTROL the image
it was made from (stock 1.11 by default). `mixed-drum-full` runs on MIXED (Waverider, lfo4 and
pslide) against MIXED_CONTROL (Waverider and lfo4). Each pattern enters its trigs and locks through
the panel in GRID RECORDING, sets SLD 16 on every trig with knob E on TRIG PAGE 2, presses PLAY and
runs 8 s, in digikit's `coupled-run` with the zero DSP peer. The control runs the same keys, so
there knob E does nothing and every lock jumps.

- `drum-full`: track 1 on FM DRUM, a trig on each of the 16 steps, every parameter that slides
  locked on every trig: 16 voices, each sliding 64 parameters.
- `mixed-drum-full`: the same on 14 voices, tracks 15 and 16 on Waverider with a trig on every
  step, and LFO 4 on track 1 aimed at TUNE, which slides.
- `stagger-locks`: track 1's odd steps, four of them lock trigs, every parameter that slides locked
  (55 on FM TONE), and a microtimed note on step 5 of tracks 2 to 8.
- `dense-80`: a trig on every step of all 16 tracks, the FLTR page's first five knobs locked on
  each: all 80 lock records of a pattern.
- `chord-retrig`: a three-note chord on step 1 and a retrig on step 9, every parameter that slides
  locked on both.

Each run is checked:

- both runs end with `coupled-run`'s gates passing, and no pass reaches the fault reporter
  (`0x4011ea6a`) or the DSP uploader's refusal (`0x400cf678`);
- every trig of the pattern's SLD tracks has SLD 16 on the build and none on the control;
- the notes, in order, are the control's, and each has its trig's lock list where the control's has
  it (stock's lists are few, and its allocator does not check for an empty free list);
- no audio frame from PLAY on is over the unit estimate (88,000 instructions / 1.21, digikit's
  calibration) on the build that is not over on the control;
- `mixed-drum-full`: some frames run a slide's value write and LFO 4's active pass both
  (`addq.l #1,0x468035d8` at `0x402dfb12` in lfo4's stubs, checked in MIXED's bytes).

Measured and printed for each pattern: the audio frame's median and longest pass and the frames
over the unit estimate on both runs; pslide's frame routine, the longest pass in frames with and
without a start; the most values its updates examined in a frame without a start (an entry on a
voice, the unit of the update rate's budget); the note path (`0x40026bac` to `0x40026c44`) and the
lock-trig applier call per voice (`0x40026642` to `0x40026650`) per note against the control's same
note; the slide buffers' high-water mark (`g_bump`, of 96).

`--gates` runs digikit's gate set (`idle`, `kb-chord16` and `dn2-rec-play` from
`tests/scenarios/dn2.json`, and the nine scenarios of `tests/scenarios/dn2-load.json`) on CONTROL,
then on BUILD with `--span-baseline` and its default limits, and the same for MIXED.

Needs digikit's `coupled-run` (`COUPLED_RUN`, else `DIGIKIT`'s
`dist/native-target/generic/release/coupled-run`) and its `tests/scenarios`. Works in a temporary
folder, or in `--keep DIR` (an absolute path) with every report and span log kept.
"""

from __future__ import annotations

import argparse
import bisect
import dataclasses
import hashlib
import json
import os
import pathlib
import re
import statistics
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from dnfw.cli.files import read_image  # noqa: E402
from dnfw.firmware.load import load  # noqa: E402
from dnfw.image import objdump  # noqa: E402
from dnfw.mods import pslide  # noqa: E402

import emu_pslide as EP  # noqa: E402
from emulib import paths  # noqa: E402

BASE = 0x40000400
UNIT_SCALE = 1.21                    # digikit's calibration against a unit (INSTRUMENTATION.md)
PLAY_SECONDS_INSTRUCTIONS = 1_060_000_000   # about 8 s from PLAY at 132 M instructions a second
TAP_HOLD = 1_000_000                 # a tap's hold, as digikit's load scenarios hold
READY = 851_236_338                  # stock 1.11 reaches the ready point at this count (digikit)
SLD_16 = 6
SPANS = {"isr": (0x40025E36, 0x40027BC6), "fault_reporter": (0x4011EA6A, 0x4011EA6E),
         "fault_refusal": (0x400CF678, 0x400CF67A), "note": (0x40026BAC, 0x40026C44),
         "lock": (0x40026642, 0x40026650), "prep": (0x400D8AE2, 0x400D8AE8),
         "listed": (0x40026C2A, 0x40026C3A)}         # a note whose trig has a lock list: the applier call
LFO4_ACTIVE = (0x402DFB12, bytes.fromhex("52b9468035d8"))      # addq.l #1,0x468035d8: an LFO 4 run
LABELS = pslide.SPEC["labels"]
BSS = LABELS["bss_start"]
G_BUMP = BSS + 16                    # buffers taken from the pool so far (build_pslide.DATA)
PATTERN, TRACK_STRIDE = EP.PATTERN, 1701
FX, MOD, DOWN, RIGHT = 5, 6, 14, 15
GATE_SCENARIOS = (("dn2.json", ("idle", "kb-chord16", "dn2-rec-play")),
                  ("dn2-load.json", ("load-seq16", "load-turns", "load-ptn-switch", "load-kb-roll",
                                     "load-midi-flood", "load-lfo3", "load-midi-out", "load-sysex-send",
                                     "load-sysex-keys")))
GATE_SPANS = {"isr": (0x40025E36, 0x40027BC6), "evala": (0x400272D4, 0x400272DA)}


# ---- the patterns, as panel steps ----

def tap(code: int) -> list[str]:
    return [f"tap:{code}"]


def select(track: int) -> list[str]:
    return [f"press:{EP.TRK}", "wait:1M", f"tap:{EP.trig(track)}", f"release:{EP.TRK}", "wait:3M"]


def held(keys, inner) -> list[str]:
    return ([s for k in keys for s in (f"press:{EP.trig(k)}", "wait:1M")] + ["wait:20M"] + list(inner)
            + [s for k in keys for s in (f"release:{EP.trig(k)}", "wait:200000")] + ["wait:10M"])


def lock_values(keys, encoders, counts: int) -> list[str]:
    """Each ENCODER turned four times COUNTS with KEYS held: a lock on each trig"""
    return held(keys, [s for e in encoders for s in [f"turn:{e}:{counts}", "wait:3M"] * 4])


def every_lock(keys, high, synth, refresh_amp_mode: bool) -> list[str]:
    """Every parameter that slides locked on KEYS (low) and HIGH (high): the SYN pages' knobs in
    SYNTH, then the FLTR, AMP, FX and MOD pages (stress patterns of the posted measurement)"""
    out = tap(EP.TRIG_PAGE) + ["wait:20M"]
    pages = ([(EP.SYN, e) for e in synth] + [(EP.FLTR, list(range(1, 9))), (EP.FLTR, [1, 4, 5, 6]),
             (EP.AMP, [1, 2, 3, 7, 8]), (EP.AMP, [1, 2, 3, 4, 7, 8]), (FX, [1, 2, 3, 5, 6, 7])]
             + [(MOD, [1, 3, 6, 8])] * 3)
    amp = 0
    for button, encoders in pages:
        out += tap(button) + ["wait:20M"]
        if button == EP.AMP:
            if refresh_amp_mode:
                out += EP.ES.turn(6, -1 if amp == 0 else 1) + ["wait:60M"]
                out += tap(EP.TRIG_PAGE) + ["wait:20M"] + tap(EP.AMP) + ["wait:20M"]
            else:
                out += [f"turn:6:{-10 if amp == 0 else 10}", "wait:3M"] * 4
            amp += 1
        out += lock_values(keys, encoders, -10) + lock_values(high, encoders, 10)
    return out


def sld_16(keys) -> list[str]:
    """SLD 16 on KEYS: TRIG PAGE 2 (from another page), the trigs held, knob E a unit an event past
    NEXT, where SLD stops, then a unit back, so that an input the UI drops leaves no lower value"""
    unit = EP.ES.COUNTS_PER_UNIT
    turns = [f"turn:{EP.KNOB_E}:{unit}", "wait:30M"] * (EP.NEXT + 3) + [f"turn:{EP.KNOB_E}:{-unit}", "wait:30M"]
    return tap(EP.TRIG_PAGE) + ["wait:30M"] + tap(EP.TRIG_PAGE) + ["wait:30M"] + held(keys, turns)


def three_note_chord(step: int) -> list[str]:
    out = [f"press:{EP.trig(step)}", "wait:40M", f"tap:{EP.STACK}", "wait:60M", f"release:{EP.trig(step)}", "wait:30M"]
    for semitones in (4, 3):
        out += [f"press:{EP.FUNC}", f"tap:{DOWN}", f"release:{EP.FUNC}", "wait:40M"] + EP.ES.turn(5, semitones)
        out += ["wait:30M"]
    return out + tap(EP.NO) + ["wait:40M"]


def waverider(track: int) -> list[str]:
    """TRACK's machine: the fifth of MACHINE SEL"""
    out = select(track) + [f"press:{EP.FUNC}", "wait:20M", f"tap:{EP.SYN}", "wait:40M", f"release:{EP.FUNC}", "wait:60M"]
    return out + (tap(DOWN) + ["wait:40M"]) * 4 + tap(EP.YES) + ["wait:200M"] + tap(EP.SYN) + ["wait:60M"]


def fm_drum() -> list[str]:
    return ([f"press:{EP.FUNC}", "wait:20M", f"tap:{EP.SYN}", "wait:40M", f"release:{EP.FUNC}", "wait:60M"]
            + tap(DOWN) + ["wait:40M"] + tap(EP.YES) + ["wait:200M"])


FM_SYN = ([5, 6, 7, 8], list(range(1, 9)), [1, 5], [1, 2, 3, 4])
DRUM_SYN = ([1, 2, 3, 5, 6, 7, 8], list(range(1, 9)), [1, 2, 3, 4], list(range(1, 9)))
LFO4_TUNE_STEPS = 1                  # LFO 4's DEST one step on from its first: FM DRUM's TUNE


@dataclasses.dataclass(frozen=True)
class Pattern:
    name: str
    steps: tuple[str, ...]           # from the ready point to PLAY, PLAY last
    sld_tracks: tuple[int, ...]      # tracks whose trigs all have SLD 16
    trigs: int                       # the trigs on each of them
    mixed: bool = False


# the trigs of each pattern but dense-80 (default: every step) and those locked high (default: odd steps)
KEYS = {"chord-retrig": ([1, 9], [9]), "stagger-locks": ([1, 3, 5, 7, 9, 11, 13, 15], [3, 5, 11, 13])}
STAGGER_LOCK_TRIGS = (3, 7, 11, 15)


def pattern(name: str) -> Pattern:
    """NAME's keys from the ready point to PLAY"""
    if name == "dense-80":
        return dense_80()
    drum, mixed = name in ("drum-full", "mixed-drum-full"), name == "mixed-drum-full"
    keys, high = KEYS.get(name, (list(range(1, 17)), list(range(1, 17, 2))))
    out = (tap(EP.NO) + ["wait:58M"] + machines(drum, mixed) + tap(EP.RECORD) + ["wait:4M"] + place(name, keys)
           + ["wait:4M"] + every_lock(keys, high, DRUM_SYN if drum else FM_SYN, refresh_amp_mode=drum)
           + before_sld(name, mixed) + sld_16(keys) + after_sld(name, mixed))
    return Pattern(name, tuple(out + tap(EP.RECORD) + ["wait:4M"] + tap(EP.PLAY)), (1,), len(keys), mixed)


def dense_80() -> Pattern:
    """A trig on every step of all 16 tracks, FLTR knobs A to E locked and SLD 16 on each"""
    out = tap(EP.NO) + ["wait:58M"] + tap(EP.FLTR) + ["wait:20M"] + tap(EP.RECORD) + ["wait:4M"]
    for track in range(1, 17):
        out += select(track) + [s for n in range(1, 17) for s in tap(EP.trig(n))] + ["wait:4M"]
        out += lock_values(range(1, 17), [1, 2, 3, 4, 5], 10)
        out += sld_16(range(1, 17)) + tap(EP.FLTR) + ["wait:20M"]
    return Pattern("dense-80", tuple(out + tap(EP.RECORD) + ["wait:4M"] + tap(EP.PLAY)), tuple(range(1, 17)), 16)


def machines(drum: bool, mixed: bool) -> list[str]:
    """Track 1 on FM DRUM (DRUM), and with MIXED tracks 15 and 16 on Waverider, one voice each"""
    out = (fm_drum() + (tap(EP.SYN) + ["wait:60M"] if mixed else [])) if drum else []
    if mixed:
        for track in (15, 16):
            out += waverider(track) + [f"tap:{EP.VOICE}", "wait:20M"] + EP.ES.turn(5, 1) + tap(EP.NO) + ["wait:20M"]
        out += select(1)
    return out


def place(name: str, keys) -> list[str]:
    """The trigs on KEYS: stagger-locks' STAGGER_LOCK_TRIGS as lock trigs, the others as note trigs"""
    out = []
    for key in keys:
        if name == "stagger-locks" and key in STAGGER_LOCK_TRIGS:
            out += [f"press:{EP.FUNC}", "wait:1M", f"tap:{EP.trig(key)}", f"release:{EP.FUNC}", "wait:3M"]
        else:
            out += tap(EP.trig(key))
    return out


def before_sld(name: str, mixed: bool) -> list[str]:
    """chord-retrig's chord on step 1 and retrig on step 9, and MIXED's LFO 4 aimed at TUNE"""
    out = []
    if name == "chord-retrig":
        out += three_note_chord(1) + tap(EP.TRIG_PAGE) + ["wait:20M"] + tap(EP.TRIG_PAGE) + ["wait:20M"]
        out += held([9], ["turn:1:10", "wait:4M"] * 8 + ["turn:4:10", "wait:4M"] * 10 + ["turn:3:10", "wait:4M"] * 60)
    if mixed:              # from LFO 3's page, [MOD] opens LFO 4's
        out += tap(MOD) + ["wait:20M"] + EP.ES.turn(4, LFO4_TUNE_STEPS) + tap(EP.YES) + ["wait:20M"]
        out += EP.ES.turn(8, 20)
    return out


def after_sld(name: str, mixed: bool) -> list[str]:
    """MIXED's Waverider tracks a trig on every step, and stagger-locks' microtimed notes on step 5 of
    tracks 2 to 8"""
    out = []
    if mixed:
        for track in (15, 16):
            out += select(track) + [s for n in range(1, 17) for s in tap(EP.trig(n))] + ["wait:4M"]
    if name == "stagger-locks":
        for track in range(2, 9):
            out += select(track) + tap(EP.trig(5)) + ["wait:4M"]
            out += held([5], [f"tap:{RIGHT}", "wait:20M"] * (track - 1))
    return out


NAMES = ("drum-full", "mixed-drum-full", "stagger-locks", "dense-80", "chord-retrig")


def events(steps: list[str]) -> tuple[list[dict], int, int]:
    """STEPS as coupled-run events from the ready point, kept clear of the UI's stalls: (events, the
    count at PLAY's press, the count at the end of STEPS)"""
    out, at, play = [], 0, 0
    for step in EP.clear_of_stalls(steps, READY, 2 * TAP_HOLD):
        kind, _, rest = step.partition(":")
        if kind == "wait":
            at += int(rest[:-1]) * 1_000_000 if rest.endswith("M") else int(rest, 0)
        elif kind == "tap":
            play = at if int(rest) == EP.PLAY else play
            out += [{"at_instr": at, "button": int(rest), "down": True},
                    {"at_instr": at + TAP_HOLD, "button": int(rest), "down": False}]
            at += 2 * TAP_HOLD
        elif kind in ("press", "release"):
            out.append({"at_instr": at, "button": int(rest), "down": kind == "press"})
        elif kind == "turn":
            encoder, counts = rest.split(":")
            out.append({"at_instr": at, "turn": int(encoder), "detents": int(counts)})
        else:
            raise ValueError(f"no coupled-run event for {step}")
    return out, play, at


def scenario(p: Pattern) -> dict:
    found, play, end = events(list(p.steps))
    return {"name": p.name, "description": p.name, "instructions": end + PLAY_SECONDS_INSTRUCTIONS,
            "exact_events": True, "clip_last_chunk": True, "events": found, "play_at_instr": play}


# ---- coupled-run ----

def coupled_run() -> pathlib.Path:
    chosen = os.environ.get("COUPLED_RUN")
    path = pathlib.Path(chosen) if chosen else paths.DIGIKIT / "dist/native-target/generic/release" / (
        "coupled-run.exe" if os.name == "nt" else "coupled-run")
    if not path.exists():
        raise SystemExit(f"coupled-run not found at {path}; set COUPLED_RUN or DIGIKIT")
    return path


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclasses.dataclass
class Report:
    ok: bool                         # exit 0 and the runner's gates
    report: dict                     # the scenario's report
    origin: int                      # the count at the ready point
    log: pathlib.Path | None
    text: str


def run(image: pathlib.Path, stock: pathlib.Path, scenarios: list[pathlib.Path], name: str,
        spans: dict, folder: pathlib.Path, tag: str, peeks: dict | None = None,
        baseline: pathlib.Path | None = None, log: bool = True) -> Report:
    out = folder / f"{tag}-{name}.json"
    command = [str(coupled_run()), "--syx", str(image), "--dsp", "zero", "--cold-base", sha256(stock),
               "--scenario", name, "--out", str(out), "--unit-scale", str(UNIT_SCALE)]
    for path in scenarios:
        command += ["--scenarios", str(path)]
    for span, (entry, leave) in spans.items():
        command += ["--span", f"{span}={entry:#x}:{leave:#x}"]
    for peek, (address, size) in (peeks or {}).items():
        command += ["--peek", f"{peek}={address:#x}:{size}"]
    span_log = folder / f"spans-{tag}.jsonl"
    if log:
        command += ["--span-log", str(span_log)]
    if baseline:
        command += ["--span-baseline", str(baseline)]
    done = subprocess.run(command, cwd=paths.DIGIKIT, capture_output=True, text=True)
    text = done.stdout + done.stderr
    (folder / f"{tag}-{name}.log").write_text(text)
    ready = re.findall(r"cold boot ready at (\d+) instructions", text)
    report = json.loads(out.read_text())["scenarios"][0] if out.exists() else {}
    return Report(done.returncode == 0 and bool(report) and report["gates"]["ok"], report,
                  int(ready[0]) if ready else 0, span_log.with_stem(f"{span_log.stem}-{name}") if log else None, text)


# ---- the frames ----

@dataclasses.dataclass
class Frames:
    lengths: list[int]               # each audio frame's pass from PLAY on
    counts: dict[str, list[int]]     # a span's entries in each frame
    inside: dict[str, list[int]]     # a span's instructions in each frame
    passes: dict[str, list[int]]     # a span's passes from PLAY on, in order
    listed: list[bool]               # each note from PLAY on, in order: its trig's lock list reached the applier
    faults: int
    period: int


def frames(r: Report, play: int, end: int, names) -> Frames:
    """R's audio frames from PLAY to END, with each of the spans NAMES counted in them"""
    rows = span_rows(r.log, names)
    lo, hi = r.origin + play, r.origin + end
    isr = [(at, n) for at, n in rows["isr"] if lo <= at < hi]
    split = {name: per_frame(found, isr) for name, found in rows.items()}
    faults = sum(s["length"]["count"] for s in r.report["spans"] if s["name"].startswith("fault_"))
    period = next(s["period"] for s in r.report["spans"] if s["name"] == "isr")
    listed_at = [at for at, _ in rows["listed"]]
    listed = [bisect.bisect_left(listed_at, at + n) > bisect.bisect_left(listed_at, at)
              for at, n in rows["note"] if lo <= at < hi]
    return Frames([n for _, n in isr], {name: c for name, (c, _) in split.items()},
                  {name: i for name, (_, i) in split.items()},
                  {name: [n for at, n in found if lo <= at < hi] for name, found in rows.items()}, listed, faults,
                  period)


def span_rows(log: pathlib.Path, names) -> dict[str, list[tuple[int, int]]]:
    """Each span's passes in LOG, (start, instructions) in order, and none for a span of NAMES that did not run"""
    rows: dict[str, list[tuple[int, int]]] = {}
    with log.open() as source:
        for line in source:
            row = json.loads(line)
            rows.setdefault(row["span"], []).append((row["at"], row["len"]))
    for found in rows.values():
        found.sort()
    for name in names:
        rows.setdefault(name, [])
    return rows


def per_frame(found: list[tuple[int, int]], isr: list[tuple[int, int]]) -> tuple[list[int], list[int]]:
    """FOUND's passes in each audio frame of ISR: (how many start in it, their instructions)"""
    times = [at for at, _ in found]
    counts, inside = [], []
    for at, n in isr:
        first, past = bisect.bisect_left(times, at), bisect.bisect_left(times, at + n)
        counts.append(past - first)
        inside.append(sum(found[i][1] for i in range(first, past)))
    return counts, inside


def over_unit(f: Frames) -> set[int]:
    return {i for i, n in enumerate(f.lengths) if n * UNIT_SCALE > f.period}


def paired(build: list[int], control: list[int]) -> dict:
    if len(build) != len(control) or not build:
        return {"count": len(build), "control_count": len(control)}
    diff = [b - c for b, c in zip(build, control)]
    return {"count": len(diff), "median": statistics.median(diff), "max": max(diff), "min": min(diff),
            "build_max": max(build), "control_max": max(control),
            "over_control": sum(d > 0 for d in diff)}


def sld_words(r: Report, p: Pattern) -> list[str]:
    """Each trig of the pattern's SLD tracks: its SLD on R's image at the end, or a problem"""
    out = []
    for track in p.sld_tracks:
        raw = bytes.fromhex(r.report["peek"][f"track{track}"])
        for step in range(16):
            word = int.from_bytes(raw[2 * step:2 * step + 2], "big")
            if word & 1:
                out.append(EP.sld(word))
    return out


def check(p: Pattern, b: Report, c: Report, play: int, end: int, spans: tuple[dict, dict],
          writes: bool) -> tuple[list[str], dict]:
    """P's runs on the build (B) and the control (C): (the problems, the measurements)"""
    failed = [f"{who}: coupled-run failed ({r.text.strip().splitlines()[-1] if r.text.strip() else 'no output'})"
              for who, r in (("build", b), ("control", c)) if not r.ok]
    if failed:
        return failed, {}
    built, stock = sld_words(b, p), sld_words(c, p)
    want = p.trigs * len(p.sld_tracks)
    problems = [] if built == [SLD_16] * want and stock == [0] * want else [
        f"setup: {len(built)} trigs with SLD {sorted(set(built))} on the build, {len(stock)} with "
        f"{sorted(set(stock))} on the control, not {want} with 16 and 0"]
    fb, fc = frames(b, play, end, spans[0]), frames(c, play, end, spans[1])
    problems += frame_problems(fb, fc)
    result = measures(fb, fc, writes) | {"pool_high_water": int(b.report["peek"]["g_bump"], 16)}
    if p.mixed and writes:
        wrote = [a + b for a, b in zip(fb.counts["writes"], fb.counts["writes1"])]
        both = sum(1 for i, n in enumerate(wrote) if n and fb.counts["lfo4"][i])
        result["frames_with_slide_writes_and_lfo4"] = both
        if not both:
            problems.append("no frame runs a slide's value write and LFO 4's active pass both")
    return problems, result


def frame_problems(fb: Frames, fc: Frames) -> list[str]:
    """Fault watches reached, notes that lost their lock list, and frames over the unit estimate on the build only"""
    out = [f"{who}: {f.faults} passes reach a fault watch" for who, f in (("build", fb), ("control", fc)) if f.faults]
    differ = [i for i, (x, y) in enumerate(zip(fb.listed, fc.listed)) if x != y]
    if differ or len(fb.listed) != len(fc.listed):
        out.append(f"{len(differ)} notes, in order, differ from the control's in having their lock list (first "
                   f"{differ[:3]}): {sum(fb.listed)} of {len(fb.listed)} on the build, {sum(fc.listed)} of "
                   f"{len(fc.listed)} on the control")
    new_over = sorted(over_unit(fb) - over_unit(fc))
    if new_over:
        out.append(f"{len(new_over)} frames over the unit estimate on the build only, from frame {new_over[0]}")
    return out


def measures(fb: Frames, fc: Frames, writes: bool) -> dict:
    """The audio frames on both runs, and pslide's frame routine and hooks on the build (fb): in frames
    without a start (no note and no lock trig) and with one"""
    quiet = [i for i in range(len(fb.lengths)) if not fb.counts["note"][i] and not fb.counts["lock"][i]]
    started = sorted(set(range(len(fb.lengths))) - set(quiet))
    wrote = [a + b for a, b in zip(fb.counts.get("writes", [0] * len(fb.lengths)),
                                   fb.counts.get("writes1", [0] * len(fb.lengths)))]
    slide = fb.inside["slide"]
    return {
        "frames": len(fb.lengths), "control_frames": len(fc.lengths),
        "audio": {"control": {"p50": statistics.median(fc.lengths), "max": max(fc.lengths), "over_unit": len(over_unit(fc))},
                  "build": {"p50": statistics.median(fb.lengths), "max": max(fb.lengths), "over_unit": len(over_unit(fb))}},
        "slide_frames": sum(1 for n in slide if n),
        "slide_max_without_start": max((slide[i] for i in quiet), default=0),
        "slide_max_with_start": max((slide[i] for i in started), default=0),
        "examined_max_without_start": max((wrote[i] for i in quiet), default=0) if writes else None,
        "note_path": paired(fb.passes.get("note", []), fc.passes.get("note", [])),
        "lock_per_voice": paired(fb.passes.get("lock", []), fc.passes.get("lock", [])),
        "prep": {"count": len(fb.passes.get("prep", [])), "max": max(fb.passes.get("prep", [0]))},
    }


def spans_of(image: pathlib.Path, mixed: bool, slides: bool, writes: bool) -> dict:
    spans = dict(SPANS)
    if slides:
        spans["slide"] = (LABELS["frame_work"], LABELS["frame_exit"])
        if writes:
            blob, va = bytes.fromhex(pslide.SPEC["code"]["blob"]), pslide.SPEC["code"]["va"]
            for span, label in (("writes", "wv_each"), ("writes1", "us_each")):
                first = objdump.disassemble(blob[LABELS[label] - va:][:8], LABELS[label])[0]
                spans[span] = (first.address, first.end)
    if mixed:
        va, want = LFO4_ACTIVE
        content = load(read_image(image)).container.find(pslide.SECTION).unpack()
        if content[va - BASE:va - BASE + len(want)] != want:
            raise SystemExit(f"{image}: no addq.l #1,0x468035d8 at {va:#x}: lfo4's stubs moved")
        spans["lfo4"] = (va, va + len(want))
    return spans


def peeks_of(p: Pattern, slides: bool) -> dict:
    """The SLD tracks' step flags, and on a build with pslide the pool's high-water mark"""
    out = {f"track{t}": (PATTERN + TRACK_STRIDE * (t - 1), 32) for t in p.sld_tracks}
    return out | ({"g_bump": (G_BUMP, 4)} if slides else {})


def case(p: Pattern, images: dict, stock: pathlib.Path, folder: pathlib.Path, writes: bool,
         keep: bool) -> tuple[list[str], dict]:
    setup = scenario(p)
    path = folder / f"scenario-{p.name}.json"
    path.write_text(json.dumps({"scenarios": [setup]}) + "\n")
    build, control = images["mixed" if p.mixed else "build"], images["mixed-control" if p.mixed else "control"]
    spans = spans_of(build, p.mixed, True, writes), spans_of(control, p.mixed, False, False)
    b = run(build, stock, [path], p.name, spans[0], folder, f"build-{p.name}", peeks_of(p, True))
    c = run(control, stock, [path], p.name, spans[1], folder, f"control-{p.name}", peeks_of(p, False))
    found, result = check(p, b, c, setup["play_at_instr"], setup["instructions"], spans, writes)
    for r in (b, c):
        if r.log and not keep:
            r.log.unlink(missing_ok=True)
    return found, result


def gates(images: dict, stock: pathlib.Path, folder: pathlib.Path, jobs: int) -> list[str]:
    """The gate set on CONTROL, then on BUILD against it, and the same for MIXED"""
    suite = paths.DIGIKIT / "tests/scenarios"
    files = [suite / name for name, _ in GATE_SCENARIOS]
    names = [n for _, found in GATE_SCENARIOS for n in found]
    out = []
    for build, control in (("build", "control"), ("mixed", "mixed-control")):
        if build not in images:
            continue

        def one(name: str) -> str:
            base = run(images[control], stock, files, name, GATE_SPANS, folder, f"gate-{control}", log=False)
            if not base.ok:
                return f"{name}: the control's run failed"
            r = run(images[build], stock, files, name, GATE_SPANS, folder, f"gate-{build}", log=False,
                    baseline=folder / f"gate-{control}-{name}.json")
            lines = [ln.strip() for ln in r.text.splitlines() if ln.strip().startswith("span ")]
            return f"{build} {name}: {'ok' if r.ok else 'FAIL'}" + "".join(f"\n    {ln}" for ln in lines)
        with ThreadPoolExecutor(jobs) as pool:
            out += list(pool.map(one, names))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("build", type=pathlib.Path)
    ap.add_argument("--control", type=pathlib.Path, default=EP.STOCK)
    ap.add_argument("--stock", type=pathlib.Path, default=EP.STOCK, help="the stock image the builds patch")
    ap.add_argument("--mixed", type=pathlib.Path)
    ap.add_argument("--mixed-control", type=pathlib.Path)
    ap.add_argument("--case", action="append", choices=NAMES)
    ap.add_argument("--gates", action="store_true", help="also run digikit's gate set")
    ap.add_argument("--no-writes", action="store_true", help="skip the count of values examined (its span log is large)")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    ap.add_argument("--keep", type=pathlib.Path, help="an absolute folder for every report and span log")
    a = ap.parse_args()
    for name in ("build", "control", "stock", "mixed", "mixed_control"):      # runs change into digikit's folder
        if getattr(a, name) is not None:
            setattr(a, name, getattr(a, name).resolve())
    EP.chunk_of(a.build)
    images = {"build": a.build, "control": a.control}
    names = [n for n in NAMES if not a.case or n in a.case]
    if a.mixed and a.mixed_control:
        images |= {"mixed": a.mixed, "mixed-control": a.mixed_control}
    elif "mixed-drum-full" in names:
        raise SystemExit("mixed-drum-full needs --mixed and --mixed-control")
    with tempfile.TemporaryDirectory() as scratch:
        folder = a.keep or pathlib.Path(scratch)
        folder.mkdir(parents=True, exist_ok=True)
        with ThreadPoolExecutor(a.jobs) as pool:
            results = list(pool.map(lambda n: case(pattern(n), images, a.stock, folder, not a.no_writes,
                                                   a.keep is not None), names))
        failed = 0
        for name, (problems, result) in zip(names, results):
            failed += bool(problems)
            print(f"{name:16s} {'FAIL' if problems else 'ok'}" + "".join(f"\n    {p}" for p in problems))
            if result:
                print("    " + json.dumps(result))
        if a.gates:
            print()
            for line in gates(images, a.stock, folder, a.jobs):
                failed += " FAIL" in line.splitlines()[0] or "failed" in line.splitlines()[0]
                print(line)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
