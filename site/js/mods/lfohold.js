/**
 * LFO trig modes ONE and HALF hold the value they stopped at.
 *
 * The browser half of `src/dnfw/mods/lfohold.py`, which carries the evidence.
 * The short version: stock 1.11's LFO evaluator stops a ONE at the end of its
 * cycle and a HALF at the middle by overwriting the LFO's output with a fixed
 * value per waveform, the centre for nearly all of them, instead of holding
 * where it got to. So a square in ONE "turns off" after a cycle and in HALF
 * "jumps back to the middle". The two stores become NOPs, and the LFO keeps the
 * last value it computed. **Confirmed on hardware on 2026-10-08** against
 * stock 1.11 on the same patch.
 *
 * Both sites are asserted with the instruction before each store, so an image
 * whose evaluator is not the one measured is refused, not patched.
 */

export const ID = "lfohold";
export const NAME = "LFO hold";
export const SECTION = 3;

const BASE = 0x40000400;
const hex = (s) => Uint8Array.from(s.match(/../g).map((b) => parseInt(b, 16)));

/** [address, stock bytes, new bytes, what] -- the same table as the Python. */
export const SITES = [
  [0x401378e8, hex("41f03c00" + "25500054"), hex("41f03c00" + "4e714e71"),
   "HALF: the stop-table store NOP'd"],
  [0x4013791c, hex("20713c00" + "25480054"), hex("20713c00" + "4e714e71"),
   "ONE: the stop-table store NOP'd"],
];

export class ModError extends Error {}

const same = (d, at, want) => want.every((v, i) => d[at + i] === v);

function mainOs(firmware) {
  const section = firmware.container.find(SECTION);
  if (section === null) throw new ModError("image has no MAIN OS section");
  return section.unpack() ?? section.rawPayload;
}

/** Which bytes this mod writes: the 4-byte store at each site. */
export function extents(firmware) {
  mainOs(firmware);
  return SITES.map(([at, , , what]) => ({
    section: SECTION, start: at + 4 - BASE, length: 4, what,
  }));
}

/** -> { content, notes } -- the new section 3 bytes, or throw. */
export function apply(firmware) {
  const content = mainOs(firmware).slice();
  for (const [at, stock, next] of SITES) {
    const off = at - BASE;
    if (!same(content, off, stock)) {
      throw new ModError(
        `0x${at.toString(16).padStart(8, "0")} is not stock; this mod is for `
        + "Digitone II 1.11, or another mod already wrote there");
    }
    content.set(next, off);
  }
  return {
    content,
    notes: ["LFO trig modes ONE and HALF hold the value they stopped at",
            "2 in-place edits of 4 B in section 3, nothing appended"],
  };
}
