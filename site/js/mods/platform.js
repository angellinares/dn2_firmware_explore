/**
 * The platform: one start-up loader and one appended area, shared by every mod.
 *
 * The browser half of `src/dnfw/mods/platform.py`, which carries the design:
 * the start-up calls at 0x4000053e become one call to the loader in the cave at
 * 0x4028da6e, and every mod that needs room past the end of MAIN OS adds its
 * chunks to one `DNFW` area. A page applies one mod and the user loads that
 * download into the next page, so each mod here *adds* to whatever area the
 * image already carries (`split`, then `join`), exactly as the CLI does.
 *
 * The hook bus (`src/dnfw/mods/bus.py`, which carries its design) is here too:
 * the sites and counts several mods share. `split` puts them back to stock and
 * `join` writes them again for every mod in the area.
 */

import { CODE } from "./platform-code.js";

export const ID = "platform";
export const SECTION = 3;
const BASE = 0x40000400;
export const STOCK_LENGTH = CODE.stock_length;
export const RUNTIME_VA = CODE.runtime_va;
export const DATA_LIMIT = CODE.data_limit;

const MAGIC = "DNFW", CODE_ID = "CODE", DISP_ID = "DISP";
export { CODE_ID as CODE, DISP_ID as DISP };

export class ModError extends Error {}

const hex = (s) => Uint8Array.from(s.match(/../g) ?? [], (b) => parseInt(b, 16));
const toHex = (a) => Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");
/** Python's `f"{n:,}"`, whatever the browser's locale. */
const grouped = (n) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
const h8 = (v) => `0x${(v >>> 0).toString(16).padStart(8, "0")}`;
const u32 = (d, at) => ((d[at] << 24) >>> 0) + (d[at + 1] << 16) + (d[at + 2] << 8) + d[at + 3];
const be32 = (v) => Uint8Array.of(v >>> 24, (v >>> 16) & 0xff, (v >>> 8) & 0xff, v & 0xff);
const ascii = (d, at) => String.fromCharCode(d[at], d[at + 1], d[at + 2], d[at + 3]);
const concat = (parts) => {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let at = 0;
  for (const p of parts) { out.set(p, at); at += p.length; }
  return out;
};
const pad4 = (n) => (4 - (n % 4)) % 4;

export function extents(areaLength = 0) {
  return [...loaderExtents(areaLength), ...busExtents()];
}

/** The start-up call, the loader's cave and the appended area. */
export function loaderExtents(areaLength = 0) {
  const out = [
    { section: SECTION, start: CODE.calls_va - BASE, length: CODE.calls_stock.length / 2,
      what: "start-up calls -> the platform loader", owner: ID },
    { section: SECTION, start: CODE.cave_va - BASE, length: CODE.cave_cap,
      what: "the platform loader's cave", owner: ID },
  ];
  if (areaLength) {
    out.push({ section: SECTION, start: STOCK_LENGTH, length: areaLength,
               what: "the appended DNFW area", owner: ID });
  }
  return out;
}

// ---- the area's layout: dnfw.patch.area

/** [[id, data]] -> the area. Order is kept; each chunk is padded to four bytes. */
export function buildArea(chunks) {
  const head = 12 + 12 * chunks.length;
  const dir = [], body = [];
  let offset = head;
  for (const [cid, data] of chunks) {
    if (cid.length !== 4) throw new ModError(`chunk id ${cid} is not four bytes`);
    dir.push(Uint8Array.from(cid, (c) => c.charCodeAt(0)), be32(offset), be32(data.length));
    body.push(data, new Uint8Array(pad4(data.length)));
    offset += data.length + pad4(data.length);
  }
  return concat([Uint8Array.from(MAGIC, (c) => c.charCodeAt(0)), be32(offset), be32(chunks.length),
                 ...dir, ...body]);
}

export function parseArea(blob) {
  if (blob.length < 12 || ascii(blob, 0) !== MAGIC) throw new ModError("the appended area: no DNFW area here");
  const total = u32(blob, 4), count = u32(blob, 8);
  if (total > blob.length) {
    throw new ModError(`the appended area: area claims ${total} B, only ${blob.length} present`);
  }
  const out = [];
  for (let i = 0; i < count; i++) {
    const cid = ascii(blob, 12 + 12 * i);
    const off = u32(blob, 16 + 12 * i), n = u32(blob, 20 + 12 * i);
    if (off + n > total) throw new ModError(`the appended area: chunk ${cid} runs past the area`);
    out.push([cid, blob.slice(off, off + n)]);
  }
  return out;
}

