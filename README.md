# PS4-Linux-Desktop

An ambitious project to transform the PlayStation 4 (PS4 Fat) into a fully functional Linux desktop computer
powered by KDE Plasma — a Windows-like desktop with a web browser, Steam, Dolphin Emulator, VLC, LibreOffice,
USB peripherals and more, **while keeping the original PS4 operating system (Orbis) intact**.

---

## How this repository is organised

This repository holds **research, not code**. It is the *search engine* of the project: it finds the
projects, finds the problems, and solves them **scientifically** — root cause, options, decision, and a
measurable verification test.

The actual implementation (kernel configs, images, scripts, packaging) is written in a **separate coding
workstream**, working from the specifications produced here.

```
.
├── README.md            ← you are here
├── AGENTS.md            ← operating rules for the research engine
└── research/            ← the research engine (start at research/README.md)
    ├── 00-executive-summary.md   feasibility verdict + hardware budget + top risks
    ├── 01-hardware-firmware.md   APU facts, console revisions, firmware state, memory budget
    ├── 02-boot-chain.md          jailbreak → loader → kernel → initramfs → desktop
    ├── 03-graphics.md            PS4 GPU, patched Mesa, Vulkan 1.3 ceiling, DXVK/Proton pins
    ├── 04-desktop.md             KDE Plasma configuration within the hardware budget
    ├── 05-applications.md        browser, Steam, Dolphin, VLC, LibreOffice, peripherals
    ├── 06-issues-registry.md     the problem → solution database (31 tracked issues)
    ├── 07-upstream-projects.md   existing projects: what to reuse, and in which version
    ├── 08-roadmap.md             milestones M0–M7 with exit criteria
    ├── 09-experiments.md         14 measurement protocols with pass/fail numbers
    ├── 10-coding-tickets.md      18 implementation-agnostic specs handed to the coding chat
    ├── 11-risks-legal.md         bricking, data loss, firmware policy, licences
    ├── 12-sources.md             every source, tagged [S01]…[S42]
    ├── backlog.yaml              machine-readable backlog (issues + tickets + experiments)
    ├── decisions.md              decision log (D-01 … D-06)
    ├── profile.example.yaml      per-console profile to fill before any test
    ├── glossary.md               vocabulary
    └── results/                  experiment outputs + INDEX.md
```

## Read this before proposing anything

1. **`research/00-executive-summary.md`** — what is feasible on this hardware and what is not.
2. **`research/06-issues-registry.md`** — if your problem is not there, add it with the template first.
3. **`research/AGENTS.md`** — the separation between research (this repo) and implementation (other chat).

## Reality check in three lines

- ✅ A jailbroken PS4 Fat boots Linux from USB with an accelerated desktop (OpenGL 4.6, Vulkan 1.3), KDE Plasma,
  browsers, media, office work and USB peripherals.
- ⚠️ Steam works **only** within pinned versions (DXVK ≤ 2.7.1, Proton ≤ 11): the GPU is GFX7-class and stops at
  Vulkan 1.3, so current DXVK 3.x is unusable. Dolphin is good for GameCube, mixed for Wii.
- ❌ No suspend, no 4K/H.265/AV1 playback, no modern AAA games, no AVX2 software — and **never** repartition
  the internal disk if you want to keep Orbis and your saves.

Full analysis and evidence: `research/00-executive-summary.md`.
