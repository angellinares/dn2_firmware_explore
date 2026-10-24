// The website's whole build, page after page, for test/test_js_build_matches_cli.py.
//
//   node scripts/js_build_check.mjs --syx STOCK.syx --out DIR --order fxmod,waverider [--order ...]
//                                   [--transients SAMPLES.bin]
//
// SAMPLES.bin holds the transients mod's samples: 2,400 int16 little-endian samples for slots
// 0, 1, ... in order, as the CLI reads them from WAVs with --from. Each is padded to its slot.
// Order element `transients` uses the factory slot sizes, `transients-equal` equal slots
// (the CLI's --equal-slots).
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
  const HIT = 2400 * 2;
  const run = (equal) => async (f) => {
    const sizes = transients.lengths(equal);
    const entries = new Map();
    for (let k = 0; k * HIT < raw.length; k++) {
      entries.set(k, transients.fit(raw.slice(k * HIT, (k + 1) * HIT), sizes[k]));
    }
    return new Map([[7, transients.apply(f, entries, { equal }).section.unpack()]]);
  };
  RUN.transients = run(false);
  RUN["transients-equal"] = run(true);
}

for (const order of orders) {
  const bytes = await applyInOrder(stock, order);
  writeFileSync(join(arg("out"), `${order.join("-")}.syx`), bytes);
  console.log(`built ${order.join(" then ")}`);
}
