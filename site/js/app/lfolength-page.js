/**
 * The LFO ONE/HALF fix page: which mod, and what the user sees of it.
 * Loading, verifying, building and the download live in `shell.js`.
 */

import { $, buildAndOffer, openFirmware, status, wireDrop } from "./shell.js";
import { replacement } from "../firmware.js";
import { apply, extents } from "../mods/lfolength.js";

let state = { firmware: null, filename: "firmware.syx" };

async function ready(firmware) {
  // Applying is also the check that this image is one the mod was measured
  // against: every guard is read, and it throws rather than writing.
  apply(firmware);
  state.firmware = firmware;
  const found = extents(firmware);
  const bytes = found.reduce((n, e) => n + e.length, 0);
  $("writes").textContent = `${found.length} ranges, ${bytes} bytes in section 3: 4 hooks, 4 NOP'd stores and the shared start-up loader, which copies a 260-byte code chunk to RAM`;
  for (const id of ["step2", "step3", "bar"]) $(id).classList.remove("hidden");
  status("Loaded. Ready to build.");
}

async function buildImage() {
  const { content, notes } = apply(state.firmware);
  await buildAndOffer(
    state.firmware,
    new Map([[3, replacement(state.firmware, 3, content)]]),
    { filename: state.filename, suffix: "lfofix", note: notes[0] });
}

function open(file) {
  state.filename = file.name;
  return openFirmware(file, { onReady: ready });
}

wireDrop($("drop"), open);
$("syx").addEventListener("change", (e) => {
  if (e.target.files?.[0]) open(e.target.files[0]);
});
$("buildBtn").addEventListener("click", buildImage);
$("resetBtn").addEventListener("click", () => location.reload());
