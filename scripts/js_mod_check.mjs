/**
 * Run the browser transients mod over a real `.syx`, from the command line.
 *
 * The check that matters is the one `docs/mods.md` calls the factory
 * round-trip: **extract the bank and write it straight back.** The Python tool
 * produces a byte-identical section 7 doing this. The browser tool cannot --
 * store-only packing encodes differently -- so the standard here is that the
 * *unpacked* section comes back byte-identical, which is the same statement
 * about the bank and a weaker one only about the compressor.
 *
 * It is a strong check rather than a pleasant one: a wrong bank offset, entry
 * size, count, endianness or sample width would each corrupt bytes, and the
 * boot-stream walk that resolves the address is exercised on the way.
 *
 * `fit` is checked separately and synthetically, because its job is to make
 * judgement calls about audio and the only way to know it made the right one is
 * to feed it a signal whose answer is known in advance.
 *
 * Usage:
 *   node scripts/js_mod_check.mjs --syx FILE
 */

import { readFileSync, writeFileSync } from "node:fs";
import { build, load, verify } from "../site/js/firmware.js";
import { fit } from "../site/js/audio.js";
import {
  COUNT, RATE, apply, extents, extract, fit as fitEntry, lengths, toEntry, toFloat,
} from "../site/js/mods/transients.js";

function arg(name) {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? process.argv[i + 1] : null;
}