export function codeChunk(load, image, bss = 0, init = 0) {
  if (load % 4) throw new ModError(`code load address ${h8(load)} is not longword-aligned`);
  const padded = concat([image, new Uint8Array(pad4(image.length))]);
  return concat([be32(load), be32(padded.length), be32(bss + pad4(bss)), be32(init), padded]);
}

export function unpackCode(data) {
  const n = u32(data, 4);
  return { load: u32(data, 0), image: data.slice(16, 16 + n), bss: u32(data, 8), init: u32(data, 12) };
}

// ---- the loader and the area in MAIN OS

export function installed(content) {
  const at = CODE.calls_va - BASE;
  return toHex(content.subarray(at, at + CODE.hook.length / 2)) === CODE.hook;
}

/** MAIN OS -> [MAIN OS without the area, the chunks already in it]. */
export function split(content) {
  if (content.length < STOCK_LENGTH) {
    throw new ModError(`MAIN OS is ${grouped(content.length)} B, shorter than ${grouped(STOCK_LENGTH)}: `
      + "not Digitone II 1.11");
  }
  if (content.length === STOCK_LENGTH) return [content.slice(), []];
  if (!installed(content)) {
    throw new ModError("MAIN OS carries appended data but not the platform loader: "
      + "it was built by something else; start from stock 1.11");
  }
  const base = content.slice(0, STOCK_LENGTH);
  const chunks = detach(base, parseArea(content.subarray(STOCK_LENGTH)));
  return [base, chunks];
}

/** MAIN OS without an area + chunks -> MAIN OS with the loader and the area. */
export function join(base, chunks) {
  if (base.length !== STOCK_LENGTH) {
    throw new ModError(`MAIN OS is ${grouped(base.length)} B, not ${grouped(STOCK_LENGTH)}`);
  }
  const content = base.slice();
  const calls = CODE.calls_va - BASE, cave = CODE.cave_va - BASE, link = CODE.link_va - BASE;
  const loader = hex(CODE.loader);
  if (!installed(content)) {
    if (toHex(content.subarray(calls, calls + CODE.calls_stock.length / 2)) !== CODE.calls_stock) {
      throw new ModError(`${h8(CODE.calls_va)} holds neither the stock start-up calls `
        + "nor the platform loader's call: another mod has changed it");
    }
    if (content.subarray(cave, cave + CODE.cave_cap).some((b) => b !== 0)) {
      throw new ModError(`the platform loader's cave at ${h8(CODE.cave_va)} is in use`);
    }
    content.set(loader, link);
    content.set(hex(CODE.hook), calls);
  } else if (toHex(content.subarray(link, link + loader.length)) !== CODE.loader) {
    throw new ModError("the start-up call reaches a loader that is not this platform's");
  }
  const all = attach(content, [...chunks]);
  const ordered = [...all.filter(([c]) => c !== CODE_ID), ...all.filter(([c]) => c === CODE_ID)];
  const blob = buildArea(ordered);
  checkRuntime(blob);
  return concat([content, blob, new Uint8Array(pad4(blob.length))]);
}

export function checkRuntime(blob) {
  const count = u32(blob, 8);
  let windowEnd = RUNTIME_VA + 12 + 12 * count;
  const ranges = [];
  for (let i = 0; i < count; i++) {
    const cid = ascii(blob, 12 + 12 * i);
    const off = u32(blob, 16 + 12 * i), n = u32(blob, 20 + 12 * i);
    if (cid === CODE_ID) {
      const c = unpackCode(blob.subarray(off, off + n));
      ranges.push([c.load, c.load + c.image.length + c.bss, `CODE at ${h8(c.load)}`]);
    } else {
      windowEnd = Math.max(windowEnd, RUNTIME_VA + off + n);
    }
  }
  if (windowEnd > DATA_LIMIT) {
    throw new ModError(`the data chunks run to ${h8(windowEnd)}, past the data window's end ${h8(DATA_LIMIT)}`);
  }
  ranges.push([RUNTIME_VA, DATA_LIMIT, "the data window"]);
  ranges.sort((a, b) => a[0] - b[0] || a[1] - b[1] || (a[2] < b[2] ? -1 : 1));
  for (let i = 1; i < ranges.length; i++) {
    const [aLo, aHi, a] = ranges[i - 1], [bLo, bHi, b] = ranges[i];
    if (bLo < aHi) throw new ModError(`${a} and ${b} overlap at run time (${h8(bLo)}..${h8(Math.min(aHi, bHi))})`);
  }
}

