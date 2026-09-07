"""Finding the C++ names GCC left in the image.

Elektron ship these images with RTTI intact, so a 3 MB anonymous blob carries
several hundred class names and a set of mangled member names. Recovering them
is the cheapest large step in reverse-engineering this firmware: it turns
addresses into a program with named types.

Two things are found here, and they are different:

**Type names** are Itanium-ABI `<length><identifier>` type strings, as RTTI
stores them -- `11LfoPageView`, and nested forms naming a namespace such as
`N9Digisharc17soundStorage_v2_tE`. They are matched by structure, so the length
prefix must agree with the identifier that follows; that agreement is what
keeps ordinary text out of the results.

**Mangled names** are whole symbols beginning `_ZN`, which name members rather
than types.

Neither is demangled here. Demangling is a separate subject and a separate
module if it is ever wanted; what a disassembler needs is the address and the
string.
"""

import re
from dataclasses import dataclass

from .coldfire import LoadedImage

# A run of printable ASCII long enough to be worth testing.
_PRINTABLE = re.compile(rb"[\x20-\x7e]{4,}")
# <digits><identifier>, the Itanium ABI's length-prefixed name component.
_COMPONENT = re.compile(r"^(\d{1,3})([A-Za-z_][A-Za-z0-9_]*)$")
_NESTED = re.compile(r"^N(\d{1,3}[A-Za-z_][A-Za-z0-9_]*)+E$")


@dataclass(frozen=True)
class Symbol:
    address: int
    text: str
    kind: str  # "type" or "mangled"


def find(image: LoadedImage) -> list[Symbol]:
    """Every type name and mangled symbol in the image, in address order."""
    found: list[Symbol] = []
    for match in _PRINTABLE.finditer(image.content):
        text = match.group().decode("ascii")
        kind = classify(text)
        if kind:
            found.append(Symbol(image.address_of(match.start()), text, kind))
    return found


def classify(text: str) -> str | None:
    """"type", "mangled", or None if this is ordinary text."""
    if text.startswith("_ZN") or text.startswith("ZN"):
        return "mangled"
    if _is_type_name(text):
        return "type"
    return None


def _is_type_name(text: str) -> bool:
    """True for `11LfoPageView` and for nested `N9Digisharc5kit_tE` forms.

    The length prefix must equal the identifier's length. Without that check
    any digit followed by a word -- and firmware is full of those -- would be
    reported as a class.
    """
    component = _COMPONENT.match(text)
    if component:
        return int(component.group(1)) == len(component.group(2))
    if not _NESTED.match(text):
        return False
    body = text[1:-1]
    while body:
        part = _COMPONENT.match(body) or re.match(r"^(\d{1,3})([A-Za-z_][A-Za-z0-9_]*)", body)
        if not part:
            return False
        length = int(part.group(1))
        identifier = part.group(2)
        if len(identifier) < length:
            return False
        body = body[len(part.group(1)) + length :]
    return True
