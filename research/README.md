# Research & Analysis Handbook — PS4 Linux Desktop

**Role of this folder:** this folder is the *research engine* of the project.
It finds, verifies, and documents **what already exists**, **what breaks**, and **how to solve it
scientifically** — with evidence, alternatives, and acceptance criteria.

It deliberately contains **no implementation code**. Implementation belongs to the coding workstream
(separate chat / separate agent). Every research item here is written so that a coding agent can pick
it up as a specification without having to redo the research.

| | |
|---|---|
| Handbook owner | Research workstream |
| Last full review | **2026-11-13** |
| Scope | PS4 "Fat" (CUH-10xx / 11xx / 12xx) first, Slim/Pro only where needed for compatibility |
| Target of the project | KDE Plasma desktop ("Windows-like"), browser, Steam, Dolphin, VLC, LibreOffice, USB peripherals, **Orbis preserved** |

---

## 1. How to use this handbook

1. Read `00-executive-summary.md` first — it is the reality check.
2. The coding workstream works **only** from `10-coding-tickets.md` and `backlog.yaml`.
3. When a bug appears on hardware, look it up in `06-issues-registry.md` by ID (`BOOT-`, `GFX-`, `NET-`, `SYS-`, `APP-`).
   If it is not there, open a new entry *using the same template* before touching code.
4. Any claim labelled `[VERIFIED]` was checked against source code, release notes, or a primary project page.
   `[REPORTED]` = community report, plausible but not reproduced here.
   `[ESTIMATE]` = computed/derived by us, must be validated by an experiment in `09-experiments.md`.
   `[UNVERIFIED]` = do not build a decision on it.
5. Numbers have a date. Vendor pages change; the PS4 Linux scene moves fast (see §5).

## 2. Separation of duties (non-negotiable)

| Workstream | Owns | Must not do |
|---|---|---|
| **Research (this folder)** | evidence gathering, root-cause analysis, option ranking, specs, test protocols, risk/legal analysis | write code, flash devices, guess fixes without evidence |
| **Coding** | kernel config, initramfs, scripts, images, drivers/packaging | invent requirements, skip `09-experiments.md` protocols, change scope silently |
| **Hardware/test** | running the protocols on a real console, collecting logs | accept "it works" without numbers |

A "fix" is only accepted when it has: **(a)** a root cause, **(b)** an issue ID, **(c)** a test in
`09-experiments.md`, **(d)** before/after data.

## 3. Document map

| File | Purpose |
|---|---|
| `00-executive-summary.md` | feasibility verdict per project goal, hardware budget, top risks |
| `01-hardware-firmware.md` | console revisions, southbridge, CPU/GPU facts, firmware/jailbreak state |
| `02-boot-chain.md` | jailbreak → loader → kernel → initramfs → rootfs, file precedence, failure modes |
| `03-graphics.md` | Liverpool/Gladius (GFX7-class), Mesa/RADV/RadeonSI, versions that work, DXVK limits |
| `04-desktop.md` | KDE Plasma vs alternatives, memory budget, X11/Wayland, tuning |
| `05-applications.md` | browser, Steam/Proton, Dolphin, VLC/mpv, LibreOffice, peripherals |
| `06-issues-registry.md` | the problem/solution database (the operational core) |
| `07-upstream-projects.md` | landscape of existing projects: status, licence, what to reuse, bus factor |
| `08-roadmap.md` | milestones M0–M7 with exit criteria |
| `09-experiments.md` | experiment protocols + measurement tools + result templates |
| `10-coding-tickets.md` | implementation-agnostic task specs handed to the coding chat |
| `11-risks-legal.md` | bricking, data loss, ToS/legal, firmware policy, ethics |
| `12-sources.md` | numbered source list `S01…` used everywhere |
| `backlog.yaml` | machine-readable backlog (same IDs as the docs) |
| `profile.example.yaml` | per-console profile to fill in before any testing |
| `glossary.md` | vocabulary for newcomers in the coding chat |

## 4. Definition of done for a research item

- [ ] Symptom reproducible description (what the user sees, on which model)
- [ ] Affected scope (Aeolia / Belize / Baikal, kernel version, Mesa version)
- [ ] Root cause with evidence (log line, source diff, release note, upstream issue)
- [ ] Resolution options ranked with trade-offs (cheapest/stablest first)
- [ ] Verification test with a **pass/fail number**, added to `09-experiments.md`
- [ ] Residual risk + rollback

## 5. Freshness policy

- §The PS4 Linux scene produced at least 20 relevant releases in 2026. Anything older than **90 days**
  in `03-graphics.md`, `07-upstream-projects.md` and `02-boot-chain.md` must be re-checked before a build.
- Firmware/jailbreak state must be re-checked before advising a user to update. **Never** advise a
  firmware update without checking `11-risks-legal.md` §2 (updates are irreversible and can close the exploit).
- Mesa/DXVK/Proton version pins in `03-graphics.md` are **hard constraints** for the coding chat until
  an experiment proves otherwise.

## 6. What this project is *not*

- Not a distribution of Sony firmware, game backups, or copyrighted blobs.
- Not a path to PSN while jailbroken.
- Not a promise of modern-AAA gaming performance (see `00-executive-summary.md` §2).
