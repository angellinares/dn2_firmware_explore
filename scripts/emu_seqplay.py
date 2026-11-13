"""Play the sequencer in the emulator and list the notes it sends the DSP.

    python scripts/emu_seqplay.py BUILD.syx [--trigs 1,5,9,13] [--track 2:3,11] [--run 700M]
        [--note 5:4 ...] [--chord 4,3 [--chord-length 60]] [--arp UP]

Boots BUILD from reset with SSI0 paced (the audio-frame interrupt, and with it the forced
interrupts that tick the sequencer, run: digikit finding 04, "The internal step clock"),
enters the trigs with RECORD and the trig keys, presses PLAY and captures every frame sent
to the DSP. Prints each note-on (voices and note numbers) and note-off with its time, and
checks that the note-ons keep to the spacing of the trigs' steps.

`--trigs` is track 1's steps; each `--track N:STEPS` adds a track (TRK held, then trig key N).
The note comes from the frame header, one word per voice. Track 1's trigs can be given
other notes and a chord, and the active track an arp mode, through the panel:

- `--note STEP:SEMITONES`: with the TRIG page open, the trig held in GRID RECORDING while
  encoder A moves its NOTE.
- `--chord INTERVALS`: NOTE EDIT on the first trig (the trig held, then STACK), a note added
  per interval (FUNC + DOWN), each that many semitones above the last (encoder E); with
  `--chord-length`, every note made that many units longer (FUNC + encoder G).
- `--arp MODE`: the ARP menu, MODE turned up from OFF (encoder A).

A turn moves a value one unit per 28 counts, sent 10 counts at a time, since a larger turn
is often dropped. These sequences and counts were found with angellinares/digikit's
`tools/seqplay.py` (digikit PRs #69, #70 and #72); the key codes are the firmware's own
names (its button table, `0x401f3824`).

The step period is read from the run, not assumed: 120 BPM is 16.5 M instructions a step at
the 132 MHz the SSI lane paces against. Needs a panel_drive with `service_forced` (digikit
#65) and a literal `--capture` length (digikit branch feat/capture-literal-len).
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw import seqframes as SF                                    # noqa: E402

PANEL_CANDIDATES = (
    ROOT.parent / "digikit-wt-forced/out/target/release/examples/panel_drive.exe",
    ROOT.parent / "digikit-rust/out/native/target-host/release/examples/panel_drive.exe",
)
EXCHANGE = "0x400cf7be"      # the audio ISR's send/receive to the DSP; argument 1 is the frame (1.11)
NO, RECORD, PLAY, STOP, TRK, TRIG1 = 12, 19, 20, 21, 16, 25
TRIG_PAGE, FUNC, DOWN, ARP, STACK = 1, 17, 14, 51, 53    # the firmware's names: TRIG, ..., STACK
ENCODER_A, ENCODER_E, ENCODER_G = 1, 5, 7
ARP_MODES = ("OFF", "TRUE", "UP", "DOWN", "CYCL")         # the arp menu's MODE, in order (0x401d4b0c)
COUNTS_PER_UNIT = 28        # a turn's counts for one unit of NOTE, the arp's MODE or a note's LEN
TURN_STEP = 10              # counts sent at a time


def use(os_version: str) -> None:
    """Capture OS_VERSION's exchange routine (issue #382): 1.12's is 1.11's moved by the map"""
    from dnfw import osport
    global EXCHANGE
    EXCHANGE = f"{osport.addr(os_version, 0x400CF7BE):#010x}"


def panel_drive() -> pathlib.Path:
    chosen = os.environ.get("PANEL_DRIVE")
    for path in ([pathlib.Path(chosen)] if chosen else []) + list(PANEL_CANDIDATES):
        if path.exists():
            return path
    raise SystemExit("panel_drive.exe not found; set PANEL_DRIVE")


