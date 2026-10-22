// The website's whole build, page after page, for test/test_js_build_matches_cli.py.
//
//   node scripts/js_build_check.mjs --syx STOCK.syx --out DIR --order fxmod,waverider [--order ...]
//
// For each order, applies each mod the way its page does (apply, then replacement() and build()
// for every section it returns, then load() of the result for the next page), and writes the
// final image to DIR/<mods joined by ->.syx. test_js_build_matches_cli.py compares it with
// `dnfw mods apply` of the same mods, so the two patchers cannot drift apart unseen: on
// 2026-10-21 the website was found never to fill the /modinfo record that the CLI fills.

import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { build, load, replacement } from "../site/js/firmware.js";
import * as arpmodes from "../site/js/mods/arpmodes.js";
import * as fxmod from "../site/js/mods/fxmod.js";
import * as layermidi from "../site/js/mods/layermidi.js";
import * as lfo4 from "../site/js/mods/lfo4.js";
import * as lfolength from "../site/js/mods/lfolength.js";
import * as midiarp from "../site/js/mods/midiarp.js";
import * as moddest from "../site/js/mods/moddest.js";
import * as reloadconfirm from "../site/js/mods/reloadconfirm.js";
import * as waverider from "../site/js/mods/waverider.js";

const MAIN_OS = (mod) => async (f) => new Map([[3, mod.apply(f).content]]);
const RUN = {
  arpmodes: MAIN_OS(arpmodes), fxmod: MAIN_OS(fxmod), layermidi: MAIN_OS(layermidi), lfo4: MAIN_OS(lfo4),
  lfolength: MAIN_OS(lfolength), midiarp: MAIN_OS(midiarp), moddest: MAIN_OS(moddest),
  reloadconfirm: MAIN_OS(reloadconfirm),
  waverider: async (f) => { const r = await waverider.apply(f); return new Map([[3, r.main], [7, r.dsp]]); },
};

const args = process.argv;
const arg = (n) => args[args.indexOf(`--${n}`) + 1];
const orders = args.flatMap((a, i) => (a === "--order" ? [args[i + 1].split(",")] : []));
const stock = await load(new Uint8Array(readFileSync(arg("syx"))));

for (const order of orders) {
  let firmware = stock, bytes = null;
  for (const mod of order) {
    const sections = await RUN[mod](firmware);
    bytes = await build(firmware, new Map([...sections].map(([id, c]) => [id, replacement(firmware, id, c, mod)])));
    firmware = await load(bytes);
  }
  writeFileSync(join(arg("out"), `${order.join("-")}.syx`), bytes);
  console.log(`built ${order.join(" then ")}`);
}
