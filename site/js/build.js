/**
 * Which site code made a build: the commit the Pages deploy writes in place of "local"
 * (.github/workflows/pages.yml). A build made here carries SITE_BUILD in its /modinfo record's
 * commit field (modinfo.js), and every page that builds firmware shows it in the footer.
 */

export const SITE_COMMIT = "local";
export const SITE_BUILD = `web-${SITE_COMMIT}`;

// node: no document, or a harness stub without querySelectorAll
if (typeof document !== "undefined" && typeof document.querySelectorAll === "function") {
  for (const el of document.querySelectorAll("[data-site-build]")) el.textContent = SITE_BUILD;
}