def turn(encoder: int, units: int) -> list[str]:
    """ENCODER turned by UNITS of its value (down when negative), TURN_STEP counts at a time."""
    counts, sign = abs(units) * COUNTS_PER_UNIT, 1 if units > 0 else -1
    steps: list[str] = []
    for sent in range(0, counts, TURN_STEP):
        steps += [f"turn:{encoder}:{sign * min(TURN_STEP, counts - sent)}", "wait:15M"]
    return steps


def note_steps(step: int, semitones: int) -> list[str]:
    """In GRID RECORDING, with the TRIG page open: STEP's trig held while its NOTE moves."""
    key = TRIG1 + step - 1
    return [f"press:{key}", "wait:40M"] + turn(ENCODER_A, semitones) + [f"release:{key}", "wait:30M"]


def chord_steps(step: int, intervals: list[int], length: int) -> list[str]:
    """In GRID RECORDING: NOTE EDIT on STEP's trig, a note added per INTERVALS entry, each that
    many semitones above the last, then every note LENGTH units longer."""
    key = TRIG1 + step - 1
    steps = [f"press:{key}", "wait:40M", f"tap:{STACK}", "wait:60M", f"release:{key}", "wait:30M"]
    for semitones in intervals:
        steps += [f"press:{FUNC}", f"tap:{DOWN}", f"release:{FUNC}", "wait:40M"]
        steps += turn(ENCODER_E, semitones) + ["wait:30M"]
    if length:
        steps += [f"press:{FUNC}"] + turn(ENCODER_G, length) + [f"release:{FUNC}", "wait:30M"]
    return steps + [f"tap:{NO}", "wait:40M"]


def arp_steps(mode: str) -> list[str]:
    """The active track's arp MODE, turned up from OFF (a fresh pattern's) in the ARP menu."""
    return ([f"tap:{ARP}", "wait:40M"] + turn(ENCODER_A, ARP_MODES.index(mode))
            + ["wait:20M", f"tap:{NO}", "wait:40M"])


def script(tracks: dict[int, list[int]], run: str, *, notes: dict[int, int] | None = None,
           chord: list[int] | None = None, chord_length: int = 0, arp: str | None = None) -> list[str]:
    """The panel steps that enter TRACKS' trigs and play them for RUN. NOTES (step ->
    semitones) and CHORD (intervals, on the first trig) go to track 1; ARP to the track
    entered last."""
    entered: list[str] = [f"tap:{TRIG_PAGE}", "wait:30M"] if notes else []
    for track, trigs in sorted(tracks.items()):
        if track != 1 or len(tracks) > 1:
            entered += [f"press:{TRK}", "wait:10M", f"tap:{TRIG1 + track - 1}",
                        f"release:{TRK}", "wait:30M"]
        entered += [f"tap:{RECORD}"] + [f"tap:{TRIG1 + t - 1}" for t in trigs]
        if track == 1 and (notes or chord):
            entered += ["wait:30M"]
            for step, semitones in sorted((notes or {}).items()):
                entered += note_steps(step, semitones)
            if chord:
                entered += chord_steps(trigs[0], chord, chord_length)
        entered += [f"tap:{RECORD}", "wait:30M"]
    if arp:
        entered += arp_steps(arp)
    return (["wait:1500M", f"tap:{NO}", "wait:60M"] + entered
            + ["wait:50M", f"tap:{PLAY}", f"wait:{run}", f"tap:{STOP}", "wait:20M"])


def play(build: pathlib.Path, tracks: dict[int, list[int]], run: str = "700M",
         ssi_hz: str = "96000", keep: pathlib.Path | None = None, **entry) -> list[SF.NoteEvent]:
    """Boot BUILD, play the trigs, and return the note events; raises RuntimeError on a fault.
    ENTRY is `script`'s notes, chord, chord_length and arp."""
    cmd = [str(panel_drive()), str(build), "--ssi-hz", ssi_hz,
           "--capture", f"{EXCHANGE}:1:48", "--steps", ",".join(script(tracks, run, **entry))]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=1500)
    if not done.stdout.strip():
        raise RuntimeError(done.stderr[-300:])
    result = json.loads(done.stdout)
    if keep:
        keep.write_text(done.stdout)
    if result["outcome"] != "done":
        raise RuntimeError(f"fault: {result['fault']}")
    return SF.events(result["captures"])


