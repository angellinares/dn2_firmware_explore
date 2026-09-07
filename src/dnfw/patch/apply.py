"""Applying patch records to a firmware image.

Every guard is checked before any byte is written, and the whole set is applied
to a copy -- so a run either produces a fully patched image or changes nothing.
A partially patched firmware is the one outcome worth engineering against.
"""

from dataclasses import dataclass

from ..firmware.model import Firmware
from ..image.coldfire import LoadedImage
from .spec import Patch, PatchError


@dataclass(frozen=True)
class Applied:
    patch: Patch
    section: int
    offset: int  # offset within the decompressed section


def applies_to(patch: Patch, firmware: Firmware) -> str | None:
    """None if `patch` targets this image, else why it does not."""
    if patch.device != firmware.envelope.device:
        return f"device 0x{patch.device:02x} != image 0x{firmware.envelope.device:02x}"
    if patch.build != firmware.container.build:
        return f"build {patch.build} != image {firmware.container.build}"
    if patch.version != firmware.container.version:
        return f"version {patch.version} != image {firmware.container.version}"
    if firmware.container.find(patch.section) is None:
        return f"image has no section id={patch.section}"
    return None


def locate(patch: Patch, image: LoadedImage) -> int:
    """Offset of `patch`'s target within the section, or raise.

    A `find` that matches more than once is an error, not a choice: the patch
    named something it believed unique, and it was wrong.
    """
    if patch.address is not None:
        if not image.contains(patch.address, len(patch.expect)):
            raise PatchError(
                f"{patch.id}: 0x{patch.address:08x} is outside section "
                f"0x{image.dest:08x}..0x{image.end:08x}"
            )
        offset = image.offset_of(patch.address)
    else:
        assert patch.find is not None
        count = image.content.count(patch.find)
        if count != 1:
            raise PatchError(f"{patch.id}: find matched {count} times, expected exactly 1")
        offset = image.content.index(patch.find)

    found = image.content[offset : offset + len(patch.expect)]
    if found != patch.expect:
        raise PatchError(
            f"{patch.id}: at {patch.target} expected {patch.expect.hex(' ')} "
            f"but found {found.hex(' ')}"
        )
    return offset


def apply(patches: list[Patch], firmware: Firmware) -> tuple[dict[int, bytes], list[Applied]]:
    """Apply `patches`, returning new content per section id and what was done.

    Raises PatchError -- before writing anything -- if any patch does not
    target this image or does not find what it expects.
    """
    for patch in patches:
        reason = applies_to(patch, firmware)
        if reason is not None:
            raise PatchError(f"{patch.id}: does not apply to this image: {reason}")

    images: dict[int, LoadedImage] = {}
    for patch in patches:
        if patch.section not in images:
            section = firmware.container.find(patch.section)
            content = section.unpack()
            if content is None:
                raise PatchError(
                    f"{patch.id}: section id={patch.section} is stored raw; "
                    "patching raw sections is not supported"
                )
            images[patch.section] = LoadedImage(dest=section.dest, content=content)

    placed = [(patch, locate(patch, images[patch.section])) for patch in patches]

    edited = {sid: bytearray(img.content) for sid, img in images.items()}
    applied = []
    for patch, offset in placed:
        edited[patch.section][offset : offset + len(patch.replace)] = patch.replace
        applied.append(Applied(patch=patch, section=patch.section, offset=offset))

    return {sid: bytes(buf) for sid, buf in edited.items()}, applied