function same(a, b) {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

const syxPath = arg("syx");
if (!syxPath) {
  console.error("usage: js_mod_check.mjs --syx FILE");
  process.exit(2);
}

const firmware = await load(new Uint8Array(readFileSync(syxPath)));
const checks = [];

// The bank, located by walking the boot stream for the blocks covering its load
// addresses -- an offset into section 7 is not an address -- and read through its table.
const factory = extract(firmware);
const where = extents(firmware)[0];
// `--bank-out` writes the 32 factory transients end to end so the Python side can compare
// them against its own extraction. Locating the bank is the one thing both implementations
// do from the same measured constants, so it is the one place a shared misreading of those
// constants could hide.
const total = factory.reduce((n, e) => n + e.length, 0);
if (arg("bank-out")) {
  const bank = new Uint8Array(total);
  let at = 0;
  for (const entry of factory) { bank.set(entry, at); at += entry.length; }
  writeFileSync(arg("bank-out"), bank);
}
checks.push({
  check: `bank is ${COUNT} entries as the factory table plays them`,
  ok: factory.length === COUNT && total === 331200,
  detail: `${total.toLocaleString()} bytes, at section ${where.section} offset ${where.start.toLocaleString()}`,
});

const stockSection = firmware.container.find(7).unpack();
const sizes = lengths(false);
const EQ = lengths(true);

// Factory sizes, the factory bank written straight back: section 7 comes back byte for byte.
const kept = apply(firmware, new Map(factory.map((entry, k) => [k, entry])));
const keptImage = await load(await build(firmware, new Map([[7, kept.section]])));
checks.push({
  check: "factory sizes: factory round-trip reproduces section 7 unpacked, byte for byte",
  ok: same(keptImage.container.find(7).unpack(), stockSection),
  detail: `${stockSection.length.toLocaleString()} bytes`,
});

// Factory sizes: one slot changed, and only that slot.
const marker = (n) => toEntry(new Float32Array(n).map((_, i) => Math.sin((2 * Math.PI * 440 * i) / RATE) * 0.5), n);
const one = extract(await load(await build(firmware, new Map([[7, apply(firmware, new Map([[17, marker(sizes[17])]])).section]]))));
checks.push({ check: "factory sizes: replacing slot 17 changes slot 17", ok: same(one[17], marker(sizes[17])) });
checks.push({
  check: "factory sizes: ...and leaves the other 31 exactly as they were",
  ok: one.every((entry, slot) => slot === 17 || same(entry, factory[slot])),
});

// Equal slots, no replacement: 32 entries of one length, each the factory sound fitted.
const laid = apply(firmware, new Map(), { equal: true });
const rebuilt = await load(await build(firmware, new Map([[7, laid.section]])));
const laidOut = extract(rebuilt);
checks.push({
  check: `equal slots: every slot is ${EQ[0]} samples, the factory sound fitted`,
  ok: laidOut.every((entry, k) => same(entry, fitEntry(factory[k], EQ[k]))),
});
const again = apply(rebuilt, new Map(laidOut.map((entry, k) => [k, entry])), { equal: true });
const back = (await load(await build(rebuilt, new Map([[7, again.section]])))).container.find(7).unpack();
checks.push({
  check: "equal slots: round-trip of the laid-out bank reproduces section 7 unpacked, byte for byte",
  ok: same(back, rebuilt.container.find(7).unpack()),
});
const after = await verify(rebuilt);
checks.push({
  check: "equal slots: the image verifies",
  ok: after.every((c) => c.ok),
  detail: `${after.filter((c) => c.ok).length}/${after.length}`,
});
const oneEq = extract(await load(await build(firmware, new Map([[7, apply(firmware, new Map([[17, marker(EQ[17])]]), { equal: true }).section]]))));
checks.push({ check: "equal slots: replacing slot 17 changes slot 17", ok: same(oneEq[17], marker(EQ[17])) });
checks.push({
  check: "equal slots: ...and leaves the other 31 as the factory sound fitted",
  ok: oneEq.every((entry, slot) => slot === 17 || same(entry, fitEntry(factory[slot], EQ[slot]))),
});

// `fit`, against signals whose right answer is known in advance.
const silenceThenClick = new Float32Array(RATE);   // 1 s
silenceThenClick[4800] = 1;                        // a click exactly 100 ms in
const SLOT = 4800;                                 // any slot length
const fitted = fit(silenceThenClick, { length: SLOT, leadMs: 3 });
checks.push({
  check: "fit finds the onset past leading silence",
  ok: fitted.onset === 4800,
  detail: `onset ${fitted.onset}, window starts ${fitted.start}`,
});
checks.push({
  check: "fit leaves exactly leadMs of room before the onset",
  ok: fitted.start === 4800 - Math.round((3 * RATE) / 1000),
});
checks.push({
  check: "fit always returns exactly one slot",
  ok: fitted.samples.length === SLOT,
});

const explicit = fit(silenceThenClick, { length: SLOT, startMs: 200 });
checks.push({
  check: "an explicit startMs overrides onset detection",
  ok: explicit.start === Math.round((200 * RATE) / 1000),
});

// start = 0 means the file's own beginning, not "unset". JS makes this easy to
// get wrong: 0 is falsy, so a truthiness test anywhere on this path would fall
// back to onset detection and silently skip the user's leading silence --
// exactly the thing they chose 0 to keep.
const fromZero = fit(silenceThenClick, { length: SLOT, startMs: 0 });
checks.push({
  check: "startMs 0 takes the sample from its very start",
  ok: fromZero.start === 0,
  detail: `start ${fromZero.start}, onset would have given ${fromZero.onset}`,
});
checks.push({
  check: "startMs 0 keeps the first slot verbatim",
  // The last 2 ms are faded, so compare only up to the fade.
  ok: Array.from({ length: SLOT - 120 }, (_, i) => i)
    .every((i) => fromZero.samples[i] === silenceThenClick[i]),
});

const loud = new Float32Array(SLOT).fill(1);
const faded = fit(loud, { length: SLOT, startMs: 0 });
checks.push({
  check: "fit fades the last 2 ms so the cut adds no click",
  ok: faded.samples[SLOT - 1] === 0 && faded.samples[0] === 1,
  detail: `last sample ${faded.samples[SLOT - 1]}`,
});

// A factory entry survives Float32 and back. Catches a scaling error that a
// round-trip of raw bytes would never see, because it never converts.
const original = factory[0];
checks.push({
  check: "int16 -> float -> int16 is lossless for a factory entry",
  ok: same(toEntry(toFloat(original), original.length / 2), original),
});

console.log(JSON.stringify({ checks }, null, 2));
process.exit(checks.every((c) => c.ok) ? 0 : 1);
