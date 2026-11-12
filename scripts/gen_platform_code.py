"""Assemble the platform loader once, for Python and the browser.

    python scripts/gen_platform_code.py [--os 1.12]

Builds `csrc/runtime/loader.S` (`dnfw.patch.loader.build`, an m68k toolchain;
WSL is fine) and writes the bytes the platform installs, so neither the CLI nor
the site needs a toolchain to apply a mod:

    src/dnfw/mods/platform_code.json
    site/js/mods/platform-code.js

It also assembles the hook bus's dispatchers (`dnfw.mods.bus.source`, at
`bus.BUS_VA`) and finds the parameter count's 55 bounds in the stock image
(`dnfw.patch.paramtable.bound_sites`), so neither needs a toolchain or a search
at apply time.

It then checks the result against `lfo4_code.json`: LFO4 was the first mod on
this loader and passed on the instrument, so the platform must install exactly
the loader and the start-up call LFO4 installs.

With `--os 1.12` (issue #382) it writes `platform_code_1.12.json` and `platform-code-1.12.js`
beside the 1.11 files: the loader built for 1.12 (`dn2_112.h`, its cave and area from
`dnfw.osport.versions`), the bus's sites and the machine bounds translated with
`dnfw.osport.addr`, and the parameter bounds found in the 1.12 image. Each translated site's
stock bytes are read in the 1.12 image and must be 1.11's; a mismatch stops the run.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw import osport                     # noqa: E402
from dnfw.checkout import resources_dir     # noqa: E402
from dnfw.cli.files import read_image      # noqa: E402
from dnfw.firmware.load import load        # noqa: E402
from dnfw.mods import bus                  # noqa: E402
from dnfw.patch import area, assemble, loader, paramtable  # noqa: E402

DATA_LIMIT = 0x46740000                    # lfowaves' NOIS state starts here
STOCKS = {"1.11": "00_Firmware/Digitone_II_OS1.11_dist.zip", "1.12": "00_Firmware/Digitone_II_OS1.12.syx"}
NL = chr(10)


def outputs(os: str) -> tuple[pathlib.Path, pathlib.Path]:
    """(the spec, its web copy) for OS: 1.11 keeps the names it always had"""
    if os == "1.11":
        return ROOT / "src/dnfw/mods/platform_code.json", ROOT / "site/js/mods/platform-code.js"
    return ROOT / f"src/dnfw/mods/platform_code_{os}.json", ROOT / f"site/js/mods/platform-code-{os}.js"


def stock_of(os: str) -> bytes:
    return load(read_image(resources_dir(ROOT) / STOCKS[os])).container.find(3).unpack()


def bus_sites(os: str, stock: bytes) -> dict[bytes, dict]:
    """Each event's site on OS and the stock bytes there, which must be 1.11's"""
    out = {}
    for event, e in bus.EVENTS.items():
        va = osport.addr(os, e["site"])
        here = stock[va - loader.BASE:va - loader.BASE + len(e["stock"]) // 2].hex()
        if here != e["stock"]:
            raise SystemExit(f"{e['name']}: {os} holds {here} at 0x{va:08x}, not 1.11's {e['stock']}")
        out[event] = {"site": va, "stock": here}
    return out


def bus_code(sites: dict[bytes, dict] | None = None) -> dict:
    names = [e["entry"] for e in bus.EVENTS.values()]
    text = bus.source({e: v["site"] for e, v in sites.items()} if sites else None)
    blob = assemble.assemble(text + NL + "    .align 2" + NL + NL.join(f"    .long {n}" for n in names) + NL,
                             base=bus.BUS_VA)
    code, symbols = blob[:-4 * len(names)], struct.unpack(f">{len(names)}I", blob[-4 * len(names):])
    entry = 4 * bus.TABLE_SLOTS * len(bus.EVENTS)       # the tables come first
    if (any(code[:entry]) or code[entry:entry + 2] != bytes.fromhex("2f0a")   # move.l %a2,-(%sp)
            or any(e["table"] != 4 * bus.TABLE_SLOTS * k for k, e in enumerate(bus.EVENTS.values()))):
        raise SystemExit("the bus's tables are not where bus.EVENTS says")
    out = {"load": bus.BUS_VA, "code": code.hex(), "symbols": dict(zip(names, symbols))}
    if sites:
        out["sites"] = {e.decode(): v for e, v in sites.items()}
    return out


def param_bounds(os: str, stock: bytes) -> list[list[int]]:
    return [[s.va, s.width, s.was] for s in paramtable.bound_sites(stock, loader.BASE, os)]


def machine_bounds(os: str, stock: bytes) -> list[list[int]]:
    """bus.MACHINE_BOUNDS on OS: each translated, and the stock value read there"""
    out = []
    for va, width, value, what in bus.MACHINE_BOUNDS:
        new = osport.addr(os, va)
        here = int.from_bytes(stock[new - loader.BASE:new - loader.BASE + width], "big")
        if here != value:
            raise SystemExit(f"{what}: {os} holds {here} at 0x{new:08x}, not {value}")
        out.append([new, width, value])
    return out


def generate(os: str = "1.11") -> dict:
    stock = stock_of(os)
    cave, link, area_va = loader.layout(os)
    if loader.BASE + len(stock) != area_va:
        raise SystemExit(f"{os}: MAIN OS ends at 0x{loader.BASE + len(stock):08x}, not 0x{area_va:08x}")
    calls = stock[loader.CALLS_VA - loader.BASE:loader.CALLS_VA - loader.BASE + 8]
    if calls != loader.CALLS_STOCK:
        raise SystemExit(f"{os}: the start-up calls are {calls.hex()}, not {loader.CALLS_STOCK.hex()}")
    if any(stock[cave - loader.BASE:cave - loader.BASE + loader.CAVE_CAP]):
        raise SystemExit(f"{os}: the loader's cave at 0x{cave:08x} is not empty")
    linked = loader.build(os=os)
    hook = b"\x4e\xb9" + struct.pack(">I", linked["dnfw_boot"]) + b"\x4e\x71"
    sites = bus_sites(os, stock) if os != "1.11" else None
    counts = {"PARM": param_bounds(os, stock)}
    if os != "1.11":
        counts["MACH"] = machine_bounds(os, stock)
    return {
        "os": f"Digitone II {os}",
        "stock_length": len(stock),
        "calls_va": loader.CALLS_VA, "calls_stock": loader.CALLS_STOCK.hex(), "hook": hook.hex(),
        "cave_va": cave, "cave_cap": loader.CAVE_CAP,
        "link_va": link, "loader": linked.image.hex(),
        "area_va": area_va, "runtime_va": area.RUNTIME_VA, "data_limit": DATA_LIMIT,
        "bus": bus_code(sites), "counts": counts,
    }


def check_against_lfo4(spec: dict) -> None:
    lfo4 = json.loads((ROOT / "src/dnfw/mods/lfo4_code.json").read_text())
    image = bytearray(spec["stock_length"])        # blank, but for the stock bytes the edits keep
    calls = spec["calls_va"] - loader.BASE
    image[calls:calls + 8] = loader.CALLS_STOCK
    for e in lfo4["edits"]:
        at = e["va"] - loader.BASE
        new = bytes.fromhex(e["new"])
        image[at:at + len(new)] = new
    link = spec["link_va"] - loader.BASE
    loader_bytes = bytes.fromhex(spec["loader"])
    if image[calls:calls + 8].hex() != spec["hook"]:
        raise SystemExit("the start-up call differs from the one lfo4 installs")
    if bytes(image[link:link + len(loader_bytes)]) != loader_bytes:
        raise SystemExit("the loader differs from the one lfo4 installs")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--os", default="1.11", choices=sorted(osport.VERSIONS))
    a = ap.parse_args()
    spec = generate(a.os)
    if a.os == "1.11":
        check_against_lfo4(spec)                   # LFO4 is a 1.11 build until it is ported
    out_json, out_js = outputs(a.os)
    out_json.write_text(json.dumps(spec, indent=1) + NL, newline=NL)
    flag = "" if a.os == "1.11" else f" --os {a.os}"
    out_js.write_text(f"// Generated by scripts/gen_platform_code.py{flag} -- do not edit by hand." + NL
                      + f"export const CODE = {json.dumps(spec, indent=1)};" + NL, newline=NL)
    print(f"{a.os}: loader {len(spec['loader']) // 2} B at 0x{spec['link_va']:08x}; hook {spec['hook']}"
          + ("; matches lfo4's" if a.os == "1.11" else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
