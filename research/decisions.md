# Decision log (ADR-lite)

Each decision: ID, date, decision, rationale, consequences, links.
Decisions are made by research and are binding for the coding chat until superseded by a new entry.

## D-01 — USB root filesystem only; internal disk read-only for the OS
- **Date:** 2026-11-13 · **Status:** accepted
- **Rationale:** internal repartitioning destroys Orbis and game saves; recovery requires a full firmware
  reinstall. USB 3.0 matches or beats the Fat's SATA-II bus anyway.
- **Consequences:** one USB device is part of the product; power-loss resilience work (EXP-013) is mandatory.
- **Refs:** `02-boot-chain.md` §6, `11-risks-legal.md` §1/§3, `27`

## D-02 — Firmware frozen at the jailbroken version
- **Date:** 2026-11-13 · **Status:** accepted
- **Rationale:** updates are irreversible and can close the exploit; 14.00+ paths are early.
- **Consequences:** docs must not advise updates; support must ask for the FW version first.
- **Refs:** `11-risks-legal.md` §2, `S24`, `S25`

## D-03 — Default VRAM payload 1024 MB
- **Date:** 2026-11-13 · **Status:** accepted
- **Rationale:** balances GPU needs of Plasma/browser with ~6.5 GB system RAM; 2048 MB reserved for the
  gaming/emulation profile.
- **Consequences:** profile switch documented; `vram.txt` validated in MB.
- **Refs:** `01-hardware-firmware.md` §4, `BOOT-004`

## D-04 — Mesa pinned; upgrades only through experiments
- **Date:** 2026-11-13 · **Status:** accepted
- **Rationale:** RADV on gfx7 has produced GPU hangs with DXVK in recent Mesa series; 25.3.5 / 26.0.4 are
  the known-stable references.
- **Consequences:** T-006 + T-007; doctor reports versions; every Mesa bump runs EXP-009/EXP-008.
- **Refs:** `03-graphics.md` §3, `S08`

## D-05 — KDE Plasma is the product desktop; XFCE is the guaranteed fallback
- **Date:** 2026-11-13 · **Status:** accepted
- **Rationale:** README requires a Windows-like desktop; a light DE guarantees recovery on any kernel.
- **Consequences:** image ships both sessions; acceptance table in `04-desktop.md` §7.
- **Refs:** `04-desktop.md` §4

## D-06 — No claim without an experiment
- **Date:** 2026-11-13 · **Status:** accepted
- **Rationale:** the scene is full of folklore; most support pain comes from unverified assumptions.
- **Consequences:** `09-experiments.md` gate; `results/INDEX.md` row required to close a ticket.

## D-07 — Kernel source of record and Mesa build (supersedes parts of `03`/`07`)
- **Date:** 2026-11-13 · **Status:** accepted
- **Decision:**
  - Kernel: `feeRnt/ps4-linux-12xx@7.0-Clean` = `8ec5c282abda91f6c2e4014de206105aa7912516` (primary),
    `6.15.4-aeolia-belize-crashniels` = `3cba9d4db59422c8fc4dd55a39958def042e8816` (fallback/current baseline).
  - Mesa: build **26.2.5** (SHA256 `794b3d17…`) + **libdrm 2.4.134** (SHA256 `ac5e74d1…`) with
    `ps4-multiboot` patches `0001` (`0cea118`) + `0002` (`6069650`). Candidate B = Mesa 25.3.5 (control).
  - Dead upstream (`sony-jaguar-devs/ps4-linux`, `ps4-linux/linux`, `ps4-linux/ps4-linux-loader`) is **not a
    dependency**; `ps4-multiboot`'s default `KERNEL_REPO` is dead, so its build is not reproducible as published.
- **Rationale:** only verifiable tree with fan/thermal hwmon + Mesa lock; only verified patch set; HiZ is the
  actual cause of GFX-002, so a version workaround alone is insufficient.
- **Consequences:** T-002/T-006/T-012 consume `14-pinned-inputs.lock.yaml`; builds fail rather than fall back.
- **Refs:** `13-QA-coding-2026-11-13.md` §1, `S43`, `S44`

## D-08 — Two kernel layouts, explicit and exclusive (amends D-01 scope, not its intent)
- **Date:** 2026-11-13 · **Status:** accepted
- **Decision:** support **(A)** kernel+initramfs on a FAT32 `PS4BOOT` partition of the USB, and **(B)** kernel in
  `/data/linux/boot` via FTP. The layout is declared in `profile.yaml`; a set with a kernel in both places is
  refused. **There is no "FTP-only" rule** — that was an unverified over-specification and is withdrawn.
- **Rationale:** both layouts are shipped by maintained projects; the precedence of one loader cannot be
  verified because the loader repos are unreadable.
- **Consequences:** BOOT-003 rewritten (layout consistency, not precedence); T-002 becomes a layout validator,
  not an FTP writer; USB-only disk policy (D-01) is unchanged.
- **Refs:** `13-QA-coding-2026-11-13.md` §1 Q3, §3 C1/C2, `S43`
