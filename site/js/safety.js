/**
 * The safety checklist of a patched Digitone II image against the stock image it came from.
 *
 * Port of `src/dnfw/firmware/safety.py`: the same items, in the same order, with the same
 * words (test/test_js_safety_matches_cli.py holds the two together). The module's docstring
 * there says what each item checks. Each item is { key, title, status, detail }, the status one
 * of pass, warn, fail, info, skip. The list never calls an image safe.
 */

import { verify } from "./firmware.js";
import * as ele3 from "./container/ele3.js";
import * as modinfo from "./modinfo.js";
import { installed, parseArea, unpackCode, RUNTIME_VA } from "./mods/platform.js";

const MAIN_OS = 3, DSP = 7;
const BASE = 0x40000400;
export const KNOWN = {
  "1.11": {
    2: "038aa5d188af120f3ca2ce4299147952c505f6bc2e8d24c2d1f16db8c21a9d62",
    3: "57b06a7960b7c3dc9803bde6b31896b89a2fbdcc404a932ff503f3856d4d7a61",
    4: "951ced17c9e9d9421c6d910eb1201726d13498c2cc64f33e7d4767a4771419fa",
    5: "becc493e90833ee87cde7a942db1faad859b2cf3c662eb225e1070f199125fab",
    7: "336e340aa0cdcd34e314cfa44849f709a3134f6bd4cd57dfc7e15702c83115e2",
    8: "6943b2f27773f40f1e7857ea6fa7a121269e930bd403098e6b6c00002327dc20",
  },
};
const STOCK_DMA = [0x466b8000, 0x46701340];        // mods/ramcheck.py
const WINDOW = 0x08000000;
const STACK_TOP = 0x48000000, STACK_RESERVE = 0x20000;
const STOCK_RAM_END = STOCK_DMA[1];
const STACK_FLOOR = STACK_TOP - STACK_RESERVE;
const SHOWN = 8;
export const NOT_CHECKED = [
  "RAM that a mod uses without an area chunk: the image does not declare it.",
  "Whether the new code reads or writes the addresses it names.",
  "The DSP's memory: which parts of it the stock DSP code uses.",
  "Whether the new code runs correctly: only the emulator and the instrument can show that.",
];

const u32 = (d, at) => ((d[at] << 24) >>> 0) + (d[at + 1] << 16) + (d[at + 2] << 8) + d[at + 3];
const h8 = (v) => `0x${(v >>> 0).toString(16).padStart(8, "0")}`;
const grouped = (n) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
const ascii = (d, at) => String.fromCharCode(d[at], d[at + 1], d[at + 2], d[at + 3]);
const item = (key, title, status, detail) => ({ key, title, status, detail });
const same = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);
const sectionName = (k) => (ele3.name(k) === "?" ? String(k) : `${k} (${ele3.name(k)})`);

/** A section's content, as `compare.content` gives it: depacked, or the stored bytes when raw. */
const content = (section) => section.unpack() ?? section.stored;

