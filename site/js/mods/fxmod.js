/**
 * LFO modulation of the FX: Chorus, Delay and Reverb in the `DEST` list.
 *
 * The browser half of `src/dnfw/mods/fxmod.py`, which carries the evidence and
 * the hardware result. Same steps, same order: check every guard and every
 * edit's stock bytes, then write the edits. `scripts/js_fxmod_check.mjs` fails
 * if the bytes differ from the Python's — and the Python's output is
 * byte-identical to `fxbrowser3_DN2_1.11.syx`, the image that was gated, so
 * what this produces is the image that was measured rather than a re-derivation
 * of it.
 *
 * Nothing here is discovered at apply time. Every address is fixed for
 * Digitone II 1.11 and every one of them is guarded: 26 sites the mod reads and
 * reasons from, plus each edit's own stock bytes. An image that differs
 * anywhere is refused rather than written somewhere plausible.
 *
 * One more refusal, for order: ten of the edits open records in the parameter
 * table, and `lfo4` moves that table into the appended area. Applied after
 * lfo4, those edits would find their stock bytes and land on a copy nothing
 * reads, so an image whose table accessors no longer reach the stock table is
 * refused, with the order that works (`tableMoved`, the port of
 * `dnfw.patch.paramtable.base_sites`).
 *
 * The slot lookup at 0x400dc02a is the platform's hook bus's `ev_param_slot`:
 * this mod subscribes its handler in the cave, so the image gains the
 * platform's loader and a small area, and Waverider answers its own slots there
 * too. A guard on instructions another mod's hook moved is read where they run.
 */

import { CODE } from "./fxmod-code.js";
import * as platform from "./platform.js";
import { tableMoved } from "./paramtable.js";

export const ID = "fxmod";
export const NAME = "LFO modulation of the FX";
export const SECTION = 3;
const BASE = 0x40000400;


export class ModError extends Error {}

const hex = (s) => Uint8Array.from(s.match(/../g) ?? [], (b) => parseInt(b, 16));
const toHex = (a) => Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");

/** -> [{ group, parameters }] — what the `DEST` list gains, for the page. */
export const DESTINATIONS = CODE.destinations;

export const COUNT = CODE.destinations.reduce((n, g) => n + g.parameters.length, 0);

// The appended area this mod adds alone: the header, two directory entries, the
// subscription, and the bus's dispatchers as a CODE chunk.
const AREA = 12 + 2 * 12 + 12 + 16 + platform.busCodeLength();

export function extents() {
  return [...CODE.edits.map((e) => ({ section: SECTION, start: e.va - BASE,
                                      length: e.new.length / 2, what: e.what })),
          ...platform.extents(AREA)];
}

/** Throw unless this image is one the mod applies to; -> [MAIN OS without the area, its chunks]. */
export function check(firmware) {
  const section = firmware.container.find(SECTION);
  if (section === null) throw new ModError("image has no MAIN OS section");
  const unpacked = section.unpack();
  if (unpacked === null) throw new ModError("MAIN OS did not depack");
  const [original, others] = platform.split(unpacked);
  const moved = tableMoved(original, ID, true);
  if (moved) throw new ModError(moved);
  const at = (va, n) => toHex(original.subarray(va - BASE, va - BASE + n));
  for (const g of CODE.guards) {
    if (toHex(platform.read(original, others, g.va, g.bytes.length / 2)) !== g.bytes) {
      throw new ModError(`0x${g.va.toString(16)} (${g.what}) is not stock; `
        + "this mod is for unmodified Digitone II 1.11");
    }
  }
  for (const e of CODE.edits) {
    if (at(e.va, e.stock.length / 2) !== e.stock) {
      throw new ModError(`0x${e.va.toString(16)} (${e.what}) is not stock; this mod is `
        + "for unmodified Digitone II 1.11, or another mod already wrote there");
    }
  }
  return [original, others];
}

/** -> `{ content, notes }`, the new section 3. */
export function apply(firmware) {
  const [original, others] = check(firmware);
  const edited = original.slice();
  for (const e of CODE.edits) edited.set(hex(e.new), e.va - BASE);
  const content = platform.join(edited, [...others, platform.subscribe(CODE.bus.event, CODE.bus.handler)]);
  return {
    content,
    notes: [`${COUNT} FX destinations appear in the LFO DEST list`,
            "Chorus, Delay and Reverb parameters follow the LFO",
            "the Chorus group reads CHR, not ERR",
            `${CODE.edits.length} edits in section 3, the slot lookup on the platform's hook bus`],
  };
}
