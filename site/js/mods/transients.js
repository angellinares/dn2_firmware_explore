/**
 * Replace the Digitone II's FM drum transient bank with your own samples.
 *
 * The browser half of `src/dnfw/mods/transients.py`, which holds the evidence. In
 * short: the samples are 16-bit mono at 48 kHz in DDR 0x8045b0c8..0x804abe88, and the
 * DSP plays them through a table of 32 entries at 0x28266d08 (start address and length
 * in samples, little-endian), one per TRAN step: TRAN 4 x k plays entry k. The factory
 * entries are 50, 100 or 150 ms, end to end (STOCK_LENGTHS).
 *
 * Slot k is table entry k. Two layouts, chosen per build:
 * - factory sizes (the default): the table stays, and each slot keeps its factory length;
 * - equal slots: the table is rewritten to 32 entries of EQUAL_SAMPLES (107.6 ms) each,
 *   packed into the bank memory's two data blocks around the 36-byte fill block, each
 *   start on an 8-byte boundary.
 * A slot with no replacement keeps its current sound, fitted to its length. An image whose
 * table is neither stock's nor the equal layout is refused.
 */

import { readSpan, spans } from "../bootstream.js";
import { replacement } from "../firmware.js";

export const ID = "transients";
export const NAME = "FM drum transients";
export const SECTION = 7;

// The bank's start comes from the table (`bankStart`): 1.11's is 0x8045b0c8, 1.10E's 0x8045b0a8.
const TABLE_ADDR = 0x28266d08;
export const COUNT = 32;
const TABLE_BYTES = COUNT * 8;
const STOCK_LENGTHS = [2400, 7200, 2400, 2400, 7200, 4800, 7200, 4800, 7200, 7200, 7200, 7200, 7200,
  ...Array(19).fill(4800)];
export const RATE = 48000;
const ALIGN = 8;
export const EQUAL_SAMPLES = 5164;
const BANK_BYTES = 2 * STOCK_LENGTHS.reduce((a, n) => a + n, 0);   // 331,200

/** Each slot's length in samples: the factory sizes, or EQUAL_SAMPLES for all. */
export function lengths(equal = false) {
  return equal ? Array(COUNT).fill(EQUAL_SAMPLES) : [...STOCK_LENGTHS];
}

function content(firmware) {
  const section = firmware.container.find(SECTION);
  if (section === null) throw new Error(`image has no section ${SECTION}`);
  return section.unpack() ?? section.rawPayload;
}

/** The 32 start addresses of the equal layout over the bank memory's data pieces. */
export function layout(data) {
  const runs = [];
  let at = bankStart(data);
  for (const piece of spans(data, at, BANK_BYTES)) {
    if (piece.at !== null) runs.push([at, at + piece.length]);
    at += piece.length;
  }
  const starts = [];
  for (const [lo, hi] of runs) {
    let a = Math.ceil(lo / ALIGN) * ALIGN;
    while (starts.length < COUNT && a + 2 * EQUAL_SAMPLES <= hi) { starts.push(a); a += 2 * EQUAL_SAMPLES; }
  }
  if (starts.length < COUNT) {
    throw new Error(`the bank memory holds ${starts.length} entries of ${EQUAL_SAMPLES} samples, not ${COUNT}`);
  }
  return starts;
}

function packTable(starts, sizes) {
  const out = new Uint8Array(TABLE_BYTES);
  const view = new DataView(out.buffer);
  starts.forEach((a, k) => {
    view.setUint32(8 * k, a, true);
    view.setUint32(8 * k + 4, sizes[k], true);
  });
  return out;
}

/** The bank's first sample: entry 0's start, in the factory table and in the equal layout. */
function bankStart(data) {
  return new DataView(readSpan(data, TABLE_ADDR, 4).buffer).getUint32(0, true);
}

function stockStarts(start) {
  const starts = [];
  let at = start;
  for (const n of STOCK_LENGTHS) { starts.push(at); at += 2 * n; }
  return starts;
}

const stockTable = (start) => packTable(stockStarts(start), STOCK_LENGTHS);

const same = (a, b) => a.length === b.length && a.every((x, i) => x === b[i]);

/** The table as (start address, length in samples) pairs, if it is stock's or this layout. */
export function table(data) {
  const raw = readSpan(data, TABLE_ADDR, TABLE_BYTES);
  const start = bankStart(data);
  if (start % ALIGN || (!same(raw, stockTable(start)) && !same(raw, packTable(layout(data), lengths(true))))) {
    throw new Error("the transient table is neither the factory one nor this mod's equal layout");
  }
  const view = new DataView(raw.buffer);
  return Array.from({ length: COUNT }, (_, k) => [view.getUint32(8 * k, true), view.getUint32(8 * k + 4, true)]);
}

