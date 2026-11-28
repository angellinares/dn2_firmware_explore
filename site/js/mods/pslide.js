/**
 * Parameter slides: a trig's parameter locks glide over a length or to the next trig.
 *
 * The browser half of `src/dnfw/mods/pslide.py`, which carries the evidence. Same steps, same
 * order: check every guard and every edit's stock bytes, write the twelve hooks and the clear
 * mask's operand, then add the routines to the platform's area as a CODE chunk at 0x46c00000,
 * with the slides' state after it, and subscribe the frame routine to the hook bus's ev_frame.
 * `test/test_js_build_matches_cli.py` fails if the bytes differ from the Python's.
 */

import { CODE } from "./pslide-code.js";
import * as platform from "./platform.js";

export const ID = "pslide";
export const NAME = "Parameter slides";
export const SECTION = 3;
const BASE = 0x40000400;
const CODE_VA = CODE.code.va;
const BLOB = CODE.code.blob;
const pad4 = (n) => n + (-n & 3);

export class ModError extends Error {}

const hex = (s) => Uint8Array.from(s.match(/../g) ?? [], (b) => parseInt(b, 16));
const toHex = (a) => Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");

/** The platform's area with this mod alone (pslide.py's `area`): the bus's code ends with ev_frame's. */
function area() {
  return 12 + 3 * 12 + 16 + pad4(BLOB.length / 2) + 12 + 16 + pad4(platform.busCodeLength());
}

export function extents() {
  return [...CODE.edits.map((e) => ({ section: SECTION, start: e.va - BASE,
                                      length: e.new.length / 2, what: e.what })),
          ...platform.extents(area())];
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
  const content = platform.join(edited, [...others, [platform.CODE, platform.codeChunk(CODE_VA, blob, CODE.code.bss)],
                                         platform.subscribe("FRAM", CODE.labels.slide_frame)]);
  return {
    content,
    notes: ["TRIG PAGE 2: SLD under RTRG. Hold trigs in GRID RECORDING and turn knob E",
            "a trig with a length glides to its locks over it, a NEXT trig glides to the next trig's",
            `${CODE.edits.length} edits in section 3, a ${blob.length.toLocaleString("en-US")} B CODE chunk at `
              + `0x${CODE_VA.toString(16).padStart(8, "0")} with ${CODE.code.bss.toLocaleString("en-US")} B of `
              + "state, and an ev_frame handler"],
  };
}
