# The MODS page

Every build from `dnfw mods apply` or from the website has a page that lists its mods. You read the list on the instrument. You do not need the file you flashed.

## How to open it

1. Press **SETTINGS**.
2. Select **SYSTEM**.
3. Press **YES**.
4. Select **MODS**, the last entry.
5. Press **YES**.

**UP** and **DOWN** move through the rows. **NO** goes back to SYSTEM. **YES** and the knobs do nothing on a row.

## What it shows

The first three rows are general:

- A row **OS** with the firmware version that the build starts from.
- A row with the build's name. For the command line, this is the output file's name before `_DN2_`, or the probe's tag. For the website, it is `WEB BUILD`.
- A row **COMMIT** with the first seven characters of the tool's commit. A `+` after it means that the tool had changes that were not committed. For the website, it is the site's commit.

Then one row for each mod: a short name on the left and the mod's version on the right.

The names have 12 characters at most, so that they stay clear of the version. The table of names is `MENU_NAMES` in `scripts/build_mods_page.py`. A mod that is not in the table shows its id.

## What to send with a bug report

Read the rows to the person who helps you, or send a photo of each screen. The versions, the OS row and the COMMIT row identify the build.

## A build without the page

`dnfw mods apply --no-mods-page` leaves the page out. Use it for a control build that must hold only stock and one change.

## How it works

The page is not a mod. `dnfw mods apply` adds it after the mods, and the website adds it with each mod that a page applies. When the image has the page already, the build keeps the page's hook and writes the new rows.

- One hook at the end of the SYSTEM menu's start-up code builds the MODS menu from stock's own menu parts. So the page looks like the stock menus.
- The code is the same in every build. The rows are data after the code: a count, then 32 bytes for each row.
- The code and the rows are a chunk at `0x46798000` in the platform's area. So a build with the page has the platform's loader, also when its mods do not need it.
- The build ships no image. The menu shows SYSTEM's art, and the MODS entry shows the icon of OS UPGRADE.

`scripts/build_mods_page.py` has the method and the stock routines. `scripts/emu_mods_page.py` checks the page in the emulator from reset. `test/test_modspage.py` checks the rows and the bytes on OS 1.11 and OS 1.12.

## Limits

- The page holds 64 rows.
- A row cannot show `%` or a character outside `A-Z`, `0-9`, space and `. + - _ /`. The build replaces such a character with a space.
- The page shows what the build tool wrote. It does not check the code of the mods at run time.
