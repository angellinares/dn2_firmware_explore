/**
 * The browser LFO ONE/HALF length mod against the Python, byte for byte.
 *
 *   node scripts/js_lfolength_check.mjs --syx STOCK.syx --py-content PY_CONTENT.bin
 *
 * `PY_CONTENT.bin` is MAIN OS as `dnfw.mods.lfolength.apply` produces it. Checks:
 * the same section 3, the rebuilt image verifies, and an image already patched
 * is refused.
 */
import { readFileSync } from "node:fs";
import { build, load, replacement, verify } from "../site/js/firmware.js";
import { apply } from "../site/js/mods/lfolength.js";

const arg = (n) => { const i = process.argv.indexOf(`--${n}`); return i >= 0 ? process.argv[i + 1] : null; };
const same = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);
const checks = [];

const firmware = await load(new Uint8Array(readFileSync(arg("syx"))));
const { content, notes } = apply(firmware);
checks.push(["MAIN OS == Python", same(content, new Uint8Array(readFileSync(arg("py-content"))))]);

const built = await build(firmware, new Map([[3, replacement(firmware, 3, content)]]));
const reloaded = await load(built);
const v = await verify(reloaded);
checks.push([`rebuilt image verifies (${v.filter((c) => c.ok).length}/${v.length})`, v.every((c) => c.ok)]);

let refused = false;
try { apply(reloaded); } catch (e) { refused = /not stock/.test(e.message); }
checks.push(["an image already patched is refused", refused]);

for (const [name, ok] of checks) console.log(`${ok ? "OK" : "FAIL"}  ${name}`);
console.log(notes.join("\n"));
process.exit(checks.every(([, ok]) => ok) ? 0 : 1);
