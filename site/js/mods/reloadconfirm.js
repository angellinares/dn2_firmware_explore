/**
 * Reload confirm: an opt-in YES/NO prompt before FUNC + NO reloads the pattern.
 *
 * The browser half of `src/dnfw/mods/reloadconfirm.py`, which carries the evidence
 * and the hardware result. Same steps, same order: check every guard and every
 * edit's stock bytes, write the two hooks, then add the routines to the platform's
 * area as a CODE chunk at 0x467e0000. `scripts/js_reloadconfirm_check.mjs` fails if
 * the bytes differ from the Python's.
 */

import { CODE } from "./reloadconfirm-code.js";
import * as platform from "./platform.js";

export const ID = "reloadconfirm";
export const NAME = "Reload confirm";
export const SECTION = 3;
const BASE = 0x40000400;
const CODE_VA = CODE.code.va;
const BLOB = CODE.code.blob;

export class ModError extends Error {}

const hex = (s) => Uint8Array.from(s.match(/../g) ?? [], (b) => parseInt(b, 16));
const toHex = (a) => Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");

export function extents() {
  return [...CODE.edits.map((e) => ({ section: SECTION, start: e.va - BASE,
                                      length: e.new.length / 2, what: e.what })),
          ...platform.extents(16 + BLOB.length / 2)];
}

/** -> `{ content, notes }`, the new section 3. */
export function apply(firmware) {
  const section = firmware.container.find(SECTION);
  if (section === null) throw new ModError("image has no MAIN OS section");
  const unpacked = section.unpack();
  if (unpacked === null) throw new ModError("MAIN OS did not depack");
  const [original, others] = platform.split(unpacked);
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

  const edited = original.slice();
  for (const e of CODE.edits) edited.set(hex(e.new), e.va - BASE);
  const blob = hex(BLOB);
  const content = platform.join(edited, [...others, [platform.CODE, platform.codeChunk(CODE_VA, blob)]]);

  return {
    content,
    notes: ["SETTINGS > PERSONALIZE > RELOAD CONFIRM: off by default",
            "on: FUNC + NO asks before reloading the pattern",
            `${CODE.edits.length} hooks in section 3, and a ${blob.length.toLocaleString("en-US")} B CODE `
              + `chunk at 0x${CODE_VA.toString(16).padStart(8, "0")} in the platform's area`],
  };
}
