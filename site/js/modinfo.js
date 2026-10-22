/**
 * The /modinfo record (docs/for-dnx-modinfo.md), written the way `dnfw mods apply` writes it
 * (src/dnfw/mods/modinfo.py, fill), so a build made here passes DNX's check.
 *
 * Waverider's chunk carries the record with its build part unfilled: the marker at 24 and a
 * zero image id and hash. `fill` writes the OS, the tag, the commit and the mods list, then the
 * image id (xxHash32 of the whole MAIN OS with the id and the hash zeroed), then the hash
 * (xxHash32 of the record's first 252 bytes, seed 0). Without a record, the content is
 * returned unchanged.
 */

import { indexOf } from "./bytes.js";
import { SITE_BUILD } from "./build.js";

const MAGIC = [0x44, 0x4e, 0x4d, 0x49, 0, 1, 1, 0];     // "DNMI", version 1, 256 bytes
const BYTES = 256;
const MARKER = new TextEncoder().encode("MODINFO-UNFILLED");
const MARKER_AT = 24;
const MOD_AT = 72, MOD_BYTES = 16, MAX_MODS = 11;

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
  const at = indexOf(content, MAGIC);
  if (at >= 0 && indexOf(content, MAGIC, at + 1) >= 0) throw new ModInfoError("the /modinfo record appears twice");
  return at;
}

/** The record's mods list, when it is filled and checks out; else []. */
function listed(rec) {
  if (indexOf(rec.subarray(MARKER_AT, MARKER_AT + MARKER.length), MARKER) === 0) return [];
  if (u32(rec, 252) !== xxh32(rec.subarray(0, 252))) return [];
  const mods = [];
  for (let k = 0; k < Math.min(rec[68], MAX_MODS); k++) {
    const at = MOD_AT + MOD_BYTES * k;
    const id = new TextDecoder("ascii").decode(rec.subarray(at, at + 12)).replace(/\0.*$/s, "");
    mods.push([id, u32(rec, at + 12)]);
  }
  return mods;
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
  const rec = out.subarray(start, start + BYTES);
  const mods = listed(rec);
  for (const id of ["waverider", mod]) {
    if (id && !mods.some(([m]) => m === id)) mods.push([id, 0]);
  }
  if (mods.length > MAX_MODS) throw new ModInfoError(`${mods.length} mods; the record holds ${MAX_MODS}`);
  rec.fill(0, 20, 24);
  rec.set(text(os, 8), 24);
  rec.set(text(`web-${mods.map(([m]) => m).join("-")}`, 24), 32);
  rec.set(text(SITE_BUILD, 12), 56);          // web-<the site's commit>, web-local in a checkout
  rec.set([mods.length, 0, 0, 0], 68);
  rec.fill(0, MOD_AT, 248);
  mods.forEach(([id, code], k) => {
    rec.set(text(id, 12), MOD_AT + MOD_BYTES * k);
    put32(rec, MOD_AT + MOD_BYTES * k + 12, code);
  });
  rec.fill(0, 252, 256);                                // 248..251 are the chunk's: the playable bounds
  put32(rec, 20, xxh32(out));                           // the id and the hash still zero
  put32(rec, 252, xxh32(rec.subarray(0, 252)));
  return out;
}
