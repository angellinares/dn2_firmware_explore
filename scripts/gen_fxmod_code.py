"""Pre-assemble the FX modulation mod for the browser and the CLI.

    python scripts/gen_fxmod_code.py [--os 1.12]

Runs `build_fxbrowser.compose` — with `build_fxbrowser2`'s four extra conversion
sites and `build_fxbrowser3`'s group-name longword, which together are the
build that works on the instrument — on the user's own stock 1.11 image, and
writes what it changed as data. The same pattern as `gen_midiarp_code.py`:

- `edits`: every in-image run the build changes, with the **stock bytes it
  expects** and the new bytes. The code cave is one edit, so its stock guard is
  the whole free run and the browser refuses an image where something already
  lives there;
- `guards`: the 25 sites the build *reads* and reasons from but does not write —
  whole instructions around each edit, the enumeration loop, the sort
  comparator, the group-name table's neighbours. An edit's own stock bytes can
  be a single byte, which is not enough to identify a build.

The slot lookup goes on the platform's hook bus (`dnfw.mods.bus`): the build's
hook at `0x400dc02a` is left out, and its code in the cave becomes a handler of
`ev_param_slot`. Where the build's code replays the three stock instructions
and jumps back, the handler answers 0 (`moveq #0,%d0 ; rts`): not taken, so the
bus asks the next handler and then the stock routine. The build's guard on the
resume point `0x400dc032` goes with the jump, because the bus resumes there.

Nothing derived from Elektron's tables ships: every byte here is either one this
project wrote (the cave, the hooks, the repointed addresses) or a mask constant
and a pointer that already exist in the user's own image, and the `stock` fields
are guards the mod compares against the file the user supplies.

Outputs `src/dnfw/mods/fxmod_code.json` and `site/js/mods/fxmod-code.js`, or with `--os 1.12`
the 1.12 build beside them, `fxmod_code_1.12.json` and `fxmod-code-1.12.js` (issue #382): the
anchor is 1.11's mapped (`build_fxbrowser.anchor_for`).
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dnfw.checkout import resources_dir                        # noqa: E402
from dnfw.cli.files import read_image                          # noqa: E402
from dnfw.firmware.load import load                            # noqa: E402

import build_fxbrowser as one                                  # noqa: E402
import build_fxbrowser2 as two                                 # noqa: E402
import build_fxbrowser3 as three                               # noqa: E402

STOCKS = {"1.11": "00_Firmware/Digitone_II_OS1.11_dist.zip",       # under 00_Resources (issue #382)
          "1.12": "00_Firmware/Digitone_II_OS1.12.syx"}


def outputs(os: str):
    """(the spec, its web copy) for OS: 1.11 keeps its names (issue #382)"""
    if os == "1.11":
        return ROOT / "src/dnfw/mods/fxmod_code.json", ROOT / "site/js/mods/fxmod-code.js"
    return ROOT / f"src/dnfw/mods/fxmod_code_{os}.json", ROOT / f"site/js/mods/fxmod-code-{os}.js"

# What the destination list gains, for the page to show. Entry numbers are this
# image's; the mod never uses them, it uses the records' own group and id.
DESTINATIONS = [
    ("Chorus", ["DPTH Depth", "SPD Speed", "HPF High-pass", "WDTH Width",
                "DEL Delay Send", "REV Reverb Send", "VOL Mix Volume"]),
    ("Delay", ["TIME Time", "X Ping-pong", "WID Stereo Width", "FDBK Feedback Gain",
               "HPF High-pass", "LPF Low-pass", "REV Reverb Send", "VOL Mix Volume",
               "DEL Delay Overdrive"]),
    ("Reverb", ["PRE Pre-delay", "DEC Decay Time", "FREQ Shelving Freq",
                "GAIN Shelving Gain", "HPF High-pass", "LPF Low-pass",
                "VOL Mix Volume", "REV Reverb Routing"]),
]


def regions(built: dict) -> list[tuple[int, int, str]]:
    """(start, end, what) for every range the build declares it writes.

    Every changed byte must fall inside one of these. That is the same claim
    `build_fxbrowser._verify` makes, restated here so the labels on the edits
    cannot drift away from the edits.
    """
    anchor, base = built["anchor"], one.BASE
    cave_address, used = built["cave"]
    out = [(cave_address - base, cave_address - base + used, "the code cave")]
    for key, what in (("eval_bound", "the evaluator's DEST bound, 100 -> 127"),
                      ("enum_bound", "the enumeration walk, 0..100 -> 0..124")):
        out.append((anchor[key][0] - base + 1, anchor[key][0] - base + 2, what))
    for key, what in (("eval_hook", "the evaluator's hook into the cave"),
                      ("slot_hook", "the slot lookup's hook into the cave")):
        site = anchor[key][0]
        out.append((site - base, site - base + len(bytes.fromhex(anchor[key][1])), what))
    for address, why in anchor["convert"]:
        out.append((address - base + 2, address - base + 6, f"entry -> code: {why}"))
    for entry in one.OPEN_RECORDS:
        at = anchor["records"] - base + one.RECORD_SIZE * (entry - 1) + 4 * one.MASK_WORD
        out.append((at, at + 4, f"entry {entry}: +44 opened to 0x1e00"))
    for address, _stock, _new, why in anchor["extra"]:
        out.append((address - base, address - base + 4, why))
    return out


NOT_TAKEN = bytes.fromhex("70004e75")              # moveq #0,%d0 ; rts


def on_the_bus(edits: list[dict], anchor: dict, cave_va: int) -> tuple[list[dict], int, int]:
    """The slot hook as a bus handler: -> (edits without the hook, the handler, the
    cave's length). The handler is the hook's target; its replay of the displaced
    stock bytes and its jump back, the cave's last 14 bytes, become NOT_TAKEN."""
    slot_site, slot_resume = anchor["slot_hook"][0], anchor["slot_hook"][2]
    hook = next(e for e in edits if e["va"] == slot_site)
    new = bytes.fromhex(hook["new"])
    if new[:2] != bytes.fromhex("4ef9") or len(new) != 8:
        raise SystemExit(f"the slot hook is not a jmp: {hook['new']}")
    handler = int.from_bytes(new[2:6], "big")
    cave = next(e for e in edits if e["what"] == "the code cave")
    body = bytes.fromhex(cave["new"])
    tail = bytes.fromhex(anchor["slot_hook"][1]) + bytes.fromhex("4ef9") + slot_resume.to_bytes(4, "big")
    if not body.endswith(tail) or not cave_va < handler < cave_va + len(body):
        raise SystemExit("the slot hook's replay is not the cave's tail")
    body = body[:-len(tail)] + NOT_TAKEN
    cave["new"], cave["stock"] = body.hex(), cave["stock"][:2 * len(body)]
    return [e for e in edits if e is not hook], handler, len(body)


def main() -> int:
    a = one.ANCHORS[3_192_192]
    a["convert"] = a["convert"] + two.MISSED
    a["controls"] = a["controls"] + three.CONTROLS
    one.EXTRA_LONGWORDS.append(three.EDIT)

    os = sys.argv[sys.argv.index("--os") + 1] if "--os" in sys.argv else "1.11"
    firmware = load(read_image(resources_dir(ROOT) / STOCKS[os]))
    section = firmware.container.find(one.MAIN_OS)
    stock = section.unpack()
    built = one.compose(stock, section.dest, log=lambda *_: None, os=os)
    content = built["content"]
    a = built["anchor"]                           # OS's: 1.11's, mapped

    labels = regions(built)
    cave_address, used = built["cave"]
    cave = range(cave_address - one.BASE, cave_address - one.BASE + used)

    edits, i, n = [], 0, len(stock)
    while i < n:
        if i == cave.start:
            edits.append({"va": cave_address, "stock": stock[cave.start:cave.stop].hex(),
                          "new": content[cave.start:cave.stop].hex(),
                          "what": "the code cave"})
            i = cave.stop
            continue
        if stock[i] == content[i]:
            i += 1
            continue
        j = i
        while j < n and stock[j] != content[j] and j != cave.start:
            j += 1
        what = next((w for lo, hi, w in labels if lo <= i and j <= hi), None)
        if what is None:
            raise SystemExit(
                f"0x{one.BASE + i:08x}..0x{one.BASE + j:08x} changed but no declared "
                f"region covers it -- regions() has drifted from the build")
        edits.append({"va": one.BASE + i, "stock": stock[i:j].hex(),
                      "new": content[i:j].hex(), "what": what})
        i = j

    if any(int(e["stock"], 16) for e in edits if e["what"] == "the code cave"):
        raise SystemExit("the cave's stock bytes are not all zero -- it is not free")
    edits, handler, used = on_the_bus(edits, a, cave_address)

    code = {
        "os": f"Digitone II {os}",
        "stock_length": n,
        "cave_va": cave_address,
        "cave_used": used,
        "bus": {"event": "PSLT", "handler": handler},
        "edits": edits,
        # Read, not written. `build_fxbrowser3.CONTROLS` is in here: the three
        # group-name slots and the three records whose short names they share
        # are the whole argument for the `ERR` -> `CHR` longword, and an
        # argument that is not checked is prose.
        "guards": [{"va": va, "bytes": want, "what": why}
                   for va, want, why in a["controls"] if va != a["slot_hook"][2]],
        "destinations": [{"group": g, "parameters": p} for g, p in DESTINATIONS],
    }
    out_json, out_js = outputs(os)
    flag = "" if os == "1.11" else f" --os {os}"
    out_json.write_text(json.dumps(code, indent=1) + "\n", newline="\n")
    out_js.write_text(f"// Generated by scripts/gen_fxmod_code.py{flag} -- do not edit by hand.\n"
                      "export const CODE = " + json.dumps(code, indent=1) + ";\n",
                      newline="\n")
    changed = sum(len(e["new"]) // 2 for e in edits)
    print(f"{len(edits)} edits, {changed} bytes, cave {used} B at {cave_address:#010x}, "
          f"{len(code['guards'])} guards")
    print(f"  wrote {out_json.relative_to(ROOT)}")
    print(f"  wrote {out_js.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
