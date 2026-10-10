// The downloaded file's name carries the mod's version (site/js/app/shell.js, outputName),
// and every mod page names its mod. Run by test/test_js_output_name.py.
import { readFileSync, readdirSync } from "node:fs";
import { VERSIONS } from "../site/js/mods/versions.js";

globalThis.document = { getElementById: () => null };
const { outputName } = await import("../site/js/app/shell.js");
const ok = (name, pass) => { console.log(`${pass ? "OK  " : "FAIL"} ${name}`); if (!pass) process.exitCode = 1; };

ok("the version follows the mod's suffix",
   outputName("Digitone_II_OS1.11.syx", "fxmod", "fxmod", { fxmod: "1.2.3" }) === "Digitone_II_OS1.11_fxmod_1.2.3.syx");
ok("a second mod on a modded file adds its own, so the name lists the mix",
   outputName("Digitone_II_OS1.11_fxmod_1.2.3.syx", "lfofix", "lfolength", { lfolength: "1.0.1" })
     === "Digitone_II_OS1.11_fxmod_1.2.3_lfofix_1.0.1.syx");
ok("the extension is matched whatever its case", outputName("FW.SYX", "x", "fxmod", { fxmod: "1.0.0" }) === "FW_x_1.0.0.syx");
ok("without a mod the name has no version (control)", outputName("fw.syx", "bench") === "fw_bench.syx");
ok("the real table is used by default", outputName("fw.syx", "fxmod", "fxmod") === `fw_fxmod_${VERSIONS.fxmod}.syx`);

const dir = new URL("../site/js/app/", import.meta.url);
const pages = readdirSync(dir).filter((f) => f.endsWith("-page.js"));
for (const f of pages) {
  const text = readFileSync(new URL(f, dir), "utf8");
  if (!text.includes("buildAndOffer(")) continue;
  const mod = /filename: state\.filename, mod: "(\w+)"/.exec(text)?.[1];
  ok(`${f} names its mod, and the mod has a version`, Boolean(mod) && mod in VERSIONS);
}
