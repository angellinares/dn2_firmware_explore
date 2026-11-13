"""Our OS facts against two independent sources (issue #382). Each part skips when its checkout is absent.

- digikit's port files (`devices/ports/dn2-1.11.toml`, `dn2-1.12.toml`), written by its own resolver.
  For every anchor named on both versions that osport decides, osport's 1.12 address must equal
  digikit's. DNFW_DIGIKIT overrides the checkout (default: digikit-main beside this repository).
- elekloader's DN2 profile (`elekloader/devices/digitone_mk2.py`), measured on 1.12 by its authors.
  It must state our image hashes, MAIN OS length, end, clear end and DMA section. DNFW_ELEKLOADER
  overrides the checkout (default: elekloader beside this repository).

The 2026-11-13 run: digikit 263 anchors on both versions, 107 decided by osport, 107 equal, 0 different."""

import os
import pathlib
import tomllib

import pytest

from dnfw import osport
from dnfw.osport import versions
from dnfw.sharcemu import SIBLINGS

DIGIKIT = pathlib.Path(os.environ.get("DNFW_DIGIKIT") or SIBLINGS / "digikit-main")
ELEKLOADER = pathlib.Path(os.environ.get("DNFW_ELEKLOADER") or SIBLINGS / "elekloader")
PORTS = DIGIKIT / "devices/ports"
PROFILE = ELEKLOADER / "elekloader/devices/digitone_mk2.py"


def port(v):
    path = PORTS / f"dn2-{v}.toml"
    if not path.exists():
        pytest.skip(f"no digikit port file {path}")
    return tomllib.loads(path.read_text(encoding="utf-8"))


def anchors(v):
    return {a["name"]: a["addr"] for a in port(v).get("anchor", []) if a.get("cpu") == "cf"}


@pytest.mark.parametrize("v", ["1.11", "1.12"])
def test_digikit_reads_the_same_stock_image(v):
    p, ours = port(v)["port"], versions.VERSIONS[v]
    assert (p["syx_sha256"], p["main_sha256"]) == (ours.syx_sha256, ours.main_sha256)


def test_digikit_s_1_12_anchors_equal_osport_s():
    old, new = anchors("1.11"), anchors("1.12")
    decided, different = 0, []
    for name in sorted(old.keys() & new.keys()):
        try:
            ours = osport.addr("1.12", old[name])
        except osport.NotPorted:
            continue
        decided += 1
        if ours != new[name]:
            different.append((name, hex(old[name]), hex(new[name]), hex(ours)))
    assert different == []
    assert decided >= 100               # the control: the comparison covers real anchors


def test_digikit_s_free_ram_starts_above_our_dma_section():
    for v in ("1.11", "1.12"):
        region = {r["name"]: r for r in port(v)["region"]}["cf.expansion"]
        assert region["start"] >= versions.VERSIONS[v].dma[1], v


def test_elekloader_s_1_12_profile_states_our_facts():
    if not PROFILE.exists():
        pytest.skip(f"no elekloader profile {PROFILE}")
    text = PROFILE.read_text(encoding="utf-8").lower()
    v = versions.V112
    lo, hi = v.dma
    for fact in (v.syx_sha256, v.main_sha256, f"{v.main_length:,}", f"{v.stock_end:#x}",
                 f"0x402fd000-{v.clear_end:#x}", f"{lo:#x}-{hi:#x}", f"{lo + 0x08000000:#x}-{hi + 0x08000000:#x}"):
        assert fact.lower() in text, fact
