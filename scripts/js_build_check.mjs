// The website's whole build, page after page, for test/test_js_build_matches_cli.py.
//
//   node scripts/js_build_check.mjs --syx STOCK.syx --out DIR --order fxmod,waverider [--order ...]
//                                   [--transients ENTRIES.bin]
//
// ENTRIES.bin holds the transients mod's samples: whole entries of 4,800 int16 little-endian
// samples, for slots 0, 1, ... in order, as the CLI reads them from WAVs with --from.
//
// For each order, applies each mod the way its page does (site/js/mods/registry.js: apply, then
// replacement() and build() for every section it returns, then load() for the next page), and writes the
// final image to DIR/<mods joined by ->.syx. test_js_build_matches_cli.py compares it with
// `dnfw mods apply` of the same mods, so the two patchers cannot drift apart unseen: on
// 2026-10-21 the website was found never to fill the /modinfo record that the CLI fills.

import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { load } from "../site/js/firmware.js";
import { applyInOrder, RUN } from "../site/js/mods/registry.js";
import * as transients from "../site/js/mods/transients.js";

const args = process.argv;
const arg = (n) => args[args.indexOf(`--${n}`) + 1];
const orders = args.flatMap((a, i) => (a === "--order" ? [args[i + 1].split(",")] : []));
const stock = await load(new Uint8Array(readFileSync(arg("syx"))));
if (args.includes("--transients")) {
  const raw = new Uint8Array(readFileSync(arg("transients")));
  const entries = new Map();
  for (let k = 0; k * transients.ENTRY_BYTES < raw.length; k++) {
    entries.set(k, raw.slice(k * transients.ENTRY_BYTES, (k + 1) * transients.ENTRY_BYTES));
  }
  RUN.transients = async (f) => new Map([[7, transients.apply(f, entries).section.unpack()]]);
}

for (const order of orders) {
  const bytes = await applyInOrder(stock, order);
  writeFileSync(join(arg("out"), `${order.join("-")}.syx`), bytes);
  console.log(`built ${order.join(" then ")}`);
}
