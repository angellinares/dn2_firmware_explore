/**
 * SETTINGS > SYSTEM > MODS: the mods a build holds, and their versions, on the instrument.
 *
 * The browser half of `src/dnfw/mods/modspage.py`. Not a mod a user picks: a page's build
 * (`withModsPage`) adds the page to MAIN OS with the mod it applies, as
 * `dnfw mods apply` adds it after its mods. An image that has the page keeps its hook and gets the new rows.
 * `scripts/js_build_check.mjs` and test_js_build_matches_cli.py fail if the bytes differ from the
 * Python's, the build's name and commit rows apart.
 */

import { SITE_COMMIT } from "../build.js";
import { replacement } from "../firmware.js";
import { CODE } from "./modspage-code.js";
import * as platform from "./platform.js";
import { VERSIONS } from "./versions.js";

export const ID = "modspage";
export const SECTION = 3;
const BASE = 0x40000400;
const CODE_VA = CODE.code.va;
export const ROW = 32, NAME_BYTES = 20, VALUE_BYTES = 12, NAME_MAX = 12, ROWS_MAX = 64;
export const MENU_NAMES = CODE.names;
export const OS_ROW = "OS";
export const INFO_ROWS = 3;      // the general rows at the top: the OS, the build's name, the commit
export const WEB_TAG = "WEB BUILD";

export class ModError extends Error {}

const hex = (s) => Uint8Array.from(s.match(/../g) ?? [], (b) => parseInt(b, 16));
const toHex = (a) => Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");
const BLOB = hex(CODE.code.blob);

/** S as a row shows it: upper case, the characters the menu's font draws, MOST at most. */
export function text(s, most) {
  return s.toUpperCase().replace(/[^A-Z0-9 .+\-_/]/g, " ").slice(0, most).trimEnd();
}

/** The general rows, before the mods: the OS, the build's name, the commit. Always INFO_ROWS. */
export function info(os, tag, commit) {
  const short = (commit || "unknown").slice(0, 7) + (commit.endsWith("+") ? "+" : "");
  return [[OS_ROW, text(os, VALUE_BYTES - 1)],
          [text(tag, NAME_BYTES - 1) || "NO NAME", ""],
          [text(`COMMIT ${short}`, NAME_BYTES - 1), ""]];
}

/** The page's rows for a build of MOD_IDS on OS, named TAG, made at COMMIT. */
export function rows(modIds, os, tag, commit) {
  const out = modIds.map((id) => [text(MENU_NAMES[id] ?? id, NAME_MAX), text(VERSIONS[id] ?? "", VALUE_BYTES - 1)]);
  return [...info(os, tag, commit), ...out];
}

/** ROWS as the code reads them: a count, then each name in 20 bytes and value in 12. */
export function table(list) {
  const out = new Uint8Array(4 + ROW * list.length);
  new DataView(out.buffer).setUint32(0, list.length);
  list.forEach(([name, value], k) => {
    if (name.length >= NAME_BYTES || value.length >= VALUE_BYTES || (name + value).includes("%")
        || /[^\x20-\x7e]/.test(name + value)) {
      throw new ModError(`the MODS page cannot show the row ${JSON.stringify(name)} ${JSON.stringify(value)}`);
    }
    out.set(Array.from(name, (c) => c.charCodeAt(0)), 4 + ROW * k);
    out.set(Array.from(value, (c) => c.charCodeAt(0)), 4 + ROW * k + NAME_BYTES);
  });
  return out;
}

/** The rows of a table. */
export function parse(data) {
  const count = new DataView(data.buffer, data.byteOffset).getUint32(0);
  const cut = (b) => String.fromCharCode(...b.subarray(0, Math.max(0, b.indexOf(0))));
  return Array.from({ length: count }, (_, k) => {
    const at = 4 + ROW * k;
    return [cut(data.subarray(at, at + NAME_BYTES)), cut(data.subarray(at + NAME_BYTES, at + ROW))];
  });
}

