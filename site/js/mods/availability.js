/**
 * Mods withdrawn from the site, by mod id.
 *
 * One subject: which mods are off and what the reader is told. A mod listed
 * here cannot be loaded or built on its page and is marked on the mod list;
 * its page stays up and shows the notice where the download would be.
 * Delete the entry to put the mod back.
 */

export const UNAVAILABLE = {
  lfo4: {
    since: "2026-10-10",
    title: "LFO4 is unavailable for now",
    reason: "We are looking into a report of song data being damaged in projects used with LFO4. "
      + "The download is off until that is resolved. If you have LFO4 installed, back up your "
      + "projects and work in copies.",
  },
  fxmod: {
    since: "2026-10-10",
    title: "LFO modulation of the FX is unavailable for now",
    reason: "We are looking into a report of song data being damaged in projects used with this mod. "
      + "The download is off until that is resolved. If you have it installed, back up your "
      + "projects and work in copies.",
  },
};

/** The entry for `id`, or null when the mod is on offer. */
export function flagFor(id, table = UNAVAILABLE) {
  return table[id] ?? null;
}
