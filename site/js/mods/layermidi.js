/**
 * Track layering onto MIDI tracks.
 *
 * The browser half of `src/dnfw/mods/layermidi.py`, which carries the evidence
 * and the hardware result. Same steps, same order: check every guard and every
 * edit's stock bytes, write the edits. `scripts/js_layermidi_check.mjs` fails
 * if the bytes differ from the Python's.
 */

import { CODE } from "./layermidi-code.js";

export const ID = "layermidi";
export const NAME = "Layering onto MIDI tracks";
export const SECTION = 3;
const BASE = 0x40000400;

export class ModError extends Error {}

const hex = (s) => Uint8Array.from(s.match(/../g) ?? [], (b) => parseInt(b, 16));
const toHex = (a) => Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");

export function extents() {
  return CODE.edits.map((e) => ({ section: SECTION, start: e.va - BASE,
                                  length: e.new.length / 2, what: e.what }));
}

/** -> `{ content, notes }`, the new section 3. */
export function apply(firmware) {
  const section = firmware.container.find(SECTION);
  if (section === null) throw new ModError("image has no MAIN OS section");
  const original = section.unpack();
  if (original === null) throw new ModError("MAIN OS did not depack");
  // Longer is fine: data appended after the stock end moves no address used here.
  if (original.length < CODE.stock_length) {
    throw new ModError(`MAIN OS is ${original.length.toLocaleString()} B, shorter than `
      + `${CODE.stock_length.toLocaleString()}: not Digitone II 1.11`);
  }
  const at = (va, n) => toHex(original.subarray(va - BASE, va - BASE + n));
  for (const g of CODE.guards) {
    if (at(g.va, g.bytes.length / 2) !== g.bytes) {
      throw new ModError(`0x${g.va.toString(16)} is not stock; this mod is for unmodified Digitone II 1.11`);
    }
  }
  for (const e of CODE.edits) {
    if (at(e.va, e.stock.length / 2) !== e.stock) {
      throw new ModError(`0x${e.va.toString(16)} is not stock; this mod is for unmodified `
        + "Digitone II 1.11, or another mod already wrote there");
    }
  }

  const content = original.slice();
  for (const e of CODE.edits) content.set(hex(e.new), e.va - BASE);

  return {
    content,
    notes: ["TRACK WILL TRIGGER onto a MIDI track plays it over MIDI",
            "note-on as the layered note plays, note-off as it is released",
            `${CODE.edits.length} edits in section 3, nothing appended`],
  };
}
