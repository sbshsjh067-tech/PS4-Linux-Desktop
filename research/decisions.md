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
