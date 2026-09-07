# Architecture principles

**Binding on every change.** A change that cannot follow one of these says so
and explains why; silently breaking one is not an option.

The first eleven are inherited wholesale from `DNX/docs/PRINCIPLES.md` and are
not repeated here — read that file, it is the same author's hard-won list and
it governs this repository too. The short form:

1. One job per module — nameable in a sentence with no "and" in it.
2. Anything a second caller needs moves up.
3. The layering goes one way.
4. Reuse means the shared thing, not a copy of it.
5. Anything reused says what it assumes.
6. A default that gets smarter needs a caller sweep.
7. Verify through the surface the user touches.
8. Never invent data.
9. Report volume is a design decision.
10. Vocabulary follows the hardware.
11. Documentation is written for the people who come after.

What follows is what this repository adds, because firmware is not a file
format — it is the thing an instrument boots.

## 12. Nothing is flashed that the toolchain cannot verify end to end

Every integrity field present in the original must verify in the rebuild before
the file is written, let alone sent. `dnfw build` and `dnfw patch apply`
re-load and re-verify their own output and refuse to write if anything fails.
That check is not a convenience and is not to be bypassed for a quick test.

A field that is absent is reported as absent, never as passing —
`firmware.verify` says "unsigned image, no digest to check" rather than a tick.

## 13. A recovery path is proven before it is needed

Before any modified image goes near the instrument, the Early Start-up Menu
route is exercised by reflashing **stock** firmware through it. A recovery path
that has never been used is a belief, not a path. See `docs/flashing.md`.

## 14. How a section is stored is read from the image, never assumed

On both Digitones some sections are aPLib streams and some are stored raw, and
which is which differs between the two devices. The only reliable test is
whether the bytes depack. `firmware.build.replacement` therefore takes that
decision from the original section rather than from an argument.

Compressing a raw section — or storing a compressed one raw — produces a file
that passes every checksum and bricks the instrument. There is no feedback from
the device between those two facts.

## 15. Ported code says where it came from and where it diverges

Three MIT repositories did most of this work already. Every module that ports
from one names it in the header, and — more importantly — names the places it
does something *different*, with the reason.

`codec/aplibpack.py` is the example to follow: it says the parse strategy is
not the C's, why Python cannot run the C's, and what that costs measured
against the sections Elektron ship.

## 16. C that relies on unsigned wraparound is a porting hazard

Two bugs during the port, both the same shape: the C computes something in a
`uint32_t` and depends on it wrapping.

- The end-of-stream token is a gamma of `0x1000002` and a `0xFF` byte, which
  only equals the offset bias after the high bits fall off a 32-bit register.
- A raw offset below the bias becomes a huge unsigned value in C and is caught
  by a range test. In Python it stays negative, passes the test, and indexes
  off the end of the output.

Both are regression tests in `test/test_aplib.py`. When porting the next piece
of C, look for arithmetic whose correctness depends on the register width.

## 17. Everything is reachable from the CLI

One entry point, `dnfw`, with one file per subcommand under `cli/`. A
subcommand does argument handling and I/O; the work lives in the library module
it calls. **A capability with no subcommand is not finished** — it cannot be
used by hand, which means it cannot be checked by hand.

## Applying these to a change

- Can each file you touched be described without an "and"?
- Does anything in `src/dnfw/` outside `cli/` touch the filesystem or argv?
- Did you port from a reference without saying so, or diverge without saying why?
- Did you add a capability without a subcommand?
- Did you run `dnfw` on a real image, not only the tests?
- Would the change let something unverified be written to disk?