async function sha256(bytes) {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  return Array.from(digest, (b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * The checklist of PATCHED against STOCK (both from `firmware.load`). REBUILD(stock, mods, tag)
 * -> Map(section id -> content) for every section, or a string that says why it cannot rebuild.
 */
export async function check(patched, stock, rebuild = null) {
  const items = [await guard("file", "The file is intact", () => file(patched))];
  if (items[0].status !== "pass") return items;
  const version = await guard("stock", "The stock file is a known Digitone II OS", () => stockItem(stock));
  items.push(version);
  if (version.status !== "pass") return items;
  const shape = await guard("layout", "The same OS version and sections", () => layout(patched, stock));
  items.push(shape);
  if (shape.status !== "pass") return items;
  const ours = contents(patched), theirs = contents(stock);
  const main = ours.get(MAIN_OS), base = theirs.get(MAIN_OS);
  items.push(await guard("recovery", "The bootstrap and the other recovery sections are stock",
                         () => recovery(ours, theirs)));
  items.push(runs("edits", "Changes inside stock's MAIN OS", base, main.subarray(0, base.length), BASE));
  const added = await guard("area", "The added code is a DNFW area", () => areaItems(main, base));
  items.push(...(Array.isArray(added) ? added : [added]));
  const dspBase = theirs.get(DSP), dsp = ours.get(DSP);
  items.push(runs("dsp", "Changes in the DSP image", dspBase, dsp.subarray(0, dspBase.length), 0,
                  dsp.length - dspBase.length));
  let found;
  try {
    found = record(main);
  } catch (error) {
    found = [item("record", "The /modinfo record checks out", "fail", `unreadable: ${error.message ?? error}`), [], ""];
  }
  const [rec, mods, tag] = found;
  items.push(rec);
  items.push(await guard("rebuild", "The record's mods rebuild this image exactly",
                         () => rebuildItem(ours, stock, mods, tag, rebuild)));
  return items;
}

async function guard(key, title, fn) {
  try {
    return await fn();
  } catch (error) {
    return item(key, title, "fail", `this part of the image could not be read: ${error.message ?? error}`);
  }
}

function contents(firmware) {
  return new Map(firmware.container.sections.map((s) => [s.id, content(s)]));
}

async function file(patched) {
  const title = "The file is intact";
  const bad = (await verify(patched)).filter((c) => !c.ok);
  if (bad.length) return item("file", title, "fail", bad.map((c) => `${c.name}: ${c.detail}`).join("; "));
  if (!patched.signed) return item("file", title, "fail", "it is not signed, so it is not a Digitone II OS file");
  return item("file", title, "pass", "every checksum and the signature verify");
}

async function stockItem(stock) {
  const title = "The stock file is a known Digitone II OS";
  const have = {};
  for (const s of stock.container.sections) have[s.id] = await sha256(content(s));
  for (const [version, want] of Object.entries(KNOWN)) {
    const ids = Object.keys(want);
    if (ids.length === Object.keys(have).length && ids.every((k) => have[k] === want[k])) {
      return item("stock", title, "pass", `Digitone II OS ${version}, every section as Elektron ships it`);
    }
  }
  return item("stock", title, "fail",
              `its sections match no known stock OS (${Object.keys(KNOWN).join(", ")}): only these are supported`);
}

function layout(patched, stock) {
  const title = "The same OS version and sections";
  const a = patched.container, b = stock.container;
  if (a.version !== b.version || a.build !== b.build) {
    return item("layout", title, "fail", `version ${a.version} build ${a.build}, stock ${b.version} build ${b.build}`);
  }
  const ids = (c) => c.sections.map((s) => `${s.id}:${s.dest}`).join(",");
  if (ids(a) !== ids(b)) return item("layout", title, "fail", "the sections or their load addresses differ from stock's");
  return item("layout", title, "pass", `version ${a.version}, ${a.sections.length} sections at stock's addresses`);
}

function recovery(ours, theirs) {
  const title = "The bootstrap and the other recovery sections are stock";
  const other = [...theirs.keys()].filter((k) => k !== MAIN_OS && k !== DSP).sort((x, y) => x - y);
  const changed = other.filter((k) => !same(ours.get(k), theirs.get(k)));
  if (changed.length) return item("recovery", title, "fail", `changed: ${changed.map(sectionName).join(", ")}`);
  return item("recovery", title, "pass", `identical to stock: ${other.map(sectionName).join(", ")}`);
}

function runs(key, title, base, next, va, grown = 0) {
  const found = [];
  const n = Math.min(base.length, next.length);
  let i = 0;
  while (i < n) {
    if (base[i] === next[i]) { i++; continue; }
    let j = i;
    while (j < n && base[j] !== next[j]) j++;
    found.push([i, j]);
    i = j;
  }
  if (!found.length && grown <= 0) return item(key, title, "info", "none");
  const total = found.reduce((t, [a, b]) => t + b - a, 0);
  const shown = found.slice(0, SHOWN).map(([a, b]) => `${h8(va + a)} (${b - a} B)`).join(", ");
  const more = found.length > SHOWN ? `, and ${found.length - SHOWN} more` : "";
  let detail = `${found.length} changed runs, ${grouped(total)} bytes` + (found.length ? `: ${shown}${more}` : "");
  if (grown > 0) detail += `; ${grouped(grown)} bytes added at the end`;
  return item(key, title, "info", detail);
}

function areaItems(main, base) {
  const title = "The added code is a DNFW area";
  if (main.length === base.length) {
    return [item("area", title, "info", "nothing is added past stock's MAIN OS"),
            item("ram", "Run-time RAM stays out of stock's", "skip", "no area"),
            dma(main, base, [])];
  }
  if (main.length < base.length) return [item("area", title, "fail", "MAIN OS is shorter than stock's")];
  if (!installed(main)) {
    return [item("area", title, "fail", "bytes are added past MAIN OS, but the platform loader is not installed")];
  }
  const blob = main.subarray(base.length);
  let chunks;
  try {
    chunks = parseArea(blob);
  } catch (error) {
    return [item("area", title, "fail", String(error.message).replace(/^the appended area: /, ""))];
  }
  const kinds = [...new Set(chunks.map(([c]) => c))].sort().join(", ");
  return [item("area", title, "pass", `${chunks.length} chunks (${kinds}), ${grouped(blob.length)} bytes`),
          ram(ranges(blob)), dma(main, base, chunks)];
}

function ranges(blob) {
  const count = u32(blob, 8);
  const out = [[RUNTIME_VA, RUNTIME_VA + 12 + 12 * count, "the area's header"]];
  for (let k = 0; k < count; k++) {
    const at = 12 + 12 * k;
    const cid = ascii(blob, at), offset = u32(blob, at + 4), length = u32(blob, at + 8);
    if (cid === "CODE") {
      const code = unpackCode(blob.subarray(offset, offset + length));
      out.push([code.load, code.load + code.image.length + code.bss, `CODE at ${h8(code.load)}`]);
    } else {
      out.push([RUNTIME_VA + offset, RUNTIME_VA + offset + length, `${cid} data`]);
    }
  }
  return out;
}

const cached = (a) => (a >= STACK_TOP && a < STACK_TOP + WINDOW ? a - WINDOW : a);

function ram(list) {
  const title = "Run-time RAM stays out of stock's";
  const bad = [];
  for (const [l, h, what] of list) {
    const lo = cached(l), hi = cached(h);
    if (lo < STOCK_RAM_END) {
      bad.push(`${what} (${h8(lo)}..${h8(hi)}) is inside stock's RAM, which ends at ${h8(STOCK_RAM_END)}`);
    } else if (hi > STACK_FLOOR) {
      bad.push(`${what} (${h8(lo)}..${h8(hi)}) reaches the stack's reserve at ${h8(STACK_FLOOR)}`);
    }
  }
  const spans = list.filter(([l, h]) => h > l).map(([l, h, w]) => [cached(l), cached(h), w])
    .sort((x, y) => x[0] - y[0] || x[1] - y[1] || (x[2] < y[2] ? -1 : x[2] > y[2] ? 1 : 0));
  for (let k = 0; k + 1 < spans.length; k++) {
    if (spans[k + 1][0] < spans[k][1]) bad.push(`${spans[k][2]} and ${spans[k + 1][2]} overlap at ${h8(spans[k + 1][0])}`);
  }
  if (bad.length) return item("ram", title, "fail", bad.join("; "));
  const lo = Math.min(...spans.map((s) => s[0])), hi = Math.max(...spans.map((s) => s[1]));
  return item("ram", title, "pass", `${spans.length} ranges, all in ${h8(lo)}..${h8(hi)}, none overlapping`);
}

const isText = (v) => [24, 16, 8, 0].every((s) => { const b = (v >>> s) & 0xff; return b >= 0x20 && b <= 0x7e; });

function named(base, main, chunks, lo, hi) {
  const found = [];
  const n = base.length;
  let i = 0;
  while (i < n) {
    if (base[i] === main[i]) { i++; continue; }
    let j = i;
    while (j < n && base[j] !== main[j]) j++;
    for (let at = Math.max(0, i - 3) & ~1; at < Math.min(n, j + 3) - 3; at += 2) {
      const v = u32(main, at);
      const was = u32(base, at);
      if (lo <= v && v < hi && !(lo <= was && was < hi)) found.push([BASE + at, v]);
    }
    i = j;
  }
  for (const [cid, data] of chunks) {
    if (cid !== "CODE") continue;
    const code = unpackCode(data);
    for (let at = 0; at < code.image.length - 3; at += 2) {
      const v = u32(code.image, at);
      if (lo <= v && v < hi) found.push([code.load + at, v]);
    }
  }
  return found;
}

function dma(main, base, chunks) {
  const title = "No new reference to stock's DMA buffers";
  const [lo, hi] = STOCK_DMA;
  const keyed = new Map();
  for (const [at, v] of [...named(base, main, chunks, lo, hi), ...named(base, main, chunks, lo + WINDOW, hi + WINDOW)]) {
    if (!isText(v)) keyed.set(`${at}:${v}`, [at, v]);
  }
  if (!keyed.size) return item("dma", title, "pass", "the new bytes name no address in stock's DMA section");
  const found = [...keyed.values()].sort((x, y) => x[0] - y[0] || x[1] - y[1]);
  const shown = found.slice(0, SHOWN).map(([at, v]) => `${h8(at)} names ${h8(v)}`).join(", ");
  return item("dma", title, "warn",
              `${found.length} places name stock's DMA section (${shown}). A mod may read it on `
              + "purpose; writing there damages saved projects");
}

function record(main) {
  const title = "The /modinfo record checks out";
  const at = modinfo.find(main);
  if (at === null) return [item("record", title, "skip", "this image has no /modinfo record"), [], ""];
  const info = modinfo.parse(main.subarray(at, at + modinfo.BYTES));
  if (!info.filled) return [item("record", title, "warn", "the record is present but was never filled"), [], ""];
  if (!info.ok) return [item("record", title, "fail", "the record's hash does not match its bytes"), [], ""];
  const zeroed = main.slice();
  zeroed.fill(0, at + 20, at + 24);
  zeroed.fill(0, at + 252, at + 256);
  if (modinfo.xxh32(zeroed) !== info.imageId) {
    return [item("record", title, "fail", "the record's image id does not match MAIN OS: "
                 + "something changed MAIN OS after the record was written"), [], ""];
  }
  const mods = info.mods.map(([m]) => m);
  return [item("record", title, "pass", `tag ${info.tag}, build ${info.commit}, mods: ${mods.join(", ")}`), mods, info.tag];
}

/** MAIN OS as the stock part and the area's chunks, each record zeroed: `_canonical` in safety.py. */
function canonical(main, baseLength) {
  if (main.length <= baseLength) return [main, []];
  const chunks = parseArea(main.subarray(baseLength)).map(([cid, data]) => {
    const at = modinfo.find(data);
    const out = data.slice();
    if (at !== null) out.fill(0, at, at + modinfo.BYTES);
    return [cid, out];
  });
  const key = ([cid, data]) => cid + ":" + Array.from(data, (b) => b.toString(16).padStart(2, "0")).join("");
  return [main.subarray(0, baseLength), chunks.map(key).sort()];
}

async function rebuildItem(ours, stock, mods, tag, rebuild) {
  const title = "The record's mods rebuild this image exactly";
  if (!mods.length) return item("rebuild", title, "skip", "no mods list to rebuild from");
  if (rebuild === null) return item("rebuild", title, "skip", "no rebuild was asked for");
  const got = await rebuild(stock, mods, tag);
  if (typeof got === "string") return item("rebuild", title, "skip", got);
  const baseLength = content(stock.container.find(MAIN_OS)).length;
  const [sa, ca] = canonical(got.get(MAIN_OS), baseLength);
  const [sb, cb] = canonical(ours.get(MAIN_OS), baseLength);
  const keys = (m) => [...m.keys()].sort((x, y) => x - y).join(",");
  const others = [...ours.keys()].filter((k) => k !== MAIN_OS).every((k) => got.has(k) && same(got.get(k), ours.get(k)));
  if (keys(got) === keys(ours) && same(sa, sb) && same(ca, cb) && others) {
    return item("rebuild", title, "pass", `stock plus ${mods.join(", ")} gives the same image, section for section`);
  }
  return item("rebuild", title, "warn",
              `stock plus ${mods.join(", ")} gives a different image. The file may come from another `
              + "version of the patcher, have options set, or have changes the record does not list");
}
