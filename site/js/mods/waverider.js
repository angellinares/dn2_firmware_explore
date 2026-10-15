/**
 * Waverider: a sixth synth machine, a wavetable oscillator, with tables on the +Drive.
 *
 * The browser half of `src/dnfw/mods/waverider.py`, which carries the evidence and the
 * hardware results. Two sections, from `waverider-code.js` (`scripts/gen_waverider_js.py`):
 *
 * - **MAIN OS (3):** check every guard and every edit's stock bytes, write the edits, then
 *   add two CODE chunks to the platform's area (the SYN pages, and the +Drive chunk), the
 *   group getter's displaced copy, the slot lookup's handler on the hook bus
 *   (`ev_param_slot`) and one machine on the bus's machine count.
 * - **The DSP boot stream (7):** only stock 1.11's section 7 is accepted (its sha256), so
 *   the result is fixed: our blocks spliced in before stock's final block, then a few runs
 *   of bytes written over stock code.
 *
 * `scripts/js_waverider_check.mjs` fails if either section differs from the Python's.
 */

import { CODE } from "./waverider-code.js";
import * as platform from "./platform.js";

export const ID = "waverider";
export const NAME = "Waverider";
export const MAIN_OS = 3;
export const DSP_STREAM = 7;
const BASE = 0x40000400;

export class ModError extends Error {}

// The group getter's hook replays its two stock instructions unchanged.
const DESTGROUP_SITE = 0x400dbce8, DESTGROUP_DISPLACED = 10;

/** What the page lists under "Writes": the edits, the two CODE chunks and the DSP stream. */
export const CODE_SUMMARY = `Section 3: ${CODE.edits.length} changes. The platform area: two blocks `
  + `of code. Section 7, the DSP boot stream: Waverider's code is added (`
  + `${CODE.dsp.stock_length.toLocaleString("en-US")} B before, `
  + `${(CODE.dsp.stock_length + CODE.dsp.insert.length / 2).toLocaleString("en-US")} B after).`;

const hex = (s) => Uint8Array.from(s.match(/../g) ?? [], (b) => parseInt(b, 16));
const toHex = (a) => Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");
const va8 = (va) => `0x${va.toString(16).padStart(8, "0")}`;

function mainOs(original) {
  if (original.length < CODE.stock_length) {
    throw new ModError(`MAIN OS is ${original.length.toLocaleString("en-US")} B, shorter than `
      + `${CODE.stock_length.toLocaleString("en-US")}: not Digitone II 1.11`);
  }
  const at = (va, n) => toHex(original.subarray(va - BASE, va - BASE + n));
  for (const g of CODE.guards) {
    if (at(g.va, g.bytes.length / 2) !== g.bytes) {
      throw new ModError(`${va8(g.va)} (${g.what}) is not stock; this mod is for unmodified Digitone II 1.11`);
    }
  }
  const content = original.slice();
  for (const e of CODE.edits) {
    if (at(e.va, e.stock.length / 2) !== e.stock) {
      throw new ModError(`${va8(e.va)} (${e.what}) is not stock; this mod is for `
        + "unmodified Digitone II 1.11, or another mod already wrote there");
    }
    content.set(hex(e.new), e.va - BASE);
  }
  return content;
}

async function section7(stock) {
  const d = CODE.dsp;
  const digest = toHex(new Uint8Array(await crypto.subtle.digest("SHA-256", stock)));
  if (digest !== d.stock_sha256) {
    throw new ModError(`the DSP boot stream: section 7 sha256 ${digest.slice(0, 12)}... is not `
      + `stock DN2 1.11's (${d.stock_sha256.slice(0, 12)}...)`);
  }
  const insert = hex(d.insert);
  const out = new Uint8Array(stock.length + insert.length);
  out.set(stock.subarray(0, d.final_offset), 0);
  out.set(insert, d.final_offset);
  out.set(stock.subarray(d.final_offset), d.final_offset + insert.length);
  for (const p of d.patches) out.set(hex(p.bytes), p.at);
  if (out.length > d.limit) {
    throw new ModError(`the DSP boot stream: section 7 is ${out.length.toLocaleString("en-US")} B: the `
      + `ColdFire loads at most ${d.limit.toLocaleString("en-US")} (a 1 MiB buffer), so the DSP would never boot`);
  }
  return out;
}

/** -> `{ main, dsp, notes }`: the new MAIN OS and section 7 contents. */
export async function apply(firmware) {
  const cf = firmware.container.find(MAIN_OS);
  const ds = firmware.container.find(DSP_STREAM);
  if (cf === null || ds === null) throw new ModError("image has no MAIN OS or no DSP boot stream");
  const unpacked = cf.unpack();
  const stream = ds.unpack();
  if (unpacked === null || stream === null) throw new ModError("MAIN OS or the DSP boot stream did not depack");
  const [original, others] = platform.split(unpacked);
  const dsp = await section7(stream);
  const main = platform.join(mainOs(original), [...others,
    [platform.CODE, platform.codeChunk(CODE.chunk.load, hex(CODE.chunk.code))],
    [platform.CODE, platform.codeChunk(CODE.drive.load, hex(CODE.drive.code))],
    platform.displace(DESTGROUP_SITE, DESTGROUP_DISPLACED, CODE.bus.group_displaced),
    platform.subscribe("PSLT", CODE.bus.slot_handler),
    platform.contribute("MACH", 1)]);
  return {
    main, dsp,
    notes: [`MACHINE SEL offers ${CODE.names[0].toUpperCase()} after SWARMER`,
            `${CODE.edits.length} edits in section 3, two CODE chunks in the platform's area; section 7 `
              + `${stream.length.toLocaleString("en-US")} -> ${dsp.length.toLocaleString("en-US")} B`],
  };
}
