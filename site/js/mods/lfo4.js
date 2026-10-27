/**
 * A fourth LFO: a fourth page under `[MOD]` that behaves like LFO1-3.
 *
 * The browser half of `src/dnfw/mods/lfo4.py`, which carries the evidence and
 * the hardware result. Same steps, same order: split off any area the image
 * already carries, check and write every edit (through `platform.write`, so an
 * edit in a site another mod displaced lands on its copy), rebuild the
 * relocated parameter table from this image, and add LFO4's two CODE chunks to
 * the platform's area. The loader and its start-up call are the platform's.
 * `scripts/js_lfo4_check.mjs` fails if the bytes differ from the Python's, and
 * the Python's are checked byte for byte against the release build when
 * `scripts/gen_lfo4_code.py` packages it.
 *
 * **No stock table bytes ship.** The relocated table is this image's own 320
 * records followed by LFO4's ten, which are this image's LFO3 records with five
 * fields rewritten -- the port of `dnfw.patch.paramtable.records` and
 * `dnfw.patch.lfo4records.build`. So a mod applied earlier that edits the stock
 * table (fxmod, moddest) is carried into the copy, **provided it is applied
 * first**: this one goes last.
 *
 * The 53 bounds of the table are the hook bus's parameter count: LFO4 adds its
 * ten records (`platform.contribute`), the platform writes the bounds, and LFO4
 * records where its four entry hooks replay their stock bytes
 * (`platform.displace`), so the platform's machine count reaches the LOAD bound
 * its hook at 0x400dd282 moved.
 */

import { CODE } from "./lfo4-code.js";
import * as platform from "./platform.js";

export const ID = "lfo4";
export const NAME = "A fourth LFO";
export const SECTION = 3;
const BASE = 0x40000400;

// dnfw.patch.paramtable
const TABLE = 0x401f7fc8, RECORD = 60, COUNT = 320;
// dnfw.patch.lfo4records
const LFO3_FIRST = 94, GROUP_SIZE = 10, SLOT0 = 101;
const SLOT = 12, NRPN = 36, UNIQUE = 40, FLAGS = 44, PAGE_NAME = 52;
// The formatter and unit words that end a record: the first 8 bytes of the next
// one in dnfw's view (dnfw.patch.lfo4records.TAIL, issue #293).
export const TAIL = 8;
// The page name after the table, in the packaged chunk.
const PAGE_NAME_BYTES = [0x4c, 0x46, 0x4f, 0x34, 0, 0, 0, 0];
const UNSET = 0xffffffff;
const DEST_POSITION = 3, DEST_FLAGS = 0x00008000;
const SLOTS = [0, 1, 2, 3, 4, 5, 5, 6, 7, 1];

export class ModError extends Error {}

const hex = (s) => Uint8Array.from(s.match(/../g) ?? [], (b) => parseInt(b, 16));
/** Python's `f"{n:,}"`, whatever the browser's locale. */
const grouped = (n) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
const u32 = (d, at) => ((d[at] << 24) >>> 0) + (d[at + 1] << 16) + (d[at + 2] << 8) + d[at + 3];
const put32 = (d, at, v) => {
  d[at] = v >>> 24; d[at + 1] = (v >>> 16) & 0xff; d[at + 2] = (v >>> 8) & 0xff; d[at + 3] = v & 0xff;
};

// The entry hooks whose stubs replay the displaced stock bytes unchanged, then jump back.
const HOOKS = [[0x40134490, 8], [0x401344d8, 8], [0x400dd282, 6], [0x400dd724, 8]];
// The area beyond the packaged blob: a directory entry and the data of each DISP and the ADDS chunk.
const AREA_EXTRA = 12 * (HOOKS.length + 1) + 12 * HOOKS.length + 8;

/** An edit the platform makes: the start-up call, the loader in its cave, or a bound of the bus's count. */
const platformOwned = (e) => {
  const lo = e.va - BASE, hi = lo + e.new.length / 2;
  return platform.loaderExtents().some((x) => x.start < hi && lo < x.start + x.length)
    || platform.busExtents().some((x) => x.start <= lo && hi <= x.start + x.length);
};
// Three stock readers of the per-track LFO arrays that LFO4 widens from 120 bytes a
// track to 160, left stepping by 120 by the packaged build (dnfw.mods.lfo4.STRIDE_EDITS,
// issues #295, #294; fixed in 1.0.3).
export const STRIDE_EDITS = [
  { va: 0x40027832, stock: "43e90078", new: "43e900a0" },
  { va: 0x40027836, stock: "1169ff830001", new: "1169ff5b0001" },
  { va: 0x4002783c, stock: "1169ff860002", new: "1169ff5e0002" },
  { va: 0x4012ab88, stock: "068400000078", new: "0684000000a0" },
  { va: 0x4012b09e, stock: "e78b", new: "eb8b" },
  { va: 0x4012b0ca, stock: "9283", new: "d283" },
];
const OWN = CODE.edits.filter((e) => !platformOwned(e)).concat(STRIDE_EDITS);

export const EDITS = OWN.length;
export const EDITED_BYTES = OWN.reduce((n, e) => n + e.new.length / 2, 0);
export const APPENDED = CODE.blob.length / 2;
export const RECORDS = CODE.table_records;

export function extents() {
  const hooks = new Set(HOOKS.map(([site]) => site));
  return [
    ...OWN.map((e) => ({ section: SECTION, start: e.va - BASE, length: e.new.length / 2,
                         what: "LFO4 edit", displaced: hooks.has(e.va) })),
    ...platform.extents(APPENDED + TAIL + AREA_EXTRA),
  ];
}

