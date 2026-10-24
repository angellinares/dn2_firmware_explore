"""Replace the Digitone II's FM drum transient bank with your own samples.

## The bank, and the table that plays it

The samples are in the **SHARC image** (container section 7, an ADI boot stream).
They were found by a detector calibrated against Elektron's own `TRANSIENT 01-08.wav`
from the Syntakt OS 1.41 Twinshot pack (`docs/pcm-hunt.md` §14): 16-bit mono,
little-endian, 48 kHz, in DDR `0x8045b0c8`..`0x804abe88`.

**The DSP plays them through a table of 32 entries** (DDR `0x28266d08`, 256 bytes:
the start address and the length in samples, little-endian, one entry per TRAN step).
TRAN 4 x k plays entry k, and the values between two steps blend the two entries
(`docs/tran-mapping.md`). The factory entries are not equal: 50, 100 or 150 ms, and
the first 13 do not start on a 100 ms grid. Found on hardware on 2026-10-24: a bank of
identical two-tone beeps at every 4,800 samples played half beeps and double beeps
below TRAN 52, and one clean beep from TRAN 52 up.

Slot k of this mod is table entry k, so it plays at TRAN 4 x k. Two layouts (owner,
2026-10-24), chosen per build:

- **Factory sizes** (the default): the table stays as it is, and each slot keeps its
  factory length (STOCK_LENGTHS: 50, 100 or 150 ms). A new sample is fitted to its slot.
  Slot 5's factory entry spans the stream's 36-byte fill block: the loader zeroes
  those 18 samples, 94.1 ms into the slot, as on stock.
- **Equal slots** (`equal=True`): the mod rewrites the table. It lays the 32 entries out
  at EQUAL_SAMPLES (5,164 samples, 107.6 ms) each over the same memory, five before the
  fill block and 27 after it, each start on an 8-byte boundary as the factory starts
  are. Factory transients that are not replaced are fitted too: the 8 of 150 ms are
  cut, and the other 24 padded (the 3 of 50 ms, and the 21 of 100 ms by 7.6 ms each).

In both, a transient you do not replace keeps its current sound, fitted to its slot
(`fit`: cut with a 2 ms fade, or padded with silence). With factory sizes, a stock
transient comes back byte for byte.

**What stays conditional:** none of this is documented by Elektron, so another OS
release could move the bank or the table. Both are resolved through the boot stream
every time this runs, and an image whose table is neither stock's nor this mod's own
layout is refused rather than written to.

## How a replacement is prepared

Each input becomes exactly its slot's length of 16-bit mono at 48 kHz (`lengths`):

- other sample rates are linearly resampled;
- stereo is mixed to mono;
- longer inputs are **truncated** and shorter ones **zero-padded**, because a slot's
  length is fixed by the layout.

Truncation is reported rather than done silently.
"""

import pathlib
import struct
import wave

from . import Extent, ModError, Result
from ..image import bootstream

ID = "transients"
NAME = "FM drum transients"
SUMMARY = "Replace the factory FM drum transient bank with your own samples."
DEVICE = 0x15                      # Digitone II, dump-protocol product id
SECTION = 7                        # the SHARC image

# Measured -- see the module docstring. Load addresses, not file offsets.
# DN2 1.11's bank. The code takes the bank's start from the table (`bank_start`): 1.10E has
# the same table with its samples 32 bytes lower, at 0x8045b0a8.
SAMPLES_START = 0x8045B0C8         # the first factory entry's first sample
SAMPLES_END = 0x804ABE88           # one past the last factory entry's last sample
TABLE_ADDR = 0x28266D08            # 32 x (start address, length in samples), LE
COUNT = 32
TABLE_BYTES = COUNT * 8
# The factory entries' lengths in samples, end to end from SAMPLES_START (read from stock
# 1.11's table; each start is the previous start plus the previous length).
STOCK_LENGTHS = (2400, 7200, 2400, 2400, 7200, 4800, 7200, 4800, 7200, 7200, 7200, 7200, 7200) + (4800,) * 19
RATE = 48000
BYTES_PER_SAMPLE = 2
ALIGN = 8                          # every factory start is on an 8-byte boundary
EQUAL_SAMPLES = 5164               # the longest equal length that fits; layout() checks it
EQUAL_BYTES = EQUAL_SAMPLES * BYTES_PER_SAMPLE
BANK_BYTES = 2 * sum(STOCK_LENGTHS)    # the factory entries, end to end: 331,200 bytes


