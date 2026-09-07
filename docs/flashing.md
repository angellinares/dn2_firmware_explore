# Flashing, and getting back

**Nothing in this file has been done yet.** It is the procedure, written before
it is needed, which is the point of it. Results get recorded here as they
happen, with dates.

## The order, and why it is this order

Each step fails differently from the one before it. Run them in order and a
failure tells you which part is wrong.

### 0. Back up the +Drive — before anything

Use DNX's `.dnx` backup. Firmware and user data are separate, and a firmware
flash should not touch projects — but "should not" is not a backup.

### 1. Prove the way back, with stock firmware

**This gates every other hardware step.**

1. Power the instrument holding `FUNC` to reach the **Early Start-up Menu**.
2. Confirm there is an `OS UPGRADE` entry. Photograph the menu.
3. Send the **stock, unmodified** `Digitone_II_OS1.10E.syx` to it over MIDI.
4. Record below: the route, how long it took, what the screen showed at each
   stage, and what a failure would look like.

The point is that this route lives in the bootloader, not in MAIN OS, so it
should still work when a MAIN OS we built does not. Until it has actually been
used once, that is a belief.

If step 2 or 3 does not behave as expected — **stop**. Do not flash anything
modified.

### 2. Gate D — a rebuild that changes nothing

```
dnfw build 00_Resources/00_Firmware/Digitone_II_OS1.10E_dist.zip -o gate-d.syx
```

Byte-identical to stock, so this proves nothing on its own. Instead extract and
rebuild MAIN OS so the compressed bytes differ while the code does not:

```
dnfw extract <image> --section 3 -o out/
dnfw build <image> -s 3=out/section_3_MAIN_OS.aplib.bin -o gate-d.syx
```

Same code, different stream, valid checksums, valid HMAC. **If it boots, the
repack-and-sign pipeline is accepted by the device.** If it does not, the fault
is in packing or signing — nothing else changed.

### 3. Gate E — a patch you can see

```
dnfw patch apply 00_Resources/00_Firmware/Digitone_II_OS1.10E_dist.zip -o gate-e.syx
```

Renames `SETTINGS > PERSONALIZE` to `DNFW ALIVE!`. Flash it, open SETTINGS,
photograph the screen.

That closes Phase 1: unpack, modify, repack, re-sign, flash, observe, as a loop
that can be run again.

## Standing rules

- **Verify before sending.** `dnfw inspect` on the file you are about to flash.
  `build` and `patch apply` already refuse to write anything that does not
  verify, but the file that reaches the instrument is the one to check.
- **One change at a time.** Gate D and Gate E are separate flashes on purpose.
- **Keep stock to hand.** The unmodified `.syx` is the recovery image; it stays
  in `00_Resources/00_Firmware/` and is never overwritten by a build output.
- **Do not patch the key material.** See `docs/ele3-format.md` §5.

## Record

| Date | Step | Result |
|---|---|---|
| | | *nothing yet* |
