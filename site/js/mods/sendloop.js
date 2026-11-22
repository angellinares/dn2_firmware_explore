/**
 * Send loop: the DSP frame send copies each frame with 4 instructions for each word in place of 7.
 *
 * The browser half of `src/dnfw/mods/sendloop.py`, which carries the method and the evidence
 * (docs/sendloop.md has the figure). One in-place edit of 24 bytes, nothing appended: stock's loop
 * must be at the site, and our loop of the same size replaces it. test_js_build_matches_cli.py
 * fails if the bytes differ from the Python's.
 */

export const ID = "sendloop";
export const NAME = "Send loop";
export const SECTION = 3;
const BASE = 0x40000400;
const SITE = 0x400cf912;                                  // OS 1.11

export class ModError extends Error {}

const hex = (s) => Uint8Array.from(s.match(/../g) ?? [], (b) => parseInt(b, 16));
// Stock's loop, as the bytes this mod expects at the site and replaces (a guard).
const STOCK = hex("42822248e280b0826f0e30bc800152825888315bfffe60ee");
// Our loop. %a3 the frame words, %a0 the buffer, %d0 the byte count.
const NEW = hex([
  "2248",              // movea.l %a0,%a1             keep the buffer's start for the code after the loop
  "e280",              // asr.l   #1,%d0              the byte count -> the word count
  "243c80010000",      // move.l  #0x80010000,%d2     the command word, once
  "45f30a00",          // lea     (%a3,%d0.l*2),%a2   the end of the frame words
  "6004",              // bra.s   2f                  test first: a count of 0 writes nothing
  "341b",              // 1: move.w (%a3)+,%d2        the frame word, into the low half
  "20c2",              // move.l  %d2,(%a0)+          the whole entry
  "b5cb",              // 2: cmpa.l %a3,%a2           words left?
  "62f8",              // bhi.s   1b                  yes: the next word
].join(""));

export function extents() {
  return [{ section: SECTION, start: SITE - BASE, length: NEW.length, what: "frame send: the copy loop" }];
}

/** -> `{ content, notes }`, the new section 3. */
export function apply(firmware) {
  const section = firmware.container.find(SECTION);
  if (section === null) throw new ModError("image has no MAIN OS section");
  const original = section.unpack();
  if (original === null) throw new ModError("MAIN OS did not depack");
  const at = SITE - BASE;
  // Longer is fine: data appended after the stock end moves nothing here.
  const there = original.subarray(at, at + STOCK.length);
  if (there.length !== STOCK.length || there.some((b, i) => b !== STOCK[i])) {
    throw new ModError(`0x${SITE.toString(16).padStart(8, "0")} is not stock; this mod is for Digitone II 1.11, `
      + "or another mod already wrote there");
  }
  const content = original.slice();
  content.set(NEW, at);
  return {
    content,
    notes: ["the DSP frame send builds its buffer with 4 instructions for each word in place of 7",
            "1 in-place edit of 24 B in section 3, nothing appended"],
  };
}