export function add(content, chunks) {
  const [base, have] = split(content);
  return join(base, [...have, ...chunks]);
}

// ---- displaced instructions

export function displace(siteVa, length, copyVa) {
  return [DISP_ID, concat([be32(siteVa), be32(length), be32(copyVa)])];
}

export function displaced(chunks) {
  const out = [];
  for (const [cid, data] of chunks) {
    if (cid !== DISP_ID) continue;
    for (let at = 0; at < data.length; at += 12) out.push([u32(data, at), u32(data, at + 4), u32(data, at + 8)]);
  }
  return out;
}

/** N bytes at VA, from the copy that runs if another mod's hook displaced them. */
export function read(content, chunks, va, n) {
  for (const [site, length, copy] of displaced(chunks)) {
    if (!(site <= va && va + n <= site + length)) continue;
    const target = copy + (va - site);
    for (const [cid, data] of chunks) {
      if (cid !== CODE_ID) continue;
      const c = unpackCode(data);
      if (c.load <= target && target + n <= c.load + c.image.length) {
        return c.image.slice(target - c.load, target - c.load + n);
      }
    }
  }
  return content.slice(va - BASE, va - BASE + n);
}

/** Write NEW over STOCK at VA, in CONTENT or in the copy another mod's hook replays. */
export function write(content, chunks, va, stock, next, what = "") {
  const label = `${h8(va)}${what ? ` (${what})` : ""}`;
  for (const [site, length, copy] of displaced(chunks)) {
    if (va + stock.length <= site || site + length <= va) continue;
    if (!(site <= va && va + stock.length <= site + length)) {
      throw new ModError(`${label} straddles a site another mod's hook displaced (${h8(site)}, ${length} B)`);
    }
    const target = copy + (va - site);
    for (let i = 0; i < chunks.length; i++) {
      if (chunks[i][0] !== CODE_ID) continue;
      const c = unpackCode(chunks[i][1]);
      if (!(c.load <= target && target < c.load + c.image.length)) continue;
      const at = target - c.load;
      if (toHex(c.image.subarray(at, at + stock.length)) !== toHex(stock)) {
        throw new ModError(`${label} is not stock in the copy at ${h8(target)}; another mod has changed it`);
      }
      c.image.set(next, at);
      chunks[i] = [CODE_ID, codeChunk(c.load, c.image, c.bss, c.init)];
      return;
    }
    throw new ModError(`${label}: the displaced copy at ${h8(target)} is in no CODE chunk`);
  }
  const at = va - BASE;
  if (toHex(content.subarray(at, at + stock.length)) !== toHex(stock)) {
    throw new ModError(`${label} is not stock (${toHex(content.subarray(at, at + 12))}...); another `
      + "mod has changed it, or this is not Digitone II 1.11");
  }
  content.set(next, at);
}

// ---- the hook bus: dnfw.mods.bus

const EVNT = "EVNT", ADDS = "ADDS";
export { EVNT, ADDS };
export const BUS_VA = CODE.bus.load;
export const busCodeLength = () => CODE.bus.code.length / 2;
const TABLE_SLOTS = 8;
const EVENTS = {
  PSLT: { name: "ev_param_slot", site: 0x400dc02a, stock: "2f027264206f0008", table: 0,
          entry: "ev_param_slot", what: "param_set_slot_to_id -> the bus's ev_param_slot" },
};
const MACHINE_BOUNDS = [[0x400dc15d, 1, 4], [0x400dc19d, 1, 4], [0x400dc333, 1, 4],
                        [0x400dc359, 1, 4], [0x400dc37f, 1, 4], [0x400dd287, 1, 6]];
const COUNT_NAMES = { PARM: "parameter records", MACH: "machine types" };
const beN = (v, width) => Uint8Array.from({ length: width }, (_, i) => (v >>> (8 * (width - 1 - i))) & 0xff);

