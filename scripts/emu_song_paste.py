"""Pasting into the song editor with something else on the clipboard, in the emulator.

    python scripts/emu_song_paste.py BUILD.syx [--lfo4] [--out DIR]

rivvi's song 1 holds two rows overwritten with data that is not song data
(docs/song-rows-report.md): one of them 16-bit values near an LFO speed's default.
The owner's question, 2026-10-10: can a paste do that, from an LFO page or from
LFO4's, on stock and on rivvi's mod set?

One panel_drive boot from reset per case. Each case copies something, opens the
song editor on song 1 ([FUNC] + [SONG] + [TRIG 1]), inserts two rows ([FUNC] +
[DOWN] twice), selects row 02, reads song 1 (stored and live), pastes ([FUNC] + [STOP]) and reads
it again. A frame is kept after each stage.

| case | what is copied | pass |
|---|---|---|
| control | row 02, given another length, copied ([FUNC] + [REC]) and pasted onto row 01 | row 01 changes: the paste keys work |
| lfo1 .. lfo3 | an LFO page ([MOD] + [REC]) | song 1 does not change |
| lfo4 (`--lfo4`) | LFO4's page (the fourth [MOD] page) | song 1 does not change |
| track | a track ([TRK] + [REC]) | song 1 does not change |
| pattern | a pattern ([FUNC] + [REC] outside the editor) | song 1 does not change |

`--onto-pages` is the other direction: LFO1's page (and LFO4's with `--lfo4`) copied,
then pasted on every other page ([page key] + [STOP]), on a track ([TRK] + [STOP]) and
on a pattern ([FUNC] + [STOP]). After each paste all sixteen songs are read, stored and
live (they must not change), and the playing kit (how many bytes the paste moved).
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PANEL = ROOT.parent / "digikit-rust/out/native/target-host/release/examples/panel_drive.exe"

MOD, NO, UP, DOWN, TRK, FUNC, REC, STOP, SONG, TRIG1 = 6, 12, 11, 14, 16, 17, 19, 21, 24, 25
STORED, STORED_LEN = 0x4120C970, 0xC00          # song 1 in the working image
LIVE, LIVE_LEN = 0x423FE4EB, 3694               # song 1 as the editor holds it
ROWS_AT, ROW = 0x1B, 37                         # live rows: 37 bytes each from +0x1b
READ = [f"peek:0x{STORED:08x}:{STORED_LEN}", f"peek:0x{LIVE:08x}:{LIVE_LEN}"]


def chord(held, key):
    return [f"press:{held}", "wait:10M", f"tap:{key}", "wait:10M", f"release:{held}", "wait:60M"]


def song_edit():
    return [f"press:{FUNC}", "wait:5M", f"press:{SONG}", "wait:10M", f"tap:{TRIG1}", "wait:10M",
            f"release:{SONG}", "wait:5M", f"release:{FUNC}", "wait:60M",
            *chord(FUNC, DOWN), *chord(FUNC, DOWN),
            f"tap:{UP}", "wait:40M", "frame:2_song_edit"]    # the cursor starts on END: up to row 02


def copy_steps(case):
    if case.startswith("lfo"):
        page = int(case[3:])
        return [f"tap:{MOD}", "wait:40M"] + [s for _ in range(page - 1) for s in (f"tap:{DOWN}", "wait:40M")] \
            + ["frame:0_page", *chord(MOD, REC), "frame:1_copied"]
    if case == "track":
        return [*chord(TRK, REC), "frame:1_copied"]
    if case == "pattern":
        return [*chord(FUNC, REC), "frame:1_copied"]
    return []


def steps(case):
    out = [f"tap:{NO}", "wait:30M", *copy_steps(case), *song_edit()]
    if case == "control":
        # row 02 made different from row 01 (its length byte), copied, pasted onto row 01
        out += [f"poke:0x{LIVE + ROWS_AT + ROW + 7:08x}:20", *chord(FUNC, REC), "frame:1_copied",
                f"tap:{UP}", "wait:40M", "frame:2b_row01"]
    return out + READ + [*chord(FUNC, STOP), "frame:3_pasted"] + READ


def run(build, case, out):
    out.mkdir(parents=True, exist_ok=True)
    script = out / "steps"
    script.write_text("\n".join(steps(case)), newline="\n")
    r = subprocess.run([str(PANEL), build, "--out", str(out), "--steps", f"@{script}"],
                       capture_output=True, text=True, timeout=600)
    d = json.loads(r.stdout)
    if d["outcome"] != "done":
        return f"{d['outcome']} {d['fault']}", None
    stored0, live0, stored1, live1 = [bytes.fromhex(x["hex"]) for x in d["results"] if "peek" in x]
    return None, [(name, [i for i in range(len(a)) if a[i] != b[i]], a, b)
                  for name, a, b in (("stored", stored0, stored1), ("live", live0, live1))]


# --- an LFO page pasted everywhere else -------------------------------------------------
TRIG, SYN, FLTR, AMP, FX = 1, 2, 3, 4, 5
SONGS, SONGS_LEN = STORED, 0xC00 * 16            # all sixteen songs, stored
LIVES, LIVES_LEN = LIVE, LIVE_LEN * 16           # and as the editor holds them
KIT, KIT_LEN = 0x4210C0C0, 23921                 # the kit buffer the emulator plays
WIDE = [f"peek:0x{SONGS:08x}:{SONGS_LEN}", f"peek:0x{LIVES:08x}:{LIVES_LEN}", f"peek:0x{KIT:08x}:{KIT_LEN}"]


def page(key, n):
    """Open page `n` (1-based) of a page key: to the top, then down."""
    return [f"tap:{key}", "wait:40M"] + [f"tap:{UP}", "wait:30M"] * 4 + [f"tap:{DOWN}", "wait:40M"] * (n - 1)


def targets(mod_pages, source):
    out = [("TRIG %d" % n, page(TRIG, n), TRIG) for n in (1, 2)]
    out += [("SYN %d" % n, page(SYN, n), SYN) for n in (1, 2, 3, 4)]
    out += [("FLTR %d" % n, page(FLTR, n), FLTR) for n in (1, 2)]
    out += [("AMP", page(AMP, 1), AMP), ("FX", page(FX, 1), FX)]
    out += [("LFO%d" % n, page(MOD, n), MOD) for n in range(1, mod_pages + 1) if n != source]
    out += [("track", page(SYN, 1), TRK), ("pattern", page(SYN, 1), FUNC)]
    return out


def onto_pages(build, source, mod_pages, out):
    """Copy LFO `source`'s page, paste it on every other page, a track and a pattern."""
    out.mkdir(parents=True, exist_ok=True)
    todo = targets(mod_pages, source)
    st = [f"tap:{NO}", "wait:30M", *page(MOD, source), *chord(MOD, REC), "frame:00_copied", *WIDE]
    for i, (name, go, held) in enumerate(todo, 1):
        st += [*go, *chord(held, STOP), "frame:%02d_%s" % (i, name.replace(" ", "")), *WIDE]
    script = out / "steps"
    script.write_text(chr(10).join(st), newline=chr(10))
    r = subprocess.run([str(PANEL), build, "--out", str(out), "--steps", f"@{script}"],
                       capture_output=True, text=True, timeout=900)
    d = json.loads(r.stdout)
    if d["outcome"] != "done":
        print(f"  FAIL LFO{source}: {d['outcome']} {d['fault']}")
        return False
    pk = [bytes.fromhex(x["hex"]) for x in d["results"] if "peek" in x]
    ok = True
    for i, (name, _, _) in enumerate(todo):
        a, b = pk[3 * i:3 * i + 3], pk[3 * i + 3:3 * i + 6]
        song = sum(x != y for x, y in zip(a[0] + a[1], b[0] + b[1]))
        kit = sum(x != y for x, y in zip(a[2], b[2]))
        ok &= not song
        print(f"  {'ok  ' if not song else 'FAIL'} LFO{source} pasted on {name:8s} songs: {song} bytes changed; kit: {kit} bytes changed")
    return ok


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("build")
    p.add_argument("--lfo4", action="store_true", help="the build has LFO4: copy its page too")
    p.add_argument("--out", default=str(ROOT / "out/song-paste"))
    p.add_argument("--onto-pages", action="store_true",
                   help="copy each LFO page and paste it on every other page, a track and a pattern")
    a = p.parse_args(argv)
    if a.onto_pages:
        pages = 4 if a.lfo4 else 3
        ok = True
        for source in ([1, 4] if a.lfo4 else [1]):
            ok &= onto_pages(a.build, source, pages, pathlib.Path(a.out) / pathlib.Path(a.build).stem / f"pages_lfo{source}")
        print("PASS" if ok else "FAIL")
        return 0 if ok else 1
    cases = ["control", "lfo1", "lfo2", "lfo3"] + (["lfo4"] if a.lfo4 else []) + ["track", "pattern"]
    ok = True
    for case in cases:
        fault, diffs = run(a.build, case, pathlib.Path(a.out) / pathlib.Path(a.build).stem / case)
        if fault:
            print(f"  FAIL {case}: {fault}")
            ok = False
            continue
        changed = any(d for _, d, _, _ in diffs)
        good = changed if case == "control" else not changed
        ok &= good
        print(f"  {'ok  ' if good else 'FAIL'} {case}: song 1 {'changed' if changed else 'unchanged'} by the paste")
        for name, d, old, new in diffs:
            if d:
                print(f"         {name} +0x{d[0]:x}..+0x{d[-1]:x}, {len(d)} bytes: "
                      f"{old[d[0]:d[-1] + 1].hex()[:80]} -> {new[d[0]:d[-1] + 1].hex()[:80]}")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
