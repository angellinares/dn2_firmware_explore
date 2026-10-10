/** The mod list: marks each card whose mod is withdrawn (`mods/availability.js`). */

import { UNAVAILABLE } from "../mods/availability.js";
import { markCard } from "./unavailable.js";

for (const [id, flag] of Object.entries(UNAVAILABLE)) {
  const card = document.querySelector(`article.mod[data-mod="${id}"]`);
  if (card) markCard(card, flag);
}
