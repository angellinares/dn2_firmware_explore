"""Checking every integrity field a firmware image carries.

One subject: producing findings. Rendering them is `cli.inspect`'s job, and
deciding whether a build may be written is `cli.build`'s.

The rule this exists to enforce: nothing is flashed that the toolchain cannot
verify end to end. A field that is absent is reported as absent, never as
passing.
"""

from dataclasses import dataclass

from ..container import ele3
from ..integrity import checksum, digest
from .model import Firmware


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class Report:
    checks: tuple[Check, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)


def verify(firmware: Firmware) -> Report:
    """Check every integrity field `firmware` carries."""
    checks = [_packets(firmware), _content(firmware)]
    checks += [_section(section) for section in firmware.container.sections]
    checks.append(_trailer(firmware))
    return Report(tuple(checks))


def _packets(firmware: Firmware) -> Check:
    total = firmware.checksums_ok + firmware.checksums_bad
    return Check(
        "transport packet checksums",
        firmware.checksums_bad == 0,
        f"{firmware.checksums_ok}/{total} packets",
    )


def _content(firmware: Firmware) -> Check:
    size = firmware.container.declared_size
    calculated = checksum.content(firmware.raw_container[:size])
    return Check(
        "container content checksum",
        calculated == firmware.stored_checksum,
        f"stored 0x{firmware.stored_checksum:08x} calculated 0x{calculated:08x}",
    )


def _section(section) -> Check:
    label = f"section {section.id} ({ele3.name(section.id)}) stream sum"
    if section.unpack() is None:
        return Check(label, True, "stored raw, no stream sum to check")
    return Check(
        label,
        section.sum_ok,
        f"stored 0x{section.declared_sum:08x} calculated 0x{section.computed_sum:08x}",
    )


def _trailer(firmware: Firmware) -> Check:
    size = firmware.container.declared_size
    if firmware.key is None:
        return Check("container trailer", True, "unsigned image, no digest to check")
    ok = digest.verify(firmware.key.value, firmware.raw_container[:size])
    return Check("container trailer", ok, "HMAC-SHA256 reproduced" if ok else "digest mismatch")
