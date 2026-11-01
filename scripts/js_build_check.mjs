// The website's whole build, page after page, for test/test_js_build_matches_cli.py.
//
//   node scripts/js_build_check.mjs --syx STOCK.syx --out DIR --order fxmod,waverider [--order ...]
//                                   [--transients SAMPLES.bin --transients-dir DIR]
//                                   [--wavetable TABLE.json] [--boot-image MARK.pgm]
//
// SAMPLES.bin holds the transients mod's samples: 2,400 int16 little-endian samples for slots
// 0, 1, ... in order, as the CLI reads them from the WAVs in --transients-dir with --from. Each
// is padded to its slot. Order elements with options, as the Mod Composer sets them:
//   transients, transients-equal   factory slot sizes, or equal slots (--equal-slots)
//   lfowaves-custom                TABLE.json as wavetable 2 (--wavetable 2=TABLE.json)
//   bootscreen                     MARK.pgm, flashing (--boot-image MARK.pgm --boot-invert)
//   bootscreen-still, -ascii, -spin  the other three animations
//
// For each order, applies each mod the way the Mod Composer does (site/js/mods/compose.js, which
// runs registry.js's pages one after the other: apply, then replacement() and build() for every
// section it returns, then load() for the next), and writes the final image to
// DIR/<elements joined by ->.syx. It also writes DIR/args.json: for each order, the arguments of
// `dnfw mods apply` that compose.command() gives for it, which the test runs. So the two patchers,
// and the command the composer shows, cannot drift apart unseen. On 2026-10-21 the website was
// found never to fill the /modinfo record that the CLI fills.

import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { load } from "../site/js/firmware.js";
import { applyInOrder } from "../site/js/mods/registry.js";
import { command, runners } from "../site/js/mods/compose.js";
import * as transients from "../site/js/mods/transients.js";
import { parsePgm } from "../site/js/pgm.js";
import { loadTable, toBytes } from "../site/js/wavetable.js";

const args = process.argv;
const has = (n) => args.includes(`--${n}`);
const arg = (n) => args[args.indexOf(`--${n}`) + 1];
const orders = args.flatMap((a, i) => (a === "--order" ? [args[i + 1].split(",")] : []));
const stock = await load(new Uint8Array(readFileSync(arg("syx"))));

/** Each order element -> [mod id, that mod's part of the composer's choice]. */
const element = {};
if (has("transients")) {
  const raw = new Uint8Array(readFileSync(arg("transients")));
  const HIT = 2400 * 2;
  const bank = (equal) => {
    const sizes = transients.lengths(equal);
    const entries = new Map();
    for (let k = 0; k * HIT < raw.length; k++) {
      entries.set(k, transients.fit(raw.slice(k * HIT, (k + 1) * HIT), sizes[k]));
    }
    return { entries, equal, folder: arg("transients-dir") };
  };
  element.transients = ["transients", bank(false)];
  element["transients-equal"] = ["transients", bank(true)];
}
if (has("wavetable")) {
  const path = arg("wavetable");
  const table = toBytes(loadTable(new Uint8Array(readFileSync(path)), path));
  element["lfowaves-custom"] = ["lfowaves", { tables: [null, table, null], files: [null, path, null] }];
}
if (has("boot-image")) {
  const image = arg("boot-image");
  const pgm = parsePgm(new Uint8Array(readFileSync(image)));
  const lit = (x, y) => pgm.data[y * pgm.w + x] >= 128;
  for (const mode of ["flash", "still", "ascii", "spin"]) {
    element[mode === "flash" ? "bootscreen" : `bootscreen-${mode}`] = ["bootscreen", { lit, mode, image }];
  }
}

const cli = {};
for (const order of orders) {
  const ids = [], choice = {};
  for (const e of order) {
    const [id, part] = element[e] ?? [e, null];
    ids.push(id);
    if (part) choice[id] = part;
  }
  const name = order.join("-");
  // The order as given, not compose.order(): the test also checks orders a user can only make
  // by loading one page's file into the next.
  const bytes = await applyInOrder(stock, ids, runners(choice));
  writeFileSync(join(arg("out"), `${name}.syx`), bytes);
  cli[name] = command(ids, choice, { stock: "STOCK", out: "OUT" }).flat();
  console.log(`built ${order.join(" then ")}`);
}
writeFileSync(join(arg("out"), "args.json"), JSON.stringify(cli, null, 1));
