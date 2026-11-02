/**
 * The browser hook bus against the Python, byte for byte, chained the way a user
 * chains pages: one page's download loaded into the next.
 *
 *   node scripts/js_bus_check.mjs --syx STOCK.syx --py-dir DIR
 *
 * DIR holds the Python side's MAIN OS for each chain (`test/test_js_bus.py` writes
 * them, named after the order, for example `waverider-fxmod.bin`): fxmod, lfo4 and
 * Waverider, the three mods that share the bus's sites and counts. Every image is
 * rebuilt, re-signed and reloaded before the next mod sees it, and each rebuilt
 * image must verify.
 */
import { readFileSync } from "node:fs";
import { build, load, replacement, verify } from "../site/js/firmware.js";
import * as fxmod from "../site/js/mods/fxmod.js";
import * as lfo4 from "../site/js/mods/lfo4.js";
import * as waverider from "../site/js/mods/waverider.js";
import { locate, modSlots, sizeAt, xxh32 } from "../site/js/modinfo.js";

const arg = (n) => { const i = process.argv.indexOf(`--${n}`); return i >= 0 ? process.argv[i + 1] : null; };
const same = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);
const checks = [];
// the /modinfo record's build part (20..247, and 252 to the end: the hash, and a 512-byte
// record's mods 12 and up): the browser fills it at every
// build (modinfo.js); the Python payloads here are the mods' own, before `dnfw mods apply`'s fill
const blank = (b) => {
  const out = b.slice(), at = locate(out);
  if (at >= 0) { out.fill(0, at + 20, at + 248); out.fill(0, at + 252, at + sizeAt(out, at)); }
  return out;
};
const listed = (b) => {
  const at = locate(b), n = sizeAt(b, at), rec = b.subarray(at, at + n);
  const hash = (rec[n - 4] << 24 | rec[n - 3] << 16 | rec[n - 2] << 8 | rec[n - 1]) >>> 0;
  const ids = modSlots(n).slice(0, rec[68]).map((p) =>
    new TextDecoder().decode(rec.subarray(p, p + 12)).replace(/\0.*$/s, ""));
  return hash === xxh32(rec.subarray(0, n - 4)) ? ids : null;
};

const run = {
  fxmod: async (f) => new Map([[3, fxmod.apply(f).content]]),
  lfo4: async (f) => new Map([[3, lfo4.apply(f).content]]),
  waverider: async (f) => { const r = await waverider.apply(f); return new Map([[3, r.main], [7, r.dsp]]); },
};
const stock = await load(new Uint8Array(readFileSync(arg("syx"))));

for (const order of [["fxmod", "waverider"], ["waverider", "fxmod"], ["lfo4", "waverider"],
                     ["waverider", "lfo4"], ["fxmod", "waverider", "lfo4"]]) {
  let firmware = stock, main = null;
  for (const mod of order) {
    const sections = await run[mod](firmware);
    main = sections.get(3);
    const parts = new Map([...sections].map(([id, c]) => [id, replacement(firmware, id, c, mod)]));
    const reloaded = await load(await build(firmware, parts));
    const v = await verify(reloaded);
    checks.push([`${order.join(" then ")}: after ${mod}, the rebuilt image verifies `
                 + `(${v.filter((c) => c.ok).length}/${v.length})`, v.every((c) => c.ok)]);
    firmware = reloaded;
  }
  const py = new Uint8Array(readFileSync(`${arg("py-dir")}/${order.join("-")}.bin`));
  checks.push([`${order.join(" then ")}: MAIN OS == Python, the record's build part aside`,
               same(blank(main), blank(py))]);
  const ids = listed(firmware.container.find(3).unpack());
  const want = order.slice(order.indexOf("waverider"));        // mods before Waverider leave no record
  checks.push([`${order.join(" then ")}: the record checks out and lists ${want.join(", ")}`,
               ids !== null && ids.join() === want.join()]);
}

for (const [name, ok] of checks) console.log(`${ok ? "OK" : "FAIL"}  ${name}`);
process.exit(checks.every(([, ok]) => ok) ? 0 : 1);