def lengths(equal: bool = False) -> list[int]:
    """Each slot's length in samples: the factory sizes, or EQUAL_SAMPLES for all."""
    return [EQUAL_SAMPLES] * COUNT if equal else list(STOCK_LENGTHS)


def _section(firmware) -> bytes:
    section = firmware.container.find(SECTION)
    if section is None:
        raise ModError(f"image has no section {SECTION}")
    return section.unpack() or section.raw_payload


def layout(stream: bytes) -> list[int]:
    """-> the 32 start addresses of the equal layout over STREAM's bank memory.

    The bank memory is two data blocks with a fill block between them (the loader
    zeroes 36 bytes, and the file has no bytes for them), so the entries are packed
    into the data pieces only. EQUAL_SAMPLES is the longest length (a multiple of
    ALIGN / 2 samples) that fits all 32; a stream where it does not fit is refused.
    """
    start = bank_start(stream)
    runs, at = [], start
    for offset, n in bootstream.spans(stream, start, BANK_BYTES):
        if offset is not None:
            runs.append((at, at + n))
        at += n
    starts = []
    for lo, hi in runs:
        a = -(-lo // ALIGN) * ALIGN
        while len(starts) < COUNT and a + EQUAL_BYTES <= hi:
            starts.append(a)
            a += EQUAL_BYTES
    if len(starts) < COUNT:
        raise ModError(f"the bank memory holds {len(starts)} entries of {EQUAL_SAMPLES} samples, not {COUNT}")
    return starts


def table(stream: bytes) -> list[tuple[int, int]]:
    """-> STREAM's transient table: (start address, length in samples) per entry."""
    raw = bootstream.read_span(stream, TABLE_ADDR, TABLE_BYTES)
    return [struct.unpack_from("<II", raw, 8 * k) for k in range(COUNT)]


def _pack_table(starts: list[int], sizes: list[int]) -> bytes:
    return b"".join(struct.pack("<II", a, n) for a, n in zip(starts, sizes))


def bank_start(stream: bytes) -> int:
    """The bank's first sample: entry 0's start, in the factory table and in the equal layout.
    `_check_table` confirms that the rest of the table fits it."""
    return struct.unpack("<I", bootstream.read_span(stream, TABLE_ADDR, 4))[0]


def _stock_starts(start: int) -> list[int]:
    starts, at = [], start
    for n in STOCK_LENGTHS:
        starts.append(at)
        at += 2 * n
    return starts


def stock_table(start: int = SAMPLES_START) -> bytes:
    """The factory table for a bank at START (1.11's by default), from STOCK_LENGTHS."""
    return _pack_table(_stock_starts(start), STOCK_LENGTHS)


def equal_table(stream: bytes) -> bytes:
    """The table of the equal layout over STREAM's bank memory."""
    return _pack_table(layout(stream), lengths(equal=True))


def _check_table(stream: bytes) -> list[tuple[int, int]]:
    """STREAM's table if it is stock's or this mod's own layout; refuses any other."""
    raw = bootstream.read_span(stream, TABLE_ADDR, TABLE_BYTES)
    start = bank_start(stream)
    if start % ALIGN or (raw != stock_table(start) and raw != equal_table(stream)):
        raise ModError("the transient table is neither the factory one nor this mod's equal layout")
    return table(stream)


def _spans(stream: bytes) -> list[tuple[int, int]]:
    """The file pieces this mod writes: the bank memory's data pieces, then the table."""
    pieces = bootstream.spans(stream, bank_start(stream), BANK_BYTES)
    pieces += bootstream.spans(stream, TABLE_ADDR, TABLE_BYTES)
    return [(at, n) for at, n in pieces if at is not None]


def extents(firmware) -> list[Extent]:
    """Which bytes this mod writes -- **several ranges, not one.**

    The bank is contiguous in the DSP's memory and scattered in the file, and the
    table is in another block, so a single extent would under-declare them and the
    compatibility check would miss a real overlap. The fill piece contributes no
    extent because there are no file bytes to claim.
    """
    return [Extent(SECTION, at, n, f"transient bank and table, {n:,} bytes")
            for at, n in _spans(_section(firmware))]


def fit(pcm: bytes, length: int) -> bytes:
    """Raw 16-bit LE PCM of any length -> exactly LENGTH samples: cut with a 2 ms fade, or padded."""
    if len(pcm) <= 2 * length:
        return pcm + bytes(2 * length - len(pcm))
    v = list(struct.unpack(f"<{length}h", pcm[:2 * length]))
    fade = RATE // 500
    for i in range(fade):
        v[-1 - i] = int(v[-1 - i] * i / fade)
    return struct.pack(f"<{length}h", *v)


def _write(data: bytearray, address: int, pcm: bytes) -> list[tuple[int, int]]:
    """Write PCM at ADDRESS across the blocks that hold it. A fill piece has no file bytes,
    so its part is skipped (the loader zeroes it). -> (offset, bytes) of each skipped part
    that was not all zeros."""
    lost, cursor = [], 0
    for at, n in bootstream.spans(bytes(data), address, len(pcm)):
        if at is None:
            if any(pcm[cursor:cursor + n]):
                lost.append((cursor, n))
        else:
            data[at:at + n] = pcm[cursor:cursor + n]
        cursor += n
    return lost


def read_wav(path: pathlib.Path, length: int | None = None) -> list[int]:
    """-> 16-bit mono samples at RATE: LENGTH of them (cut or padded), or the whole file.

    The whole file (LENGTH None) is what `prepare()` needs so it can
    choose which part to keep. Truncating first would throw away the part the
    user may be asking for.
    """
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            raise ModError(f"{path.name}: {w.getsampwidth() * 8}-bit; "
                           f"only 16-bit WAV is supported")
        ch, rate, n = w.getnchannels(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    v = list(struct.unpack_from(f"<{n * ch}h", raw, 0))
    if ch > 1:
        v = [sum(v[i:i + ch]) // ch for i in range(0, len(v), ch)]
    if rate != RATE:
        # Linear resample. Good enough for a short percussive hit, and far
        # better than refusing the file; anything fancier belongs in the
        # user's editor, where they can hear it.
        out, step = [], rate / RATE
        for i in range(int(len(v) / step)):
            x = i * step
            k = int(x)
            f = x - k
            a = v[k] if k < len(v) else 0
            b = v[k + 1] if k + 1 < len(v) else a
            out.append(int(a + (b - a) * f))
        v = out
    v = [max(-32768, min(32767, x)) for x in v]
    if length is None:
        return v
    return (v + [0] * length)[:length]


def prepare(path: pathlib.Path, length: int, lead_ms: float = 3.0,
            start_ms: float | None = None) -> list[int]:
    """Condition any sample into one slot: mono, 48 kHz, LENGTH samples of the right part.

    A slot has a fixed length and a user's file is whatever it is, so something has
    to choose *which* part.

    **`start_ms` — you choose.** The window starts exactly there. Use it when the
    part you want is not the first attack: the second hit of a flam, a tail you
    want on its own, a sample whose useful moment is 300 ms in.

    **Otherwise the onset is found** — the first point reaching an eighth of the
    peak — and the window starts `lead_ms` before it. Files routinely carry a few
    milliseconds of silence, and starting at sample 0 would spend the slot on it.

    `lead_ms` is a per-sample control, not a constant, because the right value
    depends on the sound. A sharp click wants almost none; a soft or swelling
    attack wants more, or the detector fires partway up the rise and the front of
    the sound is cut off. Guessing one number for a whole bank is exactly the
    kind of fixed assumption this project keeps having to retract, so it is
    exposed instead.

    A 2 ms fade at the end keeps the hard cut from adding a click of its own,
    which would be a transient this tool invented.

    This is **fitting**, not separation. Pulling the percussive layer out of a
    pitched sample is real signal processing, and `mikkovihonen/transientsplit`
    (MIT) already does it in the browser — run a sample through that first if
    you want the transient *component*, then through this to fit it to the slot.
    """
    v = read_wav(path)
    if not v:
        return [0] * length

    if start_ms is not None:
        start = max(0, int(start_ms * RATE / 1000))
    else:
        peak = max((abs(x) for x in v), default=0)
        if peak == 0:
            return (v + [0] * length)[:length]
        threshold = peak // 8
        onset = next((i for i, x in enumerate(v) if abs(x) >= threshold), 0)
        start = max(0, onset - int(lead_ms * RATE / 1000))

    out = v[start:start + length]
    if len(out) < length:
        out = out + [0] * (length - len(out))
    fade = RATE // 500                      # 2 ms, far shorter than any decay
    for i in range(min(fade, len(out))):
        out[-1 - i] = int(out[-1 - i] * i / fade)
    return out


def read_options(directory: pathlib.Path) -> dict:
    """Per-sample conditioning options from `prepare.csv`, if present.

    One line per file, so a bank can be tuned sample by sample without renaming
    anything or passing thirty-two flags:

        # file, lead_ms, start_ms
        kick.wav,   6,
        snare.wav,   , 120

    A blank field means "not set". `start_ms` wins over `lead_ms` where both are
    given, because naming an exact start is a stronger statement than adjusting
    a guess. Unknown filenames are reported rather than ignored -- a typo that
    silently does nothing is worse than an error.
    """
    options: dict[str, dict] = {}
    for name in ("prepare.csv", "prepare.txt"):
        path = directory / name
        if not path.exists():
            continue
        import csv
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.reader(fh):
                if not row or row[0].strip().startswith("#"):
                    continue
                key = row[0].strip()
                if not key:
                    continue
                entry = {}
                if len(row) > 1 and row[1].strip():
                    entry["lead_ms"] = float(row[1])
                if len(row) > 2 and row[2].strip():
                    entry["start_ms"] = float(row[2])
                options[key] = entry
        break
    return options


def extract(firmware) -> list[bytes]:
    """-> the 32 transients as the table plays them, each its own length of raw 16-bit LE PCM.

    Read through `bootstream.read_span`, which gathers each one across the blocks that
    hold it. Reading the file linearly -- what this did until 2026-09-14 -- returned
    block headers and the fill gap as audio.
    """
    data = _section(firmware)
    return [bootstream.read_span(data, at, 2 * n) for at, n in _check_table(data)]


def apply(firmware, sources: list[pathlib.Path], condition: bool = False,
          lead_ms: float = 3.0, options: dict | None = None, equal: bool = False) -> Result:
    """Replace slots 0, 1, ... in order with `sources`, in the factory sizes or (`equal`) equal slots.

    Slot k plays at TRAN 4 x k, and its length is `lengths(equal)[k]`. A slot with no source
    keeps its current sound, fitted to its length (`fit`). `condition=True` runs each input
    through `prepare()`: onset alignment and an end fade.
    """
    if not sources:
        raise ModError("no input samples given")
    if len(sources) > COUNT:
        raise ModError(f"{len(sources)} samples given but the bank holds "
                       f"{COUNT}; remove {len(sources) - COUNT}")

    section = firmware.container.find(SECTION)
    if section is None:
        raise ModError(f"image has no section {SECTION}")
    data = bytearray(section.unpack() or section.raw_payload)
    sizes = lengths(equal)
    # Every current slot is read before anything is written: the new layout may overlap
    # the old slots' memory.
    current = extract(firmware)
    entries = [fit(pcm, n) for pcm, n in zip(current, sizes)]

    ms = lambda n: f"{1000 * n / RATE:.1f} ms"            # noqa: E731
    notes = [f"layout: equal slots, {ms(EQUAL_SAMPLES)} each" if equal else "layout: factory sizes"]
    for k, path in enumerate(sources):
        with wave.open(str(path), "rb") as w:
            n_in, rate_in = w.getnframes(), w.getframerate()
        opts = (options or {}).get(path.name, {})
        if condition:
            samples = prepare(path, sizes[k],
                              lead_ms=opts.get("lead_ms", lead_ms),
                              start_ms=opts.get("start_ms"))
        else:
            samples = read_wav(path, sizes[k])
        entries[k] = struct.pack(f"<{sizes[k]}h", *samples)
        note = f"{k:02d} (TRAN {4 * k}, {ms(sizes[k])}) <- {path.name}"
        if condition:
            if "start_ms" in opts:
                note += f" (start {opts['start_ms']:g} ms)"
            else:
                lead = opts.get("lead_ms", lead_ms)
                note += f" (onset-aligned, lead {lead:g} ms"
                note += ", from prepare.csv)" if "lead_ms" in opts else ")"
        if rate_in != RATE:
            note += f" (resampled {rate_in} -> {RATE})"
        if n_in * RATE // max(rate_in, 1) > sizes[k]:
            note += f" (TRUNCATED to {ms(sizes[k])})"
        notes.append(note)
    for k in range(len(sources), COUNT):
        was = len(current[k]) // 2
        if was != sizes[k]:
            how = "cut" if was > sizes[k] else "padded"
            notes.append(f"{k:02d} keeps its sound, {how} from {ms(was)} to {ms(sizes[k])}")

    starts = layout(bytes(data)) if equal else _stock_starts(bank_start(bytes(data)))
    for k, (at, pcm) in enumerate(zip(starts, entries)):
        for offset, n in _write(data, at, pcm):
            notes.append(f"{k:02d}: {n // 2} samples at {ms(offset // 2)} fall in a boot-stream "
                         "fill block and stay silent, as on stock")
    bootstream.write_span(data, TABLE_ADDR, _pack_table(starts, sizes))
    return Result(payloads={SECTION: bytes(data)},
                  extents=extents(firmware),
                  notes=notes)
