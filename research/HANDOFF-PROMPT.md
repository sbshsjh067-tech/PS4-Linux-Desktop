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

---

## 4) If the coding chat cannot see `research/` (the "files not found" case)

This happened once and it will happen again, because the two workstreams may live in **different clones**.
The research lives on the public repo, in its own branch — it is **not** merged into the product branch.

**Cause of the confusion:** the research branch was created from the same `Initial commit` but contains only
`README.md`, `AGENTS.md` and `research/`. The coding workspace is a *separate* clone with 90+ files on `main`
and **no remote configured**, so `find`, `git ls-files` and `git branch -a` there will never show it.

**Fix — import only the research paths, touch nothing else:**

```bash
cd /path/to/the/coding/repo

# 1. fetch the research branch (no branch switch, no merge commit)
git fetch https://github.com/sbshsjh067-tech/PS4-Linux-Desktop.git arena/8145ca4a-ps4-linux-desktop

# 2. import ONLY the research files into the current working tree
git checkout FETCH_HEAD -- research AGENTS.md

# 3. verify (expect 20 files in research/)
ls research/ | wc -l
git status --short | head
```

**Do not** import `README.md` from that branch — it is a research-only landing page and would overwrite the
product README. The research branch's `README.md` is not part of the hand-off.

**Alternative (no network access):** paste the contents of these six files into the chat, in this order:
`AGENTS.md`, `research/00-executive-summary.md`, `research/10-coding-tickets.md`,
`research/06-issues-registry.md`, `research/backlog.yaml`, `research/decisions.md`.

**Then continue normally:** AGENTS → 00 → 10 → 06 → 02/03/04 → backlog/decisions, and reply with the
understanding summary + plan + conflicts **before** any code.

---

## 5) Reconciliation when prior work already exists (expected, not a failure)

The coding workstream may already have a Phase-0 build (e.g. another kernel version, a diagnostic initramfs,
a desktop image, a PS4 package). That is **good news**, not a conflict to hide — but the merge follows rules.

### 5.1 Precedence

1. **Measured evidence beats documentation.** Any number produced by a real run (boot time, idle RAM,
  renderer string, fps) overrides a `[VERIFIED]`/`[ESTIMATE]` line in the handbook.
2. **Documents do not silently change** — the run goes into `research/results/` first, then the registry and
  the handbook are updated, then a decision is re-opened if needed.
3. **Decisions `D-01…D-06` are binding until amended by a new entry in `research/decisions.md`.** The coding
  chat cannot amend them; it reports the contradiction and asks.
4. Safety decisions (`D-01` no internal-disk writes, `D-02` firmware frozen, thermal floor) are **not**
  negotiable by evidence — they are about preventing irreversible damage, not about performance.

### 5.2 How to report a conflict (template the coding chat must use)

```yaml
conflict:
  ref: D-04            # decision or handbook line
  build_does: "ships Mesa 26.0.8 / no pinned DXVK"
  evidence: "results/EXP-009/2026-11-14/ (GPU hang at 14 s)"
  proposed_resolution: "adopt D-04 pins; rebuild image with /opt/ps4-mesa/25.3.5"
  needs_research_decision: true
```

### 5.3 Known contradictions to expect on day one

| Handbook says | A Phase-0 build may already do | Resolution |
|---|---|---|
| Kernel from the 7.x PS4 trees (`03`, `07`) | boot a 6.15.4-based kernel | both are valid; keep the *working* one as the baseline, register the alternative as a candidate in `T-002` matrix, decide by EXP-002 |
| `D-01`: USB root only, internal disk read-only | a build that partitions or installs to the internal disk | **stop that path**; re-run on USB. Data loss is irreversible (Orbis + saves) |
| `D-04`: Mesa pinned (25.3.5 / 26.0.4), DXVK ≤ 2.7.1, Proton ≤ 11 | distro Mesa, whatever DXVK/Proton ships | must be pinned before Steam work; record the current versions first (`T-007` audit) |
| `D-05`: Plasma product + XFCE fallback | a Debian+Plasma image exists | keep it; add the XFCE recovery session and the thin profile (`T-008`, `T-009`) |
| Idle RAM target ≤ 900 MB (`04` §7) | e.g. "933 MiB desktop" | clarify the unit (RAM at idle? image size?) and record it as EXP-003 evidence either way |
| 14-day-old `README.md` claim of "fully functional" | reality is partial | `00-executive-summary.md` §2 is the claim set; docs must match it |

### 5.4 What the coding chat must send back after reading

1. Understanding summary (≤ 20 lines).
2. Plan for `T-001 → T-004 → T-002 → T-003 → T-006`.
3. A `conflict:` block for **every** contradiction with the existing build, including ones it believes are
   harmless.
4. Anything it needs from research before writing code.

Only then does implementation start.
