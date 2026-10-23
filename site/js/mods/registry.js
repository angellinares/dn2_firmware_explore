/**
 * The website's mods by id, each applied the way its page applies it: the build harness
 * (scripts/js_build_check.mjs) and the Check page's rebuild (safety.js) use this one list.
 *
 * A mod built from the user's own files (the boot screen, the transients) or one the site does
 * not publish is not here, so the Check page cannot rebuild it.
 */

import { build, load, replacement } from "../firmware.js";
import * as arpmodes from "./arpmodes.js";
import * as fxmod from "./fxmod.js";
import * as layermidi from "./layermidi.js";
import * as lfo4 from "./lfo4.js";
import * as lfolength from "./lfolength.js";
import * as lfowaves from "./lfowaves.js";
import * as midiarp from "./midiarp.js";
import * as moddest from "./moddest.js";
import * as reloadconfirm from "./reloadconfirm.js";
import * as waverider from "./waverider.js";

const MAIN_OS = (mod) => async (f) => new Map([[3, mod.apply(f).content]]);

/** id -> async (firmware) => Map(section id -> new content). */
export const RUN = {
  arpmodes: MAIN_OS(arpmodes), fxmod: MAIN_OS(fxmod), layermidi: MAIN_OS(layermidi), lfo4: MAIN_OS(lfo4),
  lfolength: MAIN_OS(lfolength), lfowaves: MAIN_OS(lfowaves), midiarp: MAIN_OS(midiarp), moddest: MAIN_OS(moddest),
  reloadconfirm: MAIN_OS(reloadconfirm),
  waverider: async (f) => { const r = await waverider.apply(f); return new Map([[3, r.main], [7, r.dsp]]); },
};

/** STOCK (a loaded firmware) with MODS applied in order, page after page -> the built .syx bytes. */
export async function applyInOrder(stock, mods) {
  let firmware = stock, bytes = null;
  for (const mod of mods) {
    const sections = await RUN[mod](firmware);
    bytes = await build(firmware, new Map([...sections].map(([id, c]) => [id, replacement(firmware, id, c, mod)])));
    firmware = await load(bytes);
  }
  return bytes;
}

/**
 * REBUILD for safety.js's `check`: STOCK with MODS applied in order -> Map(section id -> content),
 * or why the site cannot rebuild it.
 */
export async function rebuild(stock, mods) {
  const unknown = mods.filter((m) => !(m in RUN));
  if (unknown.length) return `the site does not publish ${unknown.join(", ")}, so it cannot rebuild this image`;
  const built = await load(await applyInOrder(stock, mods));
  return new Map(built.container.sections.map((s) => [s.id, s.unpack() ?? s.stored]));
}