/** A DISP chunk per entry hook: where its stub replays the stock bytes. */
function displacedCopies(stock, chunks) {
  return HOOKS.map(([site, n]) => {
    const replay = new Uint8Array(n + 6);
    replay.set(stock.subarray(site - BASE, site - BASE + n));
    replay.set([0x4e, 0xf9, (site + n) >>> 24, ((site + n) >>> 16) & 0xff, ((site + n) >>> 8) & 0xff, (site + n) & 0xff], n);
    const found = [];
    for (const [cid, data] of chunks) {
      if (cid !== platform.CODE) continue;
      const c = platform.unpackCode(data);
      for (let at = 0; at + replay.length <= c.image.length; at += 2) {
        if (replay.every((b, i) => c.image[at + i] === b)) found.push(c.load + at);
      }
    }
    if (found.length !== 1) {
      throw new ModError(`lfo4_code.json is damaged: the hook at 0x${site.toString(16).padStart(8, "0")} `
        + `replays its stock bytes ${found.length} times`);
    }
    return platform.displace(site, n, found[0]);
  });
}

/** `want` values of field +40 inside the range the table uses and claimed by none. */
export function freeUniqueIds(content, want = GROUP_SIZE) {
  const used = new Set();
  for (let i = 0; i < COUNT; i++) used.add(u32(content, TABLE - BASE + RECORD * i + UNIQUE));
  used.delete(UNSET);
  let lo = Infinity, hi = -Infinity;
  for (const v of used) { if (v < lo) lo = v; if (v > hi) hi = v; }
  const gaps = [];
  for (let v = lo; v < hi; v++) if (!used.has(v)) gaps.push(v);
  if (gaps.length < want) {
    throw new ModError(`only ${gaps.length} unused id(s) inside the table's range, ${want} wanted`);
  }
  return gaps.slice(0, want);
}

/** LFO4's ten records: LFO3's, with the slot, NRPN, id, flags and page name rewritten,
 * the first one starting with the last stock record's tail, then LFO3's last tail. */
export function lfo4Records(content, pageNameVa) {
  const ids = freeUniqueIds(content);
  const out = new Uint8Array(RECORD * GROUP_SIZE + TAIL);
  for (let k = 0; k < GROUP_SIZE; k++) {
    const at = TABLE - BASE + RECORD * (LFO3_FIRST + k);
    const record = content.slice(at, at + RECORD);
    if (k === 0) {
      const end = TABLE - BASE + RECORD * COUNT;
      record.set(content.subarray(end, end + TAIL), 0);
    }
    put32(record, SLOT, SLOT0 + SLOTS[k]);
    put32(record, NRPN, UNSET);
    put32(record, UNIQUE, ids[k]);
    put32(record, FLAGS, k === DEST_POSITION ? DEST_FLAGS : 0);
    put32(record, PAGE_NAME, pageNameVa);
    out.set(record, RECORD * k);
  }
  const last = TABLE - BASE + RECORD * (LFO3_FIRST + GROUP_SIZE);
  out.set(content.subarray(last, last + TAIL), RECORD * GROUP_SIZE);
  return out;
}

/** The relocated table, from this image: its 320 records, LFO4's ten and their tail. */
export function table(content) {
  const nameVa = CODE.table_va + RECORD * CODE.table_records + TAIL;
  const stock = content.subarray(TABLE - BASE, TABLE - BASE + RECORD * COUNT);
  const out = new Uint8Array(RECORD * (COUNT + GROUP_SIZE) + TAIL);
  out.set(stock);
  out.set(lfo4Records(content, nameVa), stock.length);
  return out;
}

/** Stock-guarded edits, then LFO4's chunks, with the table filled in, in the platform's area. */
export function compose(content) {
  const [base, others] = platform.split(content);
  const out = base.slice();
  for (const e of OWN) platform.write(out, others, e.va, hex(e.stock), hex(e.new));

  const records = table(base);
  const blank = RECORD * CODE.table_records;
  const chunks = platform.parseArea(hex(CODE.blob)).map(([cid, data]) => {
    if (cid !== platform.CODE) return [cid, data];
    const c = platform.unpackCode(data);
    if (c.load !== CODE.table_va) return [cid, data];
    // The packaged chunk is the blank table, then the page name. The table is TAIL
    // bytes longer than that blank, so the name moves on.
    const name = c.image.subarray(blank);
    if (c.image.subarray(0, blank).some((b) => b !== 0) || name.length !== PAGE_NAME_BYTES.length
        || PAGE_NAME_BYTES.some((b, i) => name[i] !== b)) {
      throw new ModError("lfo4_code.json is damaged: the table chunk is not a blank table and its name");
    }
    const image = new Uint8Array(records.length + name.length);
    image.set(records);
    image.set(name, records.length);
    return [cid, platform.codeChunk(c.load, image, c.bss, c.init)];
  });
  return platform.join(out, [...others, ...chunks, ...displacedCopies(base, chunks),
                             platform.contribute("PARM", CODE.table_records - COUNT)]);
}

/** Throw unless this image is one the mod applies to; -> MAIN OS. */
export function check(firmware) {
  const section = firmware.container.find(SECTION);
  if (section === null) throw new ModError("image has no MAIN OS section");
  const original = section.unpack();
  if (original === null) throw new ModError("MAIN OS did not depack");
  compose(original);                 // every refusal, before anything is offered
  return original;
}

/** -> `{ content, notes }`, the new section 3. */
export function apply(firmware) {
  const original = check(firmware);
  const content = compose(original);
  return {
    content,
    notes: [`${EDITS} edits, ${grouped(APPENDED)} B of CODE chunks in the platform's area; `
            + `the parameter table rebuilt from this image; MAIN OS ${grouped(content.length)} B`],
  };
}
