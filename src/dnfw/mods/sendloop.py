"""The DSP frame send's copy loop, with 4 instructions for each word in place of 7.

## What it changes for the user

Nothing that a user sees or hears. The instrument sends the same frame to the DSP. The ColdFire
spends less time on it: about 4 points of a frame less in the audio interrupt, stopped and playing
(measured on the unit, 2026-11-15). So there is more room before a busy pattern makes the audio
interrupt run late.

## How

The audio interrupt sends one frame to the DSP 1,500 times a second. The send routine
(`0x400cf7be` on 1.11) first builds a transfer buffer: each 16-bit frame word goes beside a
fixed command word, as one 4-byte entry. Stock writes the two halves of each entry apart and
counts the words. That costs 7 instructions for each of the 1,344 words of a frame.

The mod is one in-place rewrite of that 24-byte loop, with our own loop of the same size
(`NEW` below, and `docs/sendloop.md` with a figure). The command word goes into the high half of
`%d2` once. Each frame word is read into the low half, and one 32-bit write stores the entry. An
end address replaces the counter. The buffer holds the same bytes, and the loop costs 4
instructions for each word.

| register | after the loop |
|---|---|
| `%a0`, `%a1`, `%a3`, `%d0` | the same values as stock |
| `%a2`, `%d2` | other values. The routine does not read them again and restores both on return |

The routine's callers all pass 0xa80 bytes (the audio interrupt, one more stock caller, and
Waverider's table loader). A count of 0 writes nothing, as in stock.

## Evidence

- The emulator (digikit coupled-run, 2026-11-14): 4,030 instructions less in every frame in 7
  scenarios, and the same buffer contents as stock.
- The real DSP in the emulator: the rendered samples are equal to stock's, sample for sample.
- The unit (2026-11-15), against a control build, on the factory pattern DARKWAX24 B05 at 155 BPM:
  the audio interrupt 46.1 % of a frame against 50.0 %, the worst frame 91.7 % against 95.6 %, no
  interrupt over a frame on either. Recordings of both builds agree in level (0.02 dB), in
  spectrum (0.36 dB) and in timing (0 ms drift).
"""

from . import Extent, ModError, Result, specs

ID = "sendloop"
NAME = "Send loop"
SUMMARY = "A shorter copy loop in the DSP frame send: the same frame, less processor time."
DEVICE = 0x15                      # Digitone II
SECTION = 3                        # MAIN OS
BASE = 0x40000400
SITE = 0x400CF912
# 1.12: the map's +0x164 (the routine 0x400cf7be -> 0x400cf922). The 24 stock bytes are there
# once, and the routine differs from 1.11's only in three relocated addresses.
SITES = {"1.11": SITE, "1.12": 0x400CFA76}
WORDS_A_FRAME = 0xA80 // 2

# Stock's loop, as the bytes this mod expects at the site and replaces (a guard, as every mod's
# edits carry their stock bytes).
STOCK = bytes.fromhex("42822248e280b0826f0e30bc800152825888315bfffe60ee")
# Our loop, the same 24 bytes long. %a3 the frame words, %a0 the buffer, %d0 the byte count.
NEW = bytes.fromhex(
    "2248"              # movea.l %a0,%a1             keep the buffer's start for the code after the loop
    "e280"              # asr.l   #1,%d0              the byte count -> the word count
    "243c80010000"      # move.l  #0x80010000,%d2     the command word, once
    "45f30a00"          # lea     (%a3,%d0.l*2),%a2   the end of the frame words
    "6004"              # bra.s   2f                  test first: a count of 0 writes nothing
    "341b"              # 1: move.w (%a3)+,%d2        the frame word, into the low half
    "20c2"              # move.l  %d2,(%a0)+          the whole entry
    "b5cb"              # 2: cmpa.l %a3,%a2           words left?
    "62f8"              # bhi.s   1b                  yes: the next word
)
assert len(NEW) == len(STOCK) == 24


def _site(os: str) -> int:
    if os not in SITES:
        raise ModError(f"{ID} is not yet ported to Digitone II {os}")
    return SITES[os]


def extents(firmware=None, os: str | None = None) -> list[Extent]:
    site = _site(os or specs.of_firmware(firmware))
    return [Extent(SECTION, site - BASE, len(NEW), "frame send: the copy loop")]


def apply(firmware) -> Result:
    section = firmware.container.find(SECTION)
    if section is None:
        raise ModError("image has no MAIN OS section")
    original = section.unpack()
    os = specs.of_main_os(original)
    site = _site(os)
    at = site - BASE
    # Longer is fine: data appended after the stock end moves nothing here.
    if len(original) < at + len(STOCK) or original[at:at + len(STOCK)] != STOCK:
        raise ModError(f"0x{site:08x} is not stock; this mod is for Digitone II {os}, "
                       "or another mod already wrote there")
    content = bytearray(original)
    content[at:at + len(NEW)] = NEW
    return Result(payloads={SECTION: bytes(content)}, extents=extents(os=os),
                  notes=["the DSP frame send builds its buffer with 4 instructions for each "
                         "word in place of 7",
                         "1 in-place edit of 24 B in section 3, nothing appended"])
