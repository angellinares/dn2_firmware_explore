/**
 * Binary PGM (P5), the picture format `dnfw mods apply --boot-image` reads.
 *
 * DOM-free, so the boot pages and the build harness (scripts/js_build_check.mjs) read the
 * same bytes the same way.
 */

/** A binary PGM -> { w, h, data } with 8-bit luminance at its own size. */
export function parsePgm(bytes) {
  const fields = [];
  let at = 0;
  const space = (b) => b === 0x20 || b === 0x0a || b === 0x0d || b === 0x09;
  while (fields.length < 4) {
    while (space(bytes[at])) at++;
    if (bytes[at] === 0x23) { while (bytes[at] !== 0x0a) at++; continue; }   // comment
    let s = "";
    while (!space(bytes[at])) s += String.fromCharCode(bytes[at++]);
    fields.push(s);
  }
  at++;
  const [magic, w, h] = [fields[0], Number(fields[1]), Number(fields[2])];
  if (magic !== "P5") throw new Error("only binary PGM (P5) is read");
  return { w, h, data: bytes.subarray(at, at + w * h) };
}

/** LIT(x, y) -> a W x H binary PGM, lit pixels 255 and the rest 0. */
export function toPgm(lit, w, h) {
  const head = new TextEncoder().encode(`P5\n${w} ${h}\n255\n`);
  const out = new Uint8Array(head.length + w * h);
  out.set(head);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) out[head.length + y * w + x] = lit(x, y) ? 255 : 0;
  }
  return out;
}
