// The images test/test_js_safety_matches_cli.py checks with both checklists (site/js/safety.js
// and dnfw check): a good website build, and one image broken on purpose for each failure the
// checklist can report, each signed again so only the checklist's own rules can catch it.
//
//   node scripts/js_safety_cases.mjs --stock STOCK.syx --out DIR
//
// Writes DIR/<case>.syx and prints the case names.

import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { build, load } from "../site/js/firmware.js";
import { compress, storeRaw } from "../site/js/container/section.js";
import * as modinfo from "../site/js/modinfo.js";
import { applyInOrder } from "../site/js/mods/registry.js";

const args = process.argv;
const arg = (n) => args[args.indexOf(`--${n}`) + 1];
const out = arg("out");
const stock = await load(new Uint8Array(readFileSync(arg("stock"))));
const good = await load(await applyInOrder(stock, ["waverider", "fxmod"]));
const content = (f, id) => { const s = f.container.find(id); return (s.unpack() ?? s.stored).slice(); };
const base = content(stock, 3).length;
const put32 = (b, at, v) => b.set([v >>> 24, (v >>> 16) & 255, (v >>> 8) & 255, v & 255], at);
const u32 = (b, at) => ((b[at] << 24) >>> 0) + (b[at + 1] << 16) + (b[at + 2] << 8) + b[at + 3];

/** FIRMWARE with section ID's content replaced, stored as the original is, signed again. */
async function rebuilt(firmware, id, data) {
  const original = firmware.container.find(id);
  const section = original.unpack() !== null ? compress(id, original.dest, data) : storeRaw(id, original.dest, data);
  return build(firmware, new Map([[id, section]]));
}

async function edited(firmware, id, edit) {
  const data = content(firmware, id);
  edit(data);
  return rebuilt(firmware, id, data);
}

function codeChunks(main) {
  const count = u32(main, base + 8), found = [];
  for (let k = 0; k < count; k++) {
    const at = base + 12 + 12 * k;
    if (String.fromCharCode(...main.subarray(at, at + 4)) === "CODE") found.push(base + u32(main, at + 4));
  }
  return found;
}

/** MAIN OS C with its record's mods list set to MODS, and its image id and hash written again: a
 * record that checks out but does not describe the image. */
function relist(c, mods) {
  const at = modinfo.find(c);
  c[at + 68] = mods.length;
  c.fill(0, at + 72, at + 248);
  mods.forEach((m, k) => c.set(new TextEncoder().encode(m), at + 72 + 16 * k));
  c.fill(0, at + 20, at + 24);
  c.fill(0, at + 252, at + 256);
  put32(c, at + 20, modinfo.xxh32(c));
  put32(c, at + 252, modinfo.xxh32(c.subarray(at, at + 252)));
}

const cases = {
  good: async () => build(good),
  stock: async () => build(stock),
  damaged: async () => { const raw = await build(good); raw[raw.length >> 1] ^= 1; return raw; },
  moved: async () => {                     // the updater's load address, in the container's table
    const head = good.container.head.slice();
    const i = good.container.sections.findIndex((x) => x.id === 4);
    put32(head, 0x20 + 16 * i + 12, good.container.find(4).dest + 0x100);
    return build({ ...good, container: { ...good.container, head } });
  },
  bootstrap: async () => edited(good, 2, (c) => { c[0x100] ^= 0xff; }),
  noloader: async () => { const m = content(stock, 3); const c = new Uint8Array(m.length + 64); c.set(m); return rebuilt(stock, 3, c); },
  directory: async () => edited(good, 3, (c) => put32(c, base + 8, 0xffff)),
  bss: async () => edited(good, 3, (c) => put32(c, codeChunks(c)[0], 0x46000000)),
  dmaload: async () => edited(good, 3, (c) => put32(c, codeChunks(c)[0], 0x466c0000)),
  stack: async () => edited(good, 3, (c) => put32(c, codeChunks(c)[0], 0x47ff0000)),
  overlap: async () => edited(good, 3, (c) => { const [a, b] = codeChunks(c); put32(c, b, u32(c, a)); }),
  dmaname: async () => edited(good, 3, (c) => put32(c, codeChunks(c)[0] + 16, 0x4e6f1300)),
  unfilled: async () => edited(good, 3, (c) => {
    c.set(new TextEncoder().encode("MODINFO-UNFILLED"), modinfo.find(c) + 24);
  }),
  record: async () => edited(good, 3, (c) => { c[modinfo.find(c) + 32] ^= 1; }),
  imageid: async () => edited(good, 3, (c) => { c[0x1000] ^= 1; }),
  relist: async () => edited(good, 3, (c) => relist(c, ["waverider"])),
  unknown: async () => edited(good, 3, (c) => relist(c, ["waverider", "fxmod", "nosuchmod"])),
};

for (const [name, make] of Object.entries(cases)) {
  writeFileSync(join(out, `${name}.syx`), await make());
  console.log(name);
}
