"""Issue #317 in the emulator: a held trig plus an encoder push clears an arp p-lock.

    python scripts/emu_arp_push_clear.py BUILD.syx [--expect-fail]

Drives digikit's `panel_drive` from reset (found through `PANEL_DRIVE`, else the
`digikit-wt-flushchk` build beside this checkout) and reads the pattern's lock
table (80 records of 258 B, the step lock counts at +22256) with `peek`:

1. **The control, a stock parameter.** SYN page 1, GRID RECORDING on, TRIG 1
   held, encoder E turned: a HARM lock. TRIG 1 held, encoder E pushed: the lock
   goes and the step's count is 0. This is the stock clear, and it must pass on
   every build.
2. **The arp.** The ARPEGGIATOR menu, TRIG 1 held, encoders A and B turned: MODE
   and SPEED locks. Push A: only MODE goes. Push B: SPEED goes, the count is 0.
   C and D turned (RANGE, N.LEN), then pushed together: both go. Push A with no
   trig held: nothing changes.
3. **Several held trigs.** MODE locked on TRIG 1, 2 and 3; TRIG 1 and 2 held, push
   A: their locks go, TRIG 3's stays.
4. **A nudge while the knob is down** (on the unit, 2026-11-01: a real knob turns
   a little when it is pushed). For HARM and for each arp knob A..D: TRIG 1 held,
   the knob turned (a lock, and the knob's count filter awake), pushed, turned one
   count while down, released. The lock must be gone. Then, with TRIG 1 held, a
   turn after the release locks again, as on a stock page.

A build for OS 1.12 (issue #382) runs the same steps: the recount's store is the same
instruction at the same address there, and the fault watch is 1.12's. Stock 1.12 is the
control for the arp checks: it passes the HARM ones and fails every arp one.

Builds without the fix: `--expect-fail` for 0.1.0 (no push clear) and
`--expect-nudge-fail` for 0.1.1 (it clears on the press, and the nudge locks
again). The HARM controls must pass on every build.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw.checkout import resources_dir  # noqa: E402
from dnfw.cli.files import read_image  # noqa: E402
from dnfw.firmware.load import load  # noqa: E402
from dnfw.mods import specs  # noqa: E402

STOCK = resources_dir(ROOT) / "00_Firmware/Digitone_II_OS1.11_dist/Digitone_II_OS1.11.syx"
FAULT = {"1.11": 0x4011EA6A, "1.12": 0x4011ED4A}   # the fault handler: never reached on a good run
MAIN = ROOT.parents[2] if ROOT.parent.name == "worktrees" else ROOT
CANDIDATES = [p.parent / "digikit-wt-flushchk/out/target/release/examples/panel_drive.exe"
              for p in (ROOT, MAIN)]
RECOUNT_STORE = 0x4003CEE0      # `move.b %d4,%a0@(22256)`: a0 is the lock table (1.11 and 1.12)
REC, RECS, COUNTS = 258, 80, 22256
TRIG1, RECORD, ARP, PUSH_A = 25, 19, 51, 41
BOOT = "wait:1100M,tap:12,wait:40M,tap:12,wait:40M"


def panel_drive() -> pathlib.Path:
    chosen = os.environ.get("PANEL_DRIVE")
    for path in ([pathlib.Path(chosen)] if chosen else []) + CANDIDATES:
        if path.exists():
            return path
    raise SystemExit("panel_drive.exe not found; set PANEL_DRIVE")


def turn(encoder: int, times: int = 12) -> str:
    return "".join(f",turn:{encoder}:10,wait:15M" for _ in range(times))


def drive(image: pathlib.Path, steps: str, table: int | None) -> dict:
    os_ = specs.of_firmware(load(read_image(image)))
    base = ["--base", hashlib.sha256(STOCK.read_bytes()).hexdigest()] if os_ == "1.11" else []
    peek = f"peek:{table or 0:#x}:{COUNTS + 16}"
    cmd = [str(panel_drive()), str(image), *base, "--regs-at", f"{RECOUNT_STORE:#x}",
           "--watch", f"{FAULT[os_]:#x}", "--steps", BOOT + "," + steps.replace("PEEK", peek)]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    result = json.loads(done.stdout)
    if result["outcome"] != "done" or any(w["hits"] for w in result["watched"]):
        raise SystemExit(f"{image.name}: {result['outcome']} {result.get('fault')} {result['watched']}")
    return result


def locks(raw: bytes) -> dict[tuple[int, int], dict[int, int]]:
    """-> {(record byte 0, byte 1): {step: value}} for every used record."""
    found = {}
    for i in range(RECS):
        rec = raw[i * REC:(i + 1) * REC]
        if rec[:2] != b"\xff\xff":
            found[(rec[0], rec[1])] = {s: int.from_bytes(rec[2 + 2 * s:4 + 2 * s], "big")
                                       for s in range(128) if rec[2 + 2 * s:4 + 2 * s] != b"\xff\xff"}
    return found


def snapshots(image: pathlib.Path, steps: str) -> list[tuple[dict, bytes]]:
    """Run STEPS twice: once to read the table's address, once to peek it at each PEEK."""
    first = drive(image, steps, None)
    # a0 there is the table plus the step: the lowest one seen is step 0's, the table
    tables = {int(r["a"][0], 16) for r in first["regs"] if r["pc"] == f"{RECOUNT_STORE:#010x}"}
    if not tables or max(tables) - min(tables) >= 128:
        raise SystemExit(f"{image.name}: lock table not found ({sorted(map(hex, tables))})")
    result = drive(image, steps, min(tables))
    return [(locks(raw), raw[COUNTS:COUNTS + 4])
            for raw in (bytes.fromhex(r["hex"]) for r in result["results"] if "peek" in r)]


