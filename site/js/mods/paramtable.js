/**
 * Is the parameter table still where stock keeps it?
 *
 * The browser half of `dnfw.patch.paramtable.base_sites`. lfo4 copies the
 * 60-byte parameter table into the appended area and repoints its accessors. A
 * mod that opens records in the stock table must therefore come first: applied
 * after lfo4, its edits find their stock bytes and land on a table nothing
 * reads. fxmod and lfowaves ask this before they write.
 */

const BASE = 0x40000400;
const TABLE = 0x401f7fc8, RECORD = 60;
const STOCK_END = 0x4030b980;
const EXPECTED_BASES = [[8, 53], [16, 1], [40, 2]];

/**
 * -> null when the accessors still carry the stock table's base, else why not.
 * STRICT (fxmod's check, `base_sites`): exactly stock's count. Otherwise
 * (`paramtable.moved`): at least stock's count, since lfo4 repoints them all and a
 * mod's own code may hold one more (fxmod's cave helper does).
 */
export function tableMoved(content, id, strict = false) {
  const end = Math.max(0, Math.min(content.length, STOCK_END - BASE));
  for (const [bias, expected] of EXPECTED_BASES) {
    const literal = (TABLE - RECORD + bias) >>> 0;
    const want = [literal >>> 24, (literal >>> 16) & 0xff, (literal >>> 8) & 0xff, literal & 0xff];
    let found = 0;
    for (let i = 0; i + 4 <= end; i += 2) {
      if (content[i] === want[0] && content[i + 1] === want[1]
          && content[i + 2] === want[2] && content[i + 3] === want[3]) found++;
    }
    if (strict ? found !== expected : found < expected) {
      return `the parameter table has been moved (expected ${expected} site(s) holding `
        + `0x${literal.toString(16).padStart(8, "0")} (table - ${RECORD} + ${bias}), found ${found}); `
        + `lfo4 does that, and ${id} ${id === "fxmod" ? "opens" : "edits"} records in the stock table, `
        + `which nothing reads once it has moved: apply ${id} first, then lfo4`;
    }
  }
  return null;
}
