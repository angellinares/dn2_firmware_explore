/**
 * The /modinfo record (docs/for-dnx-modinfo.md), written the way `dnfw mods apply` writes it
 * (src/dnfw/mods/modinfo.py, fill), so a build made here passes DNX's check.
 *
 * Waverider's chunk carries the record with its build part unfilled: the marker at 24 and a
 * zero image id and hash. `fill` writes the OS, the tag, the commit and the mods list, then the
 * image id (xxHash32 of the whole MAIN OS with the id and the hash zeroed), then the hash
 * (xxHash32 of the record's first `bytes - 4` bytes, seed 0). Without a record, the content is
 * returned unchanged. The record is 256 bytes (11 mods) up to Waverider 0.3.7, and 512 bytes
 * (26 mods: 11 at 72, then 15 at 256) after it. Every reader takes the length from byte 6.
 */

import { indexOf } from "./bytes.js";
import { SITE_BUILD } from "./build.js";

const MAGIC = [0x44, 0x4e, 0x4d, 0x49, 0, 1];           // "DNMI", version 1; then the length
const SIZES = [256, 512];
const BYTES = 256;                                       // the smallest record
const MARKER = new TextEncoder().encode("MODINFO-UNFILLED");
const MARKER_AT = 24;
const MOD_AT = 72, MOD_BYTES = 16, MOD_END = 248, MORE_AT = 256;

/** -> where each mod sits in a record of SIZE bytes: `mod_slots` in src/dnfw/mods/modinfo.py. */
export function modSlots(size) {
  const out = [];
  for (let at = MOD_AT; at + MOD_BYTES <= MOD_END; at += MOD_BYTES) out.push(at);
  for (let at = MORE_AT; at + MOD_BYTES <= size - 4; at += MOD_BYTES) out.push(at);
  return out;
}

/** The most mods a record from this code's Waverider chunk holds (26). */
export const MAX_MODS = modSlots(SIZES[SIZES.length - 1]).length;

export class ModInfoError extends Error {}

/** xxHash32 of BYTES (a Uint8Array) with SEED, as the firmware's 0x4014be0e computes it. */
export function xxh32(bytes, seed = 0) {
  const P1 = 0x9e3779b1, P2 = 0x85ebca77, P3 = 0xc2b2ae3d, P4 = 0x27d4eb2f, P5 = 0x165667b1;
  const rotl = (x, r) => (x << r) | (x >>> (32 - r));
  const le = (i) => bytes[i] | bytes[i + 1] << 8 | bytes[i + 2] << 16 | bytes[i + 3] << 24;
  const round = (acc, v) => Math.imul(rotl((acc + Math.imul(v, P2)) | 0, 13), P1);
  const n = bytes.length;
  let i = 0, h;
  if (n >= 16) {
    let v1 = (seed + P1 + P2) | 0, v2 = (seed + P2) | 0, v3 = seed | 0, v4 = (seed - P1) | 0;
    for (; i + 16 <= n; i += 16) {
      v1 = round(v1, le(i)); v2 = round(v2, le(i + 4)); v3 = round(v3, le(i + 8)); v4 = round(v4, le(i + 12));
    }
    h = (rotl(v1, 1) + rotl(v2, 7) + rotl(v3, 12) + rotl(v4, 18)) | 0;
  } else {
    h = (seed + P5) | 0;
  }
  h = (h + n) | 0;
  for (; i + 4 <= n; i += 4) h = Math.imul(rotl((h + Math.imul(le(i), P3)) | 0, 17), P4);
  for (; i < n; i++) h = Math.imul(rotl((h + Math.imul(bytes[i], P5)) | 0, 11), P1);
  h = Math.imul(h ^ (h >>> 15), P2);
  h = Math.imul(h ^ (h >>> 13), P3);
  return (h ^ (h >>> 16)) >>> 0;
}

const u32 = (b, at) => (b[at] << 24 | b[at + 1] << 16 | b[at + 2] << 8 | b[at + 3]) >>> 0;
const put32 = (b, at, v) => b.set([v >>> 24, (v >>> 16) & 255, (v >>> 8) & 255, v & 255], at);

/** -> where the record starts in CONTENT (MAIN OS), or -1 when it carries none. */
export function locate(content) {
  const found = [];
  for (const size of SIZES) {
    const head = [...MAGIC, size >> 8, size & 255];
    for (let at = indexOf(content, head); at >= 0; at = indexOf(content, head, at + 1)) found.push(at);
  }
  if (found.length > 1) throw new ModInfoError("the /modinfo record appears twice");
  return found.length ? found[0] : -1;
}

