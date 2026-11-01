/**
 * A picture for the boot screen: any image file fitted to the 128 x 64 screen as luminance, and
 * a one-bit image drawn on a canvas.
 *
 * Shared by the Boot Screen page (boot-page.js) and the Mod Composer (compose-page.js).
 */

import { H, W, pixelOf } from "../mods/bootscreen.js";
import { parsePgm, toPgm } from "../pgm.js";

/** The mark this site ships, and what the command line reads it from. */
export const CHIMERA = "art/chimera.pgm";

/** Any picture -> 128 x 64 luminance, fitted inside the screen on black. */
function fitToScreen(draw, sw, sh) {
  const canvas = document.createElement("canvas");
  canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  ctx.fillStyle = "#000"; ctx.fillRect(0, 0, W, H);
  const scale = Math.min(W / sw, H / sh);
  const dw = sw * scale, dh = sh * scale;
  draw(ctx, (W - dw) / 2, (H - dh) / 2, dw, dh);
  const px = ctx.getImageData(0, 0, W, H).data;
  const luma = new Uint8Array(W * H);
  for (let i = 0; i < W * H; i++) {
    luma[i] = Math.round(0.2126 * px[4 * i] + 0.7152 * px[4 * i + 1] + 0.0722 * px[4 * i + 2]);
  }
  return luma;
}

export function lumaFromPgm(pgm) {
  if (pgm.w === W && pgm.h === H) return Uint8Array.from(pgm.data);
  const src = document.createElement("canvas");
  src.width = pgm.w; src.height = pgm.h;
  const img = src.getContext("2d").createImageData(pgm.w, pgm.h);
  pgm.data.forEach((v, i) => img.data.set([v, v, v, 255], 4 * i));
  src.getContext("2d").putImageData(img, 0, 0);
  return fitToScreen((ctx, x, y, w, h) => ctx.drawImage(src, x, y, w, h), pgm.w, pgm.h);
}

/** An image FILE (any format the browser reads, or PGM) -> 128 x 64 luminance. */
export async function loadPicture(file) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  if (/\.pgm$/i.test(file.name)) return lumaFromPgm(parsePgm(bytes));
  const bitmap = await createImageBitmap(new Blob([bytes]));
  return fitToScreen((ctx, x, y, w, h) => ctx.drawImage(bitmap, x, y, w, h), bitmap.width, bitmap.height);
}

/** The chimera's luminance. */
export async function chimera() {
  const res = await fetch(CHIMERA);
  return lumaFromPgm(parsePgm(new Uint8Array(await res.arrayBuffer())));
}

/** `upright`: animation frames and tunnel marks are stored upside down (bootscreen.js). */
export function drawFrame(canvas, image, upright = false) {
  const ctx = canvas.getContext("2d");
  const out = ctx.createImageData(W, H);
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      const v = pixelOf(image, x, upright ? H - 1 - y : y) ? 255 : 0;
      out.data.set([v, v, v, 255], 4 * (y * W + x));
    }
  }
  ctx.putImageData(out, 0, 0);
}

/**
 * Save LIT as a 128 x 64 PGM named NAME, the file `dnfw mods apply --boot-image` reads. A picture,
 * not firmware, so it does not go through the notice before a download (notice.js).
 */
export function savePgm(lit, name) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([toPgm(lit, W, H)], { type: "image/x-portable-graymap" }));
  link.download = name;
  link.click();
}
