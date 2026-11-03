"""What each mod writes into stock 1.11, as one SHA-256, recorded beside the mod's version.

A mod that writes other bytes needs a new version in `history.HISTORY`, or a user gets a
changed build under an old number. `test/test_mods_history.py` compares each mod's bytes
with `fingerprints.json`. `dnfw mods changelog --fingerprint IMAGE` records the bytes of
each new version, and refuses new bytes under a version that is already recorded.

A mod that needs input gets a fixed one: bootscreen a one-pixel mark, transients one
silent sample. The fingerprint is of the mod's code, not of what a user gives it.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import struct
import tempfile

from . import history

RECORD = pathlib.Path(__file__).with_name("fingerprints.json")


def _silent_wav(path: pathlib.Path) -> pathlib.Path:
    frames = bytes(2 * 480)
    path.write_bytes(b"RIFF" + struct.pack("<I", 36 + len(frames)) + b"WAVEfmt "
                     + struct.pack("<IHHIIHH", 16, 1, 1, 48000, 96000, 2, 16)
                     + b"data" + struct.pack("<I", len(frames)) + frames)
    return path


def of(firmware, mod) -> str:
    """The SHA-256 of what MOD writes, applied alone to FIRMWARE."""
    with tempfile.TemporaryDirectory() as tmp:
        if mod.ID == "bootscreen":
            result = mod.apply(firmware, [mod.mark_from_pixels({(64, 32)})])
        elif mod.ID == "transients":
            result = mod.apply(firmware, [_silent_wav(pathlib.Path(tmp) / "silent.wav")])
        else:
            result = mod.apply(firmware)
    digest = hashlib.sha256()
    for section, payload in sorted(result.payloads.items()):
        digest.update(struct.pack(">II", section, len(payload)) + payload)
    return digest.hexdigest()


def recorded() -> dict[str, dict[str, str]]:
    return json.loads(RECORD.read_text(encoding="utf-8")) if RECORD.exists() else {}


def problems(firmware, registry) -> list[str]:
    """Each mod whose bytes or version differ from the record."""
    out, record = [], recorded()
    for mod_id, mod in sorted(registry.items()):
        have, now = record.get(mod_id), history.version(mod_id)
        if have is None or have["version"] != now:
            out.append(f"{mod_id} {now}: not recorded. Run `dnfw mods changelog --fingerprint STOCK_1.11`")
        elif have["sha256"] != of(firmware, mod):
            out.append(f"{mod_id}: writes other bytes than {now} did. Add a Release to "
                       "src/dnfw/mods/history.py, then run `dnfw mods changelog --fingerprint STOCK_1.11`")
    return out


def record(firmware, registry) -> list[str]:
    """Record each new version's bytes. Returns the mods refused: new bytes, same version."""
    refused, data = [], recorded()
    for mod_id, mod in sorted(registry.items()):
        entry = {"version": history.version(mod_id), "sha256": of(firmware, mod)}
        have = data.get(mod_id)
        if have and have["version"] == entry["version"] and have["sha256"] != entry["sha256"]:
            refused.append(f"{mod_id}: writes other bytes than {entry['version']} did. "
                           "Add a Release to src/dnfw/mods/history.py first")
        else:
            data[mod_id] = entry
    RECORD.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return refused
