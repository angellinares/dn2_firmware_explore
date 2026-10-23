/**
 * The Check page: two files in, the safety checklist out (safety.js). Text is set, never
 * interpolated into HTML.
 */

import { load } from "../firmware.js";
import { check, NOT_CHECKED } from "../safety.js";
import { rebuild } from "../mods/registry.js";
import { $, wireDrop } from "./shell.js";

const MARK = { pass: "PASS", warn: "WARN", fail: "FAIL", info: "INFO", skip: "SKIP" };
const files = { patched: null, stock: null };

function pick(which, file) {
  files[which] = file;
  $(`${which}Name`).textContent = file.name;
  if (files.patched && files.stock) run();
}

for (const which of ["patched", "stock"]) {
  $(which).addEventListener("change", (e) => { if (e.target.files[0]) pick(which, e.target.files[0]); });
  wireDrop($(`drop${which[0].toUpperCase()}${which.slice(1)}`), (file) => pick(which, file));
}

async function read(file) {
  return load(new Uint8Array(await file.arrayBuffer()));
}

async function run() {
  $("results").classList.remove("hidden");
  const list = $("list");
  list.innerHTML = "";
  $("summary").textContent = "Checking…";
  $("summary").classList.add("busy");
  await new Promise((r) => requestAnimationFrame(r));
  let items;
  try {
    let patched;
    try {
      patched = await read(files.patched);
    } catch (error) {
      items = [{ key: "file", title: "The file is intact", status: "fail",
                 detail: `it is not a Digitone II OS file: ${error.message ?? error}` }];
    }
    if (!items) {
      const stock = await read(files.stock);
      items = await check(patched, stock, rebuild);
    }
  } catch (error) {
    items = [{ key: "stock", title: "The stock file is a known Digitone II OS", status: "fail",
               detail: `it is not a Digitone II OS file: ${error.message ?? error}` }];
  }
  $("summary").classList.remove("busy");
  show(items);
}

function show(items) {
  const list = $("list");
  for (const it of items) {
    const row = document.createElement("div");
    row.className = "row";
    row.dataset.status = it.status;
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = MARK[it.status];
    const title = document.createElement("span");
    title.className = "title";
    title.textContent = it.title;
    const detail = document.createElement("span");
    detail.className = "detail";
    detail.textContent = it.detail;
    row.append(chip, title, detail);
    list.append(row);
  }
  const count = (s) => items.filter((i) => i.status === s).length;
  const fails = count("fail"), warns = count("warn");
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  $("summary").textContent = `${plural(fails, "failure", "failures")}, ${plural(warns, "warning", "warnings")}, `
    + plural(count("pass"), "pass", "passes");
  const ul = $("notChecked");
  ul.innerHTML = "";
  for (const line of NOT_CHECKED) {
    const li = document.createElement("li");
    li.textContent = line;
    ul.append(li);
  }
}