/** -> the length the record at START says it has (byte 6). */
export function sizeAt(content, start) {
  return content[start + 6] << 8 | content[start + 7];
}

/** -> the record at START, at its own length. */
export function record(content, start) {
  return content.subarray(start, start + sizeAt(content, start));
}

/** -> where a record starts in CONTENT, or null: `find` in src/dnfw/mods/modinfo.py. */
export function find(content) {
  const at = locate(content);
  return at < 0 ? null : at;
}

/**
 * A record (256 or 512 bytes) -> { ok, filled, imageId, os, tag, commit, mods }: the fields the
 * Check page reads, as `parse` in src/dnfw/mods/modinfo.py reads them. `ok` is the magic, the
 * version, the size and the hash over everything before it.
 */
export function parse(rec) {
  const size = rec[6] << 8 | rec[7];
  const version = rec[4] << 8 | rec[5];
  const sizeOk = size >= BYTES && size <= rec.length;
  const end = sizeOk ? size : Math.min(Math.max(size, 4), rec.length);
  const magicOk = MAGIC.slice(0, 4).every((b, i) => rec[i] === b);
  const str = (a, b) => new TextDecoder("ascii").decode(rec.subarray(a, b)).replace(/\0.*$/s, "");
  const mods = modSlots(sizeOk ? size : BYTES).slice(0, rec[68]).map((at) => [str(at, at + 12), u32(rec, at + 12)]);
  return {
    ok: magicOk && version >= 1 && sizeOk && u32(rec, end - 4) === xxh32(rec.subarray(0, end - 4)),
    filled: indexOf(rec.subarray(MARKER_AT, MARKER_AT + MARKER.length), MARKER) !== 0,
    imageId: u32(rec, 20), os: str(24, 32), tag: str(32, 56), commit: str(56, 68), mods,
  };
}

export { BYTES };

/** The record's mods list, when it is filled and checks out; else []. */
function listed(rec) {
  if (indexOf(rec.subarray(MARKER_AT, MARKER_AT + MARKER.length), MARKER) === 0) return [];
  const n = rec.length;
  if (u32(rec, n - 4) !== xxh32(rec.subarray(0, n - 4))) return [];
  return modSlots(n).slice(0, rec[68]).map((at) => [
    new TextDecoder("ascii").decode(rec.subarray(at, at + 12)).replace(/\0.*$/s, ""), u32(rec, at + 12)]);
}

/** NUL-padded ASCII, at most N - 1 characters, as the Python `_text`. */
function text(s, n) {
  const out = new Uint8Array(n);
  out.set([...s.slice(0, n - 1)].map((c) => (c.charCodeAt(0) < 128 ? c.charCodeAt(0) : 63)));
  return out;
}

/**
 * -> CONTENT (the new MAIN OS) with its record filled, MOD added to the mods list. The list
 * keeps what an earlier fill wrote; a record still unfilled lists Waverider, whose chunk
 * brought it. A mod applied here carries no code hash (0). Unchanged without a record.
 */
export function fill(content, mod = null, os = "1.11") {
  const start = locate(content);
  if (start < 0) return content;
  const out = content.slice();
  const size = sizeAt(out, start);
  const rec = out.subarray(start, start + size);
  const slots = modSlots(size);
  const mods = listed(rec);
  for (const id of ["waverider", mod]) {
    if (id && !mods.some(([m]) => m === id)) mods.push([id, 0]);
  }
  if (mods.length > slots.length) throw new ModInfoError(`${mods.length} mods; the record holds ${slots.length}`);
  rec.fill(0, 20, 24);
  rec.set(text(os, 8), 24);
  rec.set(text(`web-${mods.map(([m]) => m).join("-")}`, 24), 32);
  rec.set(text(SITE_BUILD, 12), 56);          // web-<the site's commit>, web-local in a checkout
  rec.set([mods.length, 0, 0, 0], 68);
  slots.forEach((at) => rec.fill(0, at, at + MOD_BYTES));
  mods.forEach(([id, code], k) => {
    rec.set(text(id, 12), slots[k]);
    put32(rec, slots[k] + 12, code);
  });
  rec.fill(0, 252, 256);                                // 256: the hash, 512: reserved (248..251: the playable bounds)
  rec.fill(0, size - 4, size);                          // the hash
  put32(rec, 20, xxh32(out));                           // the id and the hash still zero
  put32(rec, size - 4, xxh32(rec.subarray(0, size - 4)));
  return out;
}