failures: list[str] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  ({detail})"))
    if not ok:
        failures.append(name)


def main(argv: list[str]) -> int:
    image = pathlib.Path(argv[0])
    broken = "--expect-fail" in argv
    hold = f"press:{TRIG1},wait:40M"
    off = f"release:{TRIG1},wait:40M"

    print("control: a stock HARM lock, SYN page 1, encoder E")
    snap = snapshots(image, f"tap:{RECORD},wait:40M,press:{TRIG1},wait:30M{turn(5)},{off},PEEK,"
                            f"{hold},tap:45,wait:30M,{off},PEEK")
    check("HARM locked on step 1", (29, 0) in snap[0][0] and 0 in snap[0][0][(29, 0)], snap[0][0])
    check("trig held + push E clears it, count 0", not snap[1][0] and snap[1][1][0] == 0, snap[1])

    # In RAM an arp lock's record is (k, track | 0x20): MODE 0, RANGE 1, SPEED 2, N.LEN 3.
    mode, rng, spd, nlen = ((k, 0x20) for k in range(4))
    print("arp: MODE, SPEED, RANGE and N.LEN on TRIG 1" + ("  (expected to survive)" if broken else ""))
    snap = snapshots(image, f"tap:{RECORD},wait:40M,tap:{ARP},wait:40M,"
                            f"press:{TRIG1},wait:30M{turn(1)}{turn(2)},{off},PEEK,"
                            f"{hold},tap:41,wait:30M,{off},PEEK,"
                            f"{hold},tap:42,wait:30M,{off},PEEK,"
                            f"{hold}{turn(3)}{turn(4)},{off},PEEK,"
                            f"{hold},tap:43,wait:30M,tap:44,wait:30M,{off},PEEK,"
                            f"tap:41,wait:30M,PEEK")
    check("MODE and SPEED locked", set(snap[0][0]) == {mode, spd}, snap[0][0])
    if broken:
        check("push A leaves both (the bug)", set(snap[1][0]) == {mode, spd}, snap[1][0])
        check("push B leaves both (the bug)", set(snap[2][0]) == {mode, spd}, snap[2][0])
    else:
        check("push A clears MODE only", set(snap[1][0]) == {spd} and snap[1][1][0] == 1, snap[1])
        check("push B clears SPEED, count 0", not snap[2][0] and snap[2][1][0] == 0, snap[2])
        check("RANGE and N.LEN locked", set(snap[3][0]) == {rng, nlen}, snap[3][0])
        check("push C and D clear both, count 0", not snap[4][0] and snap[4][1][0] == 0, snap[4])
        check("push A with no trig held changes nothing", not snap[5][0], snap[5][0])

        print("arp: MODE on TRIG 1, 2 and 3; TRIG 1 and 2 held, push A")
        snap = snapshots(image, f"tap:{RECORD},wait:40M,tap:{ARP},wait:40M,press:25,wait:20M,"
                                f"press:26,wait:20M,press:27,wait:30M{turn(1)},release:27,"
                                f"release:26,release:25,wait:40M,PEEK,press:25,wait:20M,press:26,"
                                f"wait:30M,tap:41,wait:30M,release:26,release:25,wait:40M,PEEK")
        check("MODE locked on steps 1..3", snap[0][0].get(mode, {}).keys() == {0, 1, 2}, snap[0][0])
        check("steps 1 and 2 cleared, step 3 kept", snap[1][0].get(mode, {}).keys() == {2}
              and snap[1][1][:3] == b"\x00\x00\x01", snap[1])

    nudge_fail = "--expect-nudge-fail" in argv

    def nudged(enc: int) -> str:
        """ENC turned with TRIG 1 held, pushed, turned one count while down, released; PEEK;
        then turned again with TRIG 1 held; PEEK."""
        push = PUSH_A + enc - 1
        return (f"{hold}{turn(enc)},press:{push},wait:20M,turn:{enc}:1,wait:20M,release:{push},"
                f"wait:30M,{off},PEEK,{hold}{turn(enc)},{off},PEEK")

    print("nudge: HARM pushed, turned one count while down, released")
    snap = snapshots(image, f"tap:{RECORD},wait:40M,{nudged(5)}")
    check("HARM: nudge while down, the lock is gone", not snap[0][0], snap[0])
    check("HARM: a turn after the release locks again", (29, 0) in snap[1][0], snap[1][0])
    if not broken:
        print("nudge: each arp knob pushed, turned one count while down, released"
              + ("  (0.1.1: expected to lock again)" if nudge_fail else ""))
        snap = snapshots(image, f"tap:{RECORD},wait:40M,tap:{ARP},wait:40M,"
                                + ",".join(nudged(enc) for enc in (1, 2, 3, 4)))
        for n, rec in enumerate((mode, spd, rng, nlen)):
            knob, gone, back = "ABCD"[n], snap[2 * n][0], snap[2 * n + 1][0]
            if nudge_fail:
                check(f"knob {knob}: the nudge locks again (the bug)", rec in gone, gone)
            else:
                check(f"knob {knob}: nudge while down, the lock is gone", rec not in gone, gone)
                check(f"knob {knob}: a turn after the release locks again", rec in back, back)

    print(f"\n{'all passed' if not failures else str(len(failures)) + ' FAILED: ' + ', '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
