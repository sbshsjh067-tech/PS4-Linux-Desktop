# 11 — Risks, legal, and safety

This document exists because the project touches **user hardware**, **Sony firmware**, and **third-party
licences**. The research workstream's job is to make every risk explicit before code runs on a console.

---

## 1. Hard bricking vs. soft failures — what is actually possible

| Failure | Probability | Recoverability |
|---|---|---|
| Linux payload fails, console needs power-cycle | Common | Trivial |
| Wrong kernel → white light, no boot | Common | Power off, boot Orbis normally |
| Corrupted USB rootfs | Occasional | Re-flash USB; console unaffected |
| **Internal disk repartitioned/`mkfs`'d → Orbis + all saves lost** | Only if someone ignores policy | Recovery USB with the matching `PS4UPDATE.PUP` + full reinstall |
| Thermal damage from disabled/lowered fan thresholds | Low but real | Not recoverable (hardware) |
| Firmware updated past the exploit | Depends on user action | **Not reversible** — often permanent for that console |

**Design consequences already encoded elsewhere:**
- **D-01:** USB root only, no internal writes (`02` §6, `08` M1/M4).
- **D-02:** firmware freeze (`00` §5, `11` §2).
- **SYS-002 / T-012:** fan thresholds never below the measured-safe band.

## 2. Firmware policy (irreversible decision)

1. **Do not update PS4 firmware** while the project is using that console for Linux work.
2. A firmware update can:
   - close the exploit used to run GoldHEN,
   - change kernel offsets (the loader's kexec blobs),
   - break audio/video behaviour the kernel patches were tuned for.
3. Updates **cannot be rolled back** on retail hardware.
4. If the console is on 14.00 or newer, read `02` §4 and `06` §BOOT-007 first; the path is early and rough.
5. Any documentation that tells a user "update to the latest firmware first" is **wrong** for this project.

## 3. Data-loss prevention checklist (shipped with every image)

- [ ] Installer refuses to write to `/dev/sda`/`/dev/nvme*` (internal) and to any device with PS4 partitions.
- [ ] All destructive operations print the target device model + size and require typing the label.
- [ ] `commit=30`, `noatime`, `errors=remount-ro` on root; fsck on boot.
- [ ] First-boot guide says: *unplug the USB before booting Orbis after a Linux session* (prevents accidental
      NTFS/FAT write by Orbis and keeps the PS4 from touching Linux files).
- [ ] Recovery procedure documented: power off → remove USB → boot Orbis → verify saves present.

## 4. Safety: heat, power, and the "always on" desktop

- PS4 Fat has a large but noisy cooling system; sustained 100 % CPU load at a low fan threshold can exceed
  safe SoC temperatures. EXP-012 is a **release gate**, not a suggestion.
- Do not block vents or run the console in a closed cabinet; the README's "desktop PC" use case encourages
  leaving it on for hours.
- Suspend is unavailable (`SYS-001`): the console cannot idle at low power like a laptop. Users should
  shut down rather than leave it running, unless the thermal profile is verified.

## 5. Licences and third-party components

| Component | Licence (verify before shipping) | Obligations |
|---|---|---|
| Linux kernel + PS4 patches | GPL-2.0 | source availability, notices |
| Mesa / libdrm / LLVM | MIT-style / Apache-2.0-with-LLVM-exceptions | attribution, licence text |
| DXVK, VKD3D-Proton | zlib / LGPL-2.1 | notices; dynamic linking rules for LGPL parts |
| Proton (Valve) | mixed (see repo) | keep licence files, don't rebrand |
| GoldHEN | GPL-family (check repo) | we **do not redistribute** GoldHEN; user obtains it |
| Loader (`ps4-linux-loader`) | verify (GPL-family expected) | mirror with source, keep notices |
| DolphinPS4 / RetroArch forks | GPL-2.0 / GPL-2.0+ | provide sources; no ROMs ever |
| KDE Plasma, XFCE, apps | GPL/LGPL/MIT mix | standard distro compliance |

**Never ship:** Sony firmware, PSN binaries, game dumps, ROMs, keys, or GoldHEN itself. The project ships
*configuration and glue*; the user supplies the exploit tooling and their own software.

**Mirroring rule** (`07` §5): if we depend on a repo that 404s, we cannot ship a build that fetches it at
build time. Mirror the exact commit under our storage **and** keep its licence/attribution with it.

## 6. Legal / ToS considerations (non-legal-advice summary)

- Running Linux on a console you own is a well-established homebrew activity in many jurisdictions; it can
  still violate Sony's **system software licence** and **void warranty**.
- Jailbreaking may be illegal or legally contested in some countries (DMCA §1201-style anti-circumvention
  rules). The user is responsible for local law.
- **Never** connect a jailbroken console to PSN with homebrew active: risk of account/console ban.
- Do not distribute exploit code or copyrighted firmware; do not monetise the exploit chain.
- The project should ship a plain-language disclaimer on the download page (T-018).

## 7. Reputation & support risks

| Risk | Mitigation |
|---|---|
| Users blame the project for hardware they damaged | Disclaimers + the "internal disk is forbidden" policy |
| A Mesa/DXVK update silently breaks everyone | version freeze (T-007) + doctor check |
| "KDE is slow on PS4" reviews | publish honest performance numbers from `00` §3 and `04` §7 |
| Bus factor 1 in upstream projects | mirrors, pinned commits, in-repo build scripts (T-017) |
| Stale docs (scene moves monthly) | freshness policy in `README.md` §5 and weekly digest (M7) |

## 8. Ethics of the research itself

- Do not present `[REPORTED]` community claims as verified facts in user docs.
- Publish negative results (e.g. "VP9 1080p does not work") — they save users hours.
- Do not encourage users to update firmware "for security" on hardware that then loses all homebrew.
- Credit upstream authors by name and link in every release note.
