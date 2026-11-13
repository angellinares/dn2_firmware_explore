/**
 * The Mod Composer: which mods it offers, the order it applies them in, which ones a choice
 * blocks, the build, and the `dnfw mods apply` arguments that build the same file.
 *
 * DOM-free. The page (app/compose-page.js) and the build harness (scripts/js_build_check.mjs)
 * both use it, so test/test_js_build_matches_cli.py builds each composer set the page's way and
 * runs the CLI with the arguments the page shows.
 *
 * A choice holds the options of the mods that take the user's own files:
 *
 *   transients: { entries: Map(slot -> Uint8Array of that slot's length), equal, folder }
 *   lfowaves:   { tables: [Uint8Array | null] x 3, files: [file name | null] x 3 }
 *   bootscreen: { lit(x, y), mode: "still" | "flash" | "ascii" | "spin", image }
 */

import { RUN, applyInOrder } from "./registry.js";
import { MAX_MODS } from "../modinfo.js";
import * as bootscreen from "./bootscreen.js";
import * as lfowaves from "./lfowaves.js";
import * as transients from "./transients.js";

/** The mods on offer, in the order the page lists them and applies them. */
export const GROUPS = [
  { name: "Machines", mods: ["waverider", "transients"] },
  { name: "LFOs and modulation", mods: ["lfo4", "fxmod", "lfowaves", "moddest", "lfolength"] },
  { name: "Arpeggiator and MIDI", mods: ["midiarp", "layermidi", "arpmodes", "arpscale"] },
  { name: "Workflow", mods: ["reloadconfirm", "directjump", "bootscreen"] },
];

/** As the CLI: a mod that copies the stock parameter table goes last (lfo4.py, APPLY_LAST). */
export const APPLY_LAST = ["lfo4"];

/** The mods that take the user's own files. */
export const TAKES_FILES = ["transients", "lfowaves", "bootscreen"];

const LISTED = GROUPS.flatMap((g) => g.mods);

/** IDS in the order they are applied: the page's order, with APPLY_LAST at the end. */
export function order(ids) {
  const set = new Set(ids);
  return [...LISTED.filter((id) => set.has(id) && !APPLY_LAST.includes(id)),
    ...APPLY_LAST.filter((id) => set.has(id))];
}

/** With Waverider, the /modinfo record lists every mod of the build, and it holds 26 (modinfo.js). */
export const MAX_WITH_RECORD = MAX_MODS;
const RECORD = "waverider";

/**
 * REFUSED: pairs that cannot combine, as [a, b]. -> Map(id -> { with: [chosen mods it does not
 * combine with], full: true when the build already holds the most mods it can }) for every listed
 * mod that is not chosen and cannot be added.
 */
export function blocked(chosen, refused) {
  const on = new Set(chosen);
  const out = new Map();
  for (const id of LISTED) {
    if (on.has(id)) continue;
    const hits = [...new Set(refused.filter(([a, b]) => a === id || b === id).map(([a, b]) => (a === id ? b : a)))]
      .filter((other) => on.has(other));
    const full = on.size >= MAX_WITH_RECORD && (on.has(RECORD) || id === RECORD);
    if (hits.length || full) out.set(id, { with: hits, full });
  }
  return out;
}

// The CLI's defaults for the two drawn animations (src/dnfw/cli/mods.py, the bootscreen group).
const ASCII = { ramp: " .:+#", glitchChars: "01/:=+<>[]{}#%*?_|-\\", resolve: 96, idleFrames: 16,
  seed: 26, glitch: 1, idle: 0.3 };
const SPIN = { resolve: 120, idleFrames: 48, stars: 90, smear: 1, spin: 3, zoom: 1, seed: 26 };

/** A boot screen choice -> the arguments of `bootscreen.apply`: [images, options]. */
export function bootArgs({ lit, mode }) {
  if (mode === "ascii") return [[], { ascii: bootscreen.asciiFrames(lit, ASCII) }];
  if (mode === "spin") return [[], { ascii: bootscreen.spinFrames(lit, SPIN) }];
  const mark = bootscreen.markFromPixels(lit);
  return [mode === "flash" ? [mark, bootscreen.invert(mark)] : [mark], {}];
}

/** CHOICE -> each mod's step for `applyInOrder`: the plain mods as their pages run them. */
export function runners(choice = {}) {
  const run = { ...RUN };
  if (choice.transients) {
    const { entries, equal = false } = choice.transients;
    run.transients = async (f) => new Map([[7, transients.apply(f, entries, { equal }).section.unpack()]]);
  }
  if (choice.lfowaves) {
    run.lfowaves = async (f) => new Map([[3, lfowaves.apply(f, choice.lfowaves.tables).content]]);
  }
  if (choice.bootscreen) {
    const [images, options] = bootArgs(choice.bootscreen);
    run.bootscreen = async (f) => new Map([[3, bootscreen.apply(f, images, options).content]]);
  }
  return run;
}

/** STOCK with IDS applied in `order`, with CHOICE for the mods that take files -> .syx bytes. */
export function build(stock, ids, choice = {}) {
  return applyInOrder(stock, order(ids), runners(choice));
}

/**
 * The arguments of `dnfw mods apply` that build the same set, one list per line of the command:
 * [[STOCK], ["--mod", id, ...its options], ..., ["-o", OUT]].
 */
export function command(ids, choice = {}, { stock = "Digitone_II_OS1.11.syx", out = "modded.syx" } = {}) {
  const lines = [[stock]];
  for (const id of order(ids)) {
    const line = ["--mod", id];
    if (id === "transients" && choice.transients) {
      line.push("--from", choice.transients.folder ?? "my-transients/");
      if (choice.transients.equal) line.push("--equal-slots");
    }
    if (id === "lfowaves" && choice.lfowaves) {
      (choice.lfowaves.files ?? []).forEach((name, k) => { if (name) line.push("--wavetable", `${k + 1}=${name}`); });
    }
    if (id === "bootscreen" && choice.bootscreen) {
      const { mode, image } = choice.bootscreen;
      if (mode === "ascii" || mode === "spin") line.push("--boot-animation", mode);
      line.push("--boot-image", image);
      if (mode === "flash") line.push("--boot-invert");
    }
    lines.push(line);
  }
  lines.push(["-o", out]);
  return lines;
}