/** The chunk that subscribes HANDLER (a run-time address) to EVENT. */
export function subscribe(event, handler, order = 50) {
  if (!(event in EVENTS)) throw new ModError(`the bus has no event ${event}`);
  return [EVNT, concat([Uint8Array.from(event, (c) => c.charCodeAt(0)), be32(order), be32(handler)])];
}

/** The chunk that adds AMOUNT to COUNT. */
export function contribute(count, amount) {
  if (!(count in COUNT_NAMES)) throw new ModError(`the bus has no count ${count}`);
  return [ADDS, concat([Uint8Array.from(count, (c) => c.charCodeAt(0)), be32(amount)])];
}

const records = (chunks, cid, size) => {
  const out = [];
  for (const [c, data] of chunks) {
    if (c !== cid) continue;
    for (let at = 0; at < data.length; at += size) out.push(data.subarray(at, at + size));
  }
  return out;
};

/** -> { count: amount }, refusing a count that two mods add to. */
export function totals(chunks) {
  const out = {};
  for (const r of records(chunks, ADDS, 8)) {
    const count = ascii(r, 0);
    if (count in out) {
      throw new ModError(`two mods add ${COUNT_NAMES[count] ?? count}; the platform takes one mod's for now`);
    }
    out[count] = u32(r, 4);
  }
  return out;
}

/** -> { event: [handler, ...] } in the order the dispatcher calls them. */
export function handlers(chunks) {
  const out = {};
  for (const r of records(chunks, EVNT, 12)) (out[ascii(r, 0)] ??= []).push([u32(r, 4), u32(r, 8)]);
  for (const e of Object.keys(out)) out[e] = out[e].sort((a, b) => a[0] - b[0] || a[1] - b[1]).map((s) => s[1]);
  return out;
}

const bounds = (count) => (count === "MACH" ? MACHINE_BOUNDS : CODE.counts[count]);
const hook = (event) => concat([hex("4ef9"), be32(CODE.bus.symbols[EVENTS[event].entry]), hex("4e71")]);

function detach(content, chunks) {
  for (const [count, amount] of Object.entries(totals(chunks))) {
    for (const [va, width, value] of bounds(count)) {
      write(content, chunks, va, beN(value + amount, width), beN(value, width), `the ${COUNT_NAMES[count]} count`);
    }
  }
  for (const event of Object.keys(handlers(chunks))) {
    write(content, chunks, EVENTS[event].site, hook(event), hex(EVENTS[event].stock), EVENTS[event].name);
  }
  return chunks.filter(([c, d]) => !(c === CODE_ID && unpackCode(d).load === BUS_VA));
}

function attach(content, chunks) {
  for (const [count, amount] of Object.entries(totals(chunks))) {
    for (const [va, width, value] of bounds(count)) {
      write(content, chunks, va, beN(value, width), beN(value + amount, width), `the ${COUNT_NAMES[count]} count`);
    }
  }
  const subs = handlers(chunks);
  if (Object.keys(subs).length === 0) return chunks;
  const image = hex(CODE.bus.code);
  for (const [event, found] of Object.entries(subs)) {
    if (found.length >= TABLE_SLOTS) {
      throw new ModError(`${found.length} mods subscribe to ${EVENTS[event].name}; the bus takes ${TABLE_SLOTS - 1}`);
    }
    found.forEach((h, k) => image.set(be32(h), EVENTS[event].table + 4 * k));
    write(content, chunks, EVENTS[event].site, hex(EVENTS[event].stock), hook(event), EVENTS[event].name);
  }
  return [...chunks, [CODE_ID, codeChunk(BUS_VA, image)]];
}

/** The bytes the bus owns: every mod on the platform declares them. */
export function busExtents() {
  const out = Object.values(EVENTS).map((e) => ({ section: SECTION, start: e.site - BASE,
    length: e.stock.length / 2, what: e.what, owner: ID }));
  for (const count of Object.keys(COUNT_NAMES)) {
    for (const [va, width] of bounds(count)) {
      out.push({ section: SECTION, start: va - BASE, length: width, what: `the ${COUNT_NAMES[count]} count`, owner: ID });
    }
  }
  return out;
}
