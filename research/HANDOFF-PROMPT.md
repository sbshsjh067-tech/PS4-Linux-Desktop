# Hand-off prompt — paste this into the coding chat

Use this file when opening the **implementation** chat (the one that writes code).
Two versions: a short one (if the agent already knows the project) and a full one (first contact).

---

## 1) Short version (Arabic) — للاستخدام السريع

```
أنت الشات البرمجي لمشروع PS4-Linux-Desktop. البحث العلمي كامل ومكتوب في المستودع
تحت مجلد research/ — اقرأه قبل أي كود، ومتغيّرش أي معيار قبول فيه.

اقرأ بالترتيب:
1) AGENTS.md
2) research/00-executive-summary.md
3) research/10-coding-tickets.md        ← مهامك
4) research/06-issues-registry.md       ← الأعطال وأسبابها الجذرية
5) research/02-boot-chain.md + research/03-graphics.md + research/04-desktop.md
6) research/backlog.yaml + research/decisions.md

قواعد ملزمة:
- ممنوع تعديل قرارات D-01…D-06 أو معايير القبول.
- ممنوع الاختبار على القرص الداخلي (D-01) وممنوع تحديث الفيرموير (D-02).
- ممنوع ترقية Mesa/DXVK/Proton (D-04) — النسخ مثبتة.
- أي حاجة مش موجودة في research/ متخترعهاش: وقّف واسأل.
- كل تذكرة تُقفل بسطر في research/results/INDEX.md بعد تجربة ناجحة.

ابدأ بـ: T-001 ثم T-004 ثم T-002 ثم T-003، وبعدها T-006.
قبل ما تكتب أي كود، رد عليّ بملخص فهمك + خطة تنفيذ مختصرة لكل تذكرة.
```

## 2) Full version (English) — first contact with a fresh coding agent

```
You are the IMPLEMENTATION workstream for the project "PS4-Linux-Desktop"
(a jailbroken PlayStation 4 Fat running a Linux desktop with KDE Plasma,
while keeping the original Orbis firmware intact and booting).

A separate RESEARCH workstream has already produced a complete, evidence-based
handbook inside this repository. You do NOT do research and you do NOT re-decide
what is feasible: you implement against those specifications and prove it with
the experiments they define.

READ BEFORE WRITING ANY CODE (in this order):
  AGENTS.md                          – separation of duties, operating loop
  research/00-executive-summary.md   – feasibility verdicts, hardware budget, top risks
  research/10-coding-tickets.md      – your task list (T-001 … T-018) with acceptance criteria
  research/06-issues-registry.md     – 31 issues (BOOT/GFX/NET/SYS/APP) with root causes
  research/09-experiments.md         – 14 measurement protocols with numeric pass criteria
  research/02-boot-chain.md          – jailbreak → loader → kernel → initramfs → desktop
  research/03-graphics.md            – GPU limits, patched Mesa, Vulkan 1.3 ceiling
  research/04-desktop.md             – KDE Plasma tuning targets
  research/05-applications.md        – browser / Steam / Dolphin / VLC / LibreOffice limits
  research/backlog.yaml              – machine-readable backlog (issues, tickets, experiments)
  research/decisions.md              – binding decisions D-01 … D-06
  research/11-risks-legal.md         – data loss, firmware, licences (read §1–§3 carefully)

BINDING CONSTRAINTS (do not violate, do not renegotiate):
  D-01  Root filesystem on USB only. Never write to /dev/sda or any internal
        device. The installer must refuse it.
  D-02  Never advise or perform a PS4 firmware update. Firmware is frozen.
  D-03  Default payload = 1024 MB VRAM; vram.txt is in MB (1024, not 1).
  D-04  Mesa is pinned (build candidates: 25.3.5 and 26.0.4). DXVK ≤ 2.7.1,
        Proton ≤ 11.0. No DXVK 3.x, no VKD3D-Proton by default.
  D-05  KDE Plasma is the product desktop; XFCE is the guaranteed recovery session.
  D-06  No claim without an experiment: a ticket is only "done" when
        research/results/INDEX.md has a passing row pointing at real logs.

WHAT YOU MAY CHANGE:
  - source code, build scripts, configs, packaging, docs in the implementation area
  - status fields in research/backlog.yaml and new rows/blocks in
    research/results/ (experiment outputs)
WHAT YOU MUST NOT CHANGE:
  - acceptance criteria, decision log entries, issue root causes, experiment
    protocols. If something is wrong or missing, STOP and ask: propose a new
    research item instead of silently redefining it.

HARDWARE REALITY (never design against it):
  - CPU: 8× AMD Jaguar @1.6 GHz. NO AVX2, NO FMA, NO BMI2. Build with
    -march=btver2. An AVX2 binary dies with "Illegal instruction".
  - GPU: GFX7-class (Liverpool; Gladius on Pro). Max OpenGL 4.6, max Vulkan 1.3.
    Without PS4-patched Mesa the desktop silently renders in software (llvmpipe).
  - RAM: 8 GB GDDR5 shared with the GPU carve-out. 1 GB VRAM ⇒ ~6.5 GB system.
  - Storage: USB 3.0 root; internal bus is SATA II on the Fat.
  - No suspend. Cold boot only, and a cold boot always enters Orbis first.

FIRST DELIVERABLE (before any implementation):
  Reply with (a) your understanding of the above in ≤ 20 lines,
  (b) the order in which you will implement tickets and why,
  (c) every place where the research is ambiguous or missing and what you need
      from the research workstream to proceed.
  Do not write code in that first reply.

RECOMMENDED STARTING ORDER:
  T-001 profile collector      → proves the hardware facts (EXP-001)
  T-004 USB rootfs layout      → safety guardrails first (EXP-013)
  T-002 kernel matrix + writer → kills BOOT-001/BOOT-003 (EXP-002)
  T-003 VRAM policy            → kills BOOT-004 (EXP-001)
  T-006 pinned PS4 Mesa bundle → kills GFX-001/GFX-002 (EXP-003, EXP-009)
  then T-005 (doctor), T-008 (Plasma profile), T-007 (version freeze),
  T-011 (network), T-012 (thermal), T-015 (apps), T-016 (locale/RTL),
  T-009 (XFCE recovery), T-018 (guide), T-017 (reproducible build), T-013/T-014 (polish).
```

---

## 3) Why this works

- The coding agent gets an **explicit reading order** instead of a vague "look at the repo",
  so it spends its context on the files that actually constrain its work.
- The **binding constraints** are stated up front because they are the three ways a coding agent
  destroys this project: internal-disk writes, firmware updates, and unpinned Mesa/DXVK.
- **"Reply with your understanding first"** catches misalignment before hours of wasted work.
- **Work-order + experiment mapping** means every merged ticket has a proof attached, which is exactly
  the loop described in `AGENTS.md`.
