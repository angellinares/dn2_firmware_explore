/**
 * The Parameter slides page: which mod, and what the user sees of it.
 * Loading, verifying, building and the download live in `shell.js`.
 *
 * A new selection withdraws the previous one's offer first, and its firmware and file name are
 * kept together only once it has passed every check, so Build never pairs one file's bytes with
 * another's name. Only the newest selection is kept when two are read at once.
 */

import { $, buildAndOffer, openFirmware, status, wireDrop } from "./shell.js";
import { replacement } from "../firmware.js";
import { apply, extents } from "../mods/pslide.js";

let state = { firmware: null, filename: "firmware.syx" };
let opened = 0;

async function ready(firmware, filename) {
  // Applying is also the check that this image is one the mod was measured
  // against: every guard is read, and it throws rather than writing.
  apply(firmware);
  state = { firmware, filename };
  const found = extents();
  const bytes = found.reduce((n, e) => n + e.length, 0);
  $("writes").textContent = `${found.length} places in section 3, ${bytes} bytes, with the code in the platform's appended area`;
  for (const id of ["step2", "step3", "bar"]) $(id).classList.remove("hidden");
  status("Loaded. Ready to build.");
}

async function buildImage() {
  const { content, notes } = apply(state.firmware);
  await buildAndOffer(
    state.firmware,
    new Map([[3, replacement(state.firmware, 3, content, "pslide")]]),
    { filename: state.filename, mod: "pslide", suffix: "pslide", note: notes[0] });
}

function open(file) {
  const mine = ++opened;
  state = { firmware: null, filename: "firmware.syx" };
  for (const id of ["step2", "step3", "bar"]) $(id).classList.add("hidden");
  $("buildVerdict").innerHTML = "";
  return openFirmware(file, { onReady: (firmware) => (mine === opened ? ready(firmware, file.name) : undefined) });
}

wireDrop($("drop"), open);
$("syx").addEventListener("change", (e) => {
  if (e.target.files?.[0]) open(e.target.files[0]);
});
$("buildBtn").addEventListener("click", buildImage);
$("resetBtn").addEventListener("click", () => location.reload());