/** NEW's general rows, then OLD's mods, each with NEW's version, then NEW's mods that OLD lacks. */
export function merge(old, fresh) {
  const left = new Map(fresh.slice(INFO_ROWS));
  const out = fresh.slice(0, INFO_ROWS);
  for (const [n, v] of old.slice(INFO_ROWS)) {
    out.push([n, left.has(n) ? left.get(n) : v]);
    left.delete(n);
  }
  out.push(...left.entries());
  if (out.length > ROWS_MAX) throw new ModError(`the MODS page holds ${ROWS_MAX} rows, and this build has ${out.length}`);
  return out;
}

const mine = (chunks) => chunks.find(([id, data]) => id === platform.CODE && platform.unpackCode(data).load === CODE_VA);

/** The rows of the page a MAIN OS already holds: [] for an image with no page. */
export function existing(content) {
  const [, others] = platform.split(content);
  const chunk = mine(others);
  return chunk ? parse(platform.unpackCode(chunk[1]).image.subarray(BLOB.length)) : [];
}

/** CONTENT (a MAIN OS) with the page and LIST. An image that has the page keeps its hook. */
export function apply(content, list) {
  const [original, others] = platform.split(content);
  const at = (va, n) => toHex(original.subarray(va - BASE, va - BASE + n));
  const chunk = mine(others);
  const edited = original.slice();
  if (!chunk) {
    for (const g of CODE.guards) {
      if (at(g.va, g.bytes.length / 2) !== g.bytes) {
        throw new ModError(`0x${g.va.toString(16).padStart(8, "0")} is not stock; this mod is for unmodified Digitone II 1.11`);
      }
    }
    for (const e of CODE.edits) {
      if (at(e.va, e.stock.length / 2) !== e.stock) {
        throw new ModError(`0x${e.va.toString(16).padStart(8, "0")} is not stock; this mod is for unmodified `
          + "Digitone II 1.11, or another mod already wrote there");
      }
    }
    for (const e of CODE.edits) edited.set(hex(e.new), e.va - BASE);
  } else {
    for (const e of CODE.edits) {
      if (at(e.va, e.new.length / 2) !== e.new) {
        throw new ModError(`0x${e.va.toString(16).padStart(8, "0")} does not hold the MODS page's hook, and the image has its chunk`);
      }
    }
  }
  const rest = others.filter((c) => c !== chunk);
  const data = table(list);
  const blob = new Uint8Array(BLOB.length + data.length);
  blob.set(BLOB);
  blob.set(data, BLOB.length);
  return platform.join(edited, [...rest, [platform.CODE, platform.codeChunk(CODE_VA, blob)]]);
}

/** CONTENT (a MAIN OS) with no page: its chunk gone and its hook's site stock again. Unchanged without one. */
export function without(content) {
  if (content.length <= platform.STOCK_LENGTH) return content;
  const [original, others] = platform.split(content);
  const chunk = mine(others);
  if (!chunk) return content;
  for (const e of CODE.edits) original.set(hex(e.stock), e.va - BASE);
  const rest = others.filter((c) => c !== chunk);
  return rest.length ? platform.join(original, rest) : original;
}

/** CONTENT (the new MAIN OS a page built) with the page, MOD added to its rows. */
export function update(content, mod, os = "1.11") {
  return apply(content, merge(existing(content), rows([mod], os, WEB_TAG, SITE_COMMIT)));
}

/**
 * A page's REPLACEMENTS (Map of section id -> Section) with MOD's row on the MODS page: MAIN OS
 * from the map, or the firmware's own when the mod leaves it alone, built again with the page.
 */
export function withModsPage(firmware, replacements, mod) {
  const main = (replacements.get(3) ?? firmware.container.find(3)).unpack();
  return new Map([...replacements, [3, replacement(firmware, 3, update(main, mod), mod)]]);
}
