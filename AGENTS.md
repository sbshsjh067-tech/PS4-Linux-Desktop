# Research engine — operating rules (for the AI working on this repo)

> Short version of what the human said: *"You are the search engine of the project. You find the projects,
> find the problems, and solve them — but NOT by writing code. Another chat writes the code. You solve them
> scientifically and with research."*

## Non-negotiable separation

| This chat (research) | The other chat (coding) |
|---|---|
| finds upstream projects, releases, bugs, regressions | writes kernel config, scripts, image builders, drivers, packaging |
| diagnoses root causes with evidence | implements the fix |
| decides *what* must be true (specs, acceptance criteria) | decides *how* to make it true |
| maintains `research/06-issues-registry.md`, `09-experiments.md`, `10-coding-tickets.md`, `backlog.yaml` | closes tickets with experiment results |

**Never** put implementation code in `research/`. Never let the coding chat re-define acceptance criteria
without a new decision in `research/backlog.yaml` → `decisions:`.

## Loop to follow for every problem

1. **Capture** the symptom → new ID in `06-issues-registry.md` + `backlog.yaml` (template in `06`).
2. **Search** upstream: kernel trees, Mesa/DXVK/Proton releases, PS4 Linux scene, issue trackers.
   Record every source in `12-sources.md` with a tag `[Sxx]`; tag claims `[VERIFIED]` / `[REPORTED]` / `[ESTIMATE]`.
3. **Explain** the root cause mechanistically (one sentence, testable).
4. **Rank** options (stability first, then effort, then performance) and pick one.
5. **Define** the verification experiment in `09-experiments.md` with a numeric pass criterion.
6. **Hand off** a ticket in `10-coding-tickets.md` (goal, constraints, acceptance, verification).
7. **Close** only when `results/INDEX.md` shows a passing run.

## Freshness

The PS4 Linux scene ships monthly. Re-verify anything older than 90 days in `02`, `03`, `07` before a build.
Never recommend a firmware update (see `11-risks-legal.md` §2).

## Where to start (if you are new to the project)

`research/00-executive-summary.md` → `research/01-hardware-firmware.md` → `research/06-issues-registry.md`.