def parse_tracks(trigs: str, extra: list[str]) -> dict[int, list[int]]:
    tracks = {1: [int(t) for t in trigs.split(",")]}
    for spec in extra:
        number, steps = spec.split(":")
        tracks[int(number)] = [int(t) for t in steps.split(",")]
    return tracks


def signature(found: list[SF.NoteEvent]) -> list[tuple]:
    """What a build did, with times from its first note-on: comparable between builds."""
    ons = SF.note_ons(found)
    t0 = ons[0].icount if ons else 0
    return [(e.icount - t0, e.kind, e.voices, e.notes) for e in found if e.icount >= t0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("build", type=pathlib.Path)
    ap.add_argument("--trigs", default="1,5,9,13", help="steps of track 1, 1-based, ascending")
    ap.add_argument("--track", action="append", default=[], metavar="N:STEPS",
                    help="another track's steps, e.g. 2:3,11 (repeatable)")
    ap.add_argument("--run", default="700M", help="instructions to play for")
    ap.add_argument("--ssi-hz", default="96000")
    ap.add_argument("--json", type=pathlib.Path, help="keep panel_drive's output here")
    ap.add_argument("--note", action="append", default=[], metavar="STEP:SEMITONES",
                    help="move a trig of track 1 from C4, e.g. 5:4 (repeatable)")
    ap.add_argument("--chord", metavar="INTERVALS",
                    help="a chord on track 1's first trig, each note that many semitones above the last, e.g. 4,3")
    ap.add_argument("--chord-length", type=int, default=0, help="units added to the chord's note length")
    ap.add_argument("--arp", choices=ARP_MODES[1:], help="the arp's mode on the track entered last")
    a = ap.parse_args()
    tracks = parse_tracks(a.trigs, a.track)
    notes = {int(step): int(semitones) for step, semitones in (spec.split(":") for spec in a.note)}
    chord = [int(i) for i in a.chord.split(",")] if a.chord else None
    try:
        found = play(a.build, tracks, a.run, a.ssi_hz, a.json, notes=notes, chord=chord,
                     chord_length=a.chord_length, arp=a.arp)
    except RuntimeError as error:
        print(error)
        return 2

    ons = SF.note_ons(found)
    if not ons:
        print("no note-on reached the DSP")
        return 1
    t0 = ons[0].icount
    print(f"{len(ons)} note-ons, {len(found) - len(ons)} note-offs")
    for e in found:
        notes = f"  notes {list(e.notes)}" if e.notes else ""
        print(f"  {SF.seconds(e.icount - t0):7.3f} s  {e.kind:3}  voices {list(e.voices)}{notes}")

    if a.arp:
        print("the arp plays between the trigs, so their spacing is not checked")
        return 0
    spacing = SF.gaps(found)
    # trigs repeat every 16 steps: the gaps between the steps any track plays on, then the
    # wrap to the first (a step two tracks share is one event: their voices are one mask)
    trigs = sorted({t for steps in tracks.values() for t in steps})
    steps = [b - a_ for a_, b in zip(trigs, trigs[1:])] + [16 - trigs[-1] + trigs[0]]
    expected = [steps[i % len(steps)] for i in range(len(spacing))]
    per_step = [g / s for g, s in zip(spacing, expected)]
    if per_step:
        mean = sum(per_step) / len(per_step)
        worst = max(abs(p - mean) / mean for p in per_step)
        print(f"step period {mean / 1e6:.2f} M instructions = {SF.bpm(mean):.1f} BPM; "
              f"worst gap off by {worst * 100:.2f}%")
        return 0 if worst < 0.02 else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
