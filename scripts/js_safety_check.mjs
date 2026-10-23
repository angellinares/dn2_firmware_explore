// The website's safety checklist (site/js/safety.js) of one image, as JSON, for
// test/test_js_safety_matches_cli.py.
//
//   node scripts/js_safety_check.mjs --stock STOCK.syx --image PATCHED.syx [--rebuild]

import { readFileSync } from "node:fs";
import { load } from "../site/js/firmware.js";
import { check } from "../site/js/safety.js";
import { rebuild } from "../site/js/mods/registry.js";

const args = process.argv;
const arg = (n) => args[args.indexOf(`--${n}`) + 1];
const stock = await load(new Uint8Array(readFileSync(arg("stock"))));
let patched;
try {
  patched = await load(new Uint8Array(readFileSync(arg("image"))));
} catch (error) {
  console.log(JSON.stringify({ error: String(error.message ?? error) }));
  process.exit(0);
}
const items = await check(patched, stock, args.includes("--rebuild") ? rebuild : null);
console.log(JSON.stringify(items));