/** The 32 transients as the table plays them, each its own length of raw 16-bit LE PCM. */
export function extract(firmware) {
  const data = content(firmware);
  return table(data).map(([at, n]) => readSpan(data, at, 2 * n));
}

/** One entry's samples as Float32 in [-1, 1), for preview and drawing. */
export function toFloat(entry) {
  const view = new DataView(entry.buffer, entry.byteOffset, entry.byteLength);
  const out = new Float32Array(entry.byteLength / 2);
  for (let i = 0; i < out.length; i++) out[i] = view.getInt16(i * 2, true) / 32768;
  return out;
}

/**
 * Float samples -> LENGTH samples of 16-bit LE PCM, padded or truncated.
 *
 * Scaled by **32768 and clamped**, not by 32767, so that this is the exact inverse of
 * `toFloat`: a factory entry read out and written straight back comes home unchanged.
 */
export function toEntry(samples, length) {
  const out = new Uint8Array(2 * length);
  const view = new DataView(out.buffer);
  const n = Math.min(samples.length, length);
  for (let i = 0; i < n; i++) {
    const scaled = Math.round(samples[i] * 32768);
    view.setInt16(i * 2, Math.max(-32768, Math.min(32767, scaled)), true);
  }
  return out;
}

/** Raw 16-bit LE PCM of any length -> exactly LENGTH samples: cut with a 2 ms fade, or padded. */
export function fit(pcm, length) {
  const out = new Uint8Array(2 * length);
  out.set(pcm.subarray(0, 2 * length));
  if (pcm.length > 2 * length) {
    const view = new DataView(out.buffer);
    const fade = RATE / 500;
    for (let i = 0; i < fade; i++) {
      const at = (length - 1 - i) * 2;
      view.setInt16(at, Math.trunc((view.getInt16(at, true) * i) / fade), true);
    }
  }
  return out;
}

/** Write PAYLOAD at ADDRESS across its blocks, skipping fill pieces (the loader zeroes them).
 *  -> [offset, bytes] of each skipped part that was not all zeros. */
function writeSpan(data, address, payload) {
  let cursor = 0;
  const lost = [];
  for (const { at, length } of spans(data, address, payload.length)) {
    if (at === null) {
      if (payload.subarray(cursor, cursor + length).some((b) => b !== 0)) lost.push([cursor, length]);
    } else data.set(payload.subarray(cursor, cursor + length), at);
    cursor += length;
  }
  return lost;
}

/**
 * Which bytes this mod writes, so a set of mods can be checked for overlap before any
 * of them runs: the bank memory's data pieces and the table.
 */
export function extents(firmware) {
  const data = content(firmware);
  return [...spans(data, bankStart(data), BANK_BYTES), ...spans(data, TABLE_ADDR, TABLE_BYTES)]
    .filter((piece) => piece.at !== null)
    .map((piece) => ({
      section: SECTION,
      start: piece.at,
      length: piece.length,
      what: `transient bank and table, ${piece.length.toLocaleString()} bytes`,
    }));
}

/**
 * Replace slots with `entries`, a sparse Map of slot index (TRAN / 4) -> Uint8Array of that
 * slot's length (`lengths(equal)[k]` samples), in the factory sizes or (`equal`) equal slots.
 * A slot absent from the map keeps its current sound, fitted to its length.
 *
 * -> { section, notes, extents } with the Section ready for `firmware.build`.
 */
export function apply(firmware, entries, { equal = false } = {}) {
  const data = content(firmware).slice();       // a copy: the loaded image stays clean
  const sizes = lengths(equal);
  const pcm = extract(firmware).map((entry, k) => fit(entry, sizes[k]));
  const ms = (n) => `${((1000 * n) / RATE).toFixed(1)} ms`;
  const notes = [equal ? `layout: equal slots, ${ms(EQUAL_SAMPLES)} each` : "layout: factory sizes"];
  for (const [k, entry] of entries) {
    if (!Number.isInteger(k) || k < 0 || k >= COUNT) throw new Error(`slot ${k} is outside 0..${COUNT - 1}`);
    if (entry.length !== 2 * sizes[k]) {
      throw new Error(`slot ${k}: ${entry.length} bytes, expected exactly ${2 * sizes[k]}`);
    }
    pcm[k] = entry;
    notes.push(`${String(k).padStart(2, "0")} (TRAN ${4 * k}, ${ms(sizes[k])}) replaced`);
  }
  const starts = equal ? layout(data) : stockStarts(bankStart(data));
  starts.forEach((a, k) => {
    for (const [offset, n] of writeSpan(data, a, pcm[k])) {
      notes.push(`${String(k).padStart(2, "0")}: ${n / 2} samples at ${ms(offset / 2)} fall in a `
        + "boot-stream fill block and stay silent, as on stock");
    }
  });
  writeSpan(data, TABLE_ADDR, packTable(starts, sizes));
  return { section: replacement(firmware, SECTION, data, ID), notes, extents: extents(firmware) };
}
