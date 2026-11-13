# 06 — Issues registry (problem → scientific solution)

The operational core of this project. Every bug found on hardware gets an ID here **before** code is
touched. The coding chat implements from this file; the research chat maintains it.

**ID scheme:** `BOOT-nnn` (boot chain), `GFX-nnn` (graphics/Mesa), `NET-nnn` (network), `SYS-nnn`
(system/thermal/storage), `APP-nnn` (applications).

**Status values:** `open` → `diagnosed` (root cause + evidence) → `solution-proposed` (option chosen,
spec written) → `in-implementation` → `verified` (test passed with numbers) → `closed`.
`wontfix` only with a written reason.

Template (copy this for new entries):

```yaml
- id: XXX-000
  title: short symptom
  status: open
  severity: blocker | high | medium | low
  scope: {models: [Aeolia|Belize|Baikal], kernel: "7.x", mesa: "25.3.5", fw: "13.52"}
  symptom: what the user sees
  reproduction: numbered steps
  evidence: logs, links, source lines  (use [Sxx] from 12-sources.md)
  root_cause: one sentence, mechanistic
  options: [ {name, cost, risk, verdict} ]
  chosen_solution: what + why
  verification: EXP-xxx with pass criteria
  residual_risk: ...
```

---

## BOOT — boot chain

### BOOT-001 — Light stays white, Linux never starts · `diagnosed` · severity: blocker
- **Scope:** any model; most often wrong kernel family.
- **Symptom:** payload sent, LED never turns blue, no video for >20 s.
- **Evidence:** field guidance "white light = wrong kernel or payload, blue = kernel started" [S16];
  runtime southbridge detection exists precisely because model lists are unreliable [S14].
- **Root cause:** bzImage built for a different southbridge (Aeolia/Belize ↔ Baikal) or loader not
  matching firmware.
- **Options:** (a) swap kernel family; (b) use firmware-agnostic loader v25+; (c) verify loader/FW support
  table. **Chosen:** (b) + (c), (a) as manual fallback.
- **Verification:** EXP-001 boot 3× per kernel candidate; pass = blue light + desktop ≤ 2 min, 3/3.

### BOOT-002 — `mounting LABEL=… failed` in rescue shell · `diagnosed` · severity: high
- **Root cause:** rootfs label missing/mistyped, USB not enumerated in time, or stale LABEL baked into
  the initramfs from an old install.
- **Options:** (a) rewrite label; (b) `root=UUID=`; (c) increase root-wait timeout (`ps4_rootwait=30`);
  (d) full USB power-cycle.
- **Chosen:** (c) as default in images + (a/b) documented. Precedent: `ps4_rootwait` exists for slow USB [S17].
- **Verification:** EXP-002 variant with a deliberately slow USB 2.0 stick → must still boot.

### BOOT-003 — Two kernel layouts, mixed together · `diagnosed` · **rewritten 2026-11-13**
- **Original wording (withdrawn):** "USB `bzImage` always wins over `/data/linux/boot`". That came from a
  single community note about one loader version; the loader repositories are now unreadable (404), so the
  precedence cannot be verified and a rule must not rest on it. See `13-...` §3 C1.
- **Real root cause:** there are two legitimate layouts — (A) kernel on a FAT32 `PS4BOOT` partition of the
  USB, (B) kernel in `/data/linux/boot` via FTP — and a console that ends up with a kernel in *both* places
  boots whichever the loader happens to prefer, producing unreproducible "it worked yesterday".
- **Solution:** the layout is declared in `profile.yaml` (`boot.layout`); pre-flight refuses when a `bzImage`
  exists in both locations; every shipped kernel carries a sha256 recorded in the manifest.
- **Verification:** EXP-001 step 0 asserts the declared layout matches the files actually present.

### BOOT-004 — `vram.txt` written as `1` (GB) instead of `1024` (MB) · `diagnosed`
- **Root cause:** loader v25 changed the unit convention; invalid values fall back silently to payload
  default [S14].
- **Impact:** user believes they have 1 GB VRAM; may actually run 1024 default anyway — but a wrong large
  value silently eats RAM.
- **Solution:** the image writes `vram.txt` itself and prints effective value to the log at boot
  (`dmesg`/`/proc/cmdline` check).
- **Verification:** EXP-001 asserts effective VRAM == requested.

### BOOT-005 — Black screen 1–2 minutes after payload, then desktop · `closed (expected behaviour)`
- **Root cause:** normal kernel+initramfs handoff latency; nothing is wrong [S17].
- **Solution:** documentation + progress LED/beep trick (optional, coding ticket T-013).
- **Verification:** measure the delay in EXP-002.

### BOOT-006 — Linux boots but display manager shows black screen · `diagnosed` · severity: high
- **Scope:** HDMI bridge / modeset stage, more common on Slim/Pro; Pro also fixed by PS4-side settings.
- **Root cause:** display bridge not driven correctly at modeset, or compositor picking an unsupported mode.
- **Evidence:** blackscreen fixes at DM stage in kernel branches [S03]; HDMI keep-alive service in
  PS4 Multiboot [S17]; PS4-side HDR/Deep Color off fixes Pro [S19].
- **Options:** (a) PS4 settings: HDR off, RGB automatic, Deep Color automatic; (b) `Ctrl+Alt+F2` then
  `F7/F1`; (c) boot Wayland session; (d) HDMI keep-alive service in image; (e) different kernel branch.
- **Chosen:** (a)+(d) shipped by default, (b/c) in the doctor script.
- **Verification:** EXP-008 (30 min idle + 10 DM restarts) pass 10/10.

### BOOT-007 — Console hangs after jailbreak page, needs cold start · `reported` (14.00 path)
- **Root cause:** exploit host state; documented as a failure case of the 14.00 Afterglow host [S24].
- **Solution:** if on ≤13.52, stay there. If on 14.00, always start from the host index page, never from a
  restored session; keep the PC-served pages running.
- **Verification:** n/a (out of our control) — document only.

### BOOT-008 — Reboot from Linux returns to Orbis instead of Linux · `closed (by design)`
- **Root cause:** no Linux boot entry; cold boot always enters Orbis [S19].
- **Solution:** document the loop; provide "send payload" helper on a phone/PC (T-014).

## GFX — graphics

### GFX-001 — Desktop renders but is slow, CPU pegged · `diagnosed` · severity: blocker for UX
- **Root cause:** stock Mesa has no PS4 PCI IDs → llvmpipe software rendering. RadeonSI only recognises
  Liverpool/Gladius after the patches [S06][S07].
- **Solution:** ship patched Mesa in a private prefix (`/opt/ps4-mesa`) and select it for the session;
  doctor script fails loudly if `glxinfo -B` shows `llvmpipe`.
- **Verification:** EXP-003; pass = `renderer string` contains `LIVERPOOL`/`GLADIUS`, idle CPU ≤ 8 %.

### GFX-002 — GPU hang 10–20 s into a DXVK game · `diagnosed` · severity: high
- **Root cause (mechanistic, verified 2026-11-13):** RADV enables **HiZ (HTILE)** on Liverpool/Gladius, and
  HiZ hangs the `gfx` ring on the first DXVK frame (*"ring gfx timeout"*); radeonsi's own HiZ path is fine.
  `blue0x1/ps4-multiboot` patch `0002-radv-ps4-no-hiz.patch` sets `use_hiz = false` for both chips
  [S43]. Field evidence: DXVK+ACO hangs after ~20 s while OpenGL is stable and `glxgears` shows 1621 fps
  (no thermal/clock limit) [S08].
- **Diagnostic that needs no rebuild:** launch the title with `RADV_DEBUG=nohiz`; if the hang disappears,
  the cause is confirmed on that machine.
- **Options:** (a) Mesa **26.2.5 + patch 0002** (fixes the defect); (b) Mesa 25.3.5 (field-proven,
  control); (c) Mesa 26.0.4 (field-proven); (d) `RADV_DEBUG=llvm` → pipelines fail to compile, 
  **not a fix** [S08]; (e) `PROTON_USE_WINED3D=1` (OpenGL, slower but stable) [S08].
- **Chosen:** (a)/(b) pinned; (e) as documented fallback. Detect at runtime and refuse unsupported Mesa.
- **Verification:** EXP-009 (420 s / 240 s stability runs reproducing the published protocol).

### GFX-003 — Corrupted scan-out / diagonal tearing on some Belize units · `diagnosed`
- **Root cause:** tiled scan-out buffers + display path on GFX7.1 boards (`AMD_DEBUG=notiling` fixes,
  `nodcc` does not) [S15].
- **Solution:** ship a toggle in the doctor script; default on for affected board revisions only.
- **Verification:** EXP-006 with before/after screenshots.

### GFX-004 — Vulkan apps demand 1.4 / newer DXVK refuses to start · `diagnosed`
- **Root cause:** hardware ceiling — Vulkan 1.3 max on GFX6/7 [S09]; DXVK 3.x requires 1.4 [S12].
- **Solution:** pin DXVK ≤2.7.1, Proton ≤11, and *block* package updates that pull newer DXVK
  (Lutris/Heroic manage their own DXVK! set their versions explicitly).
- **Verification:** EXP-009 asserts `vulkaninfo --summary` API ≤ 1.3 and a D3D11 test boots.

### GFX-005 — Plasma compositor black screen after Mesa update · `diagnosed`
- **Root cause:** a radeonsi regression in the compositing path in one Mesa series; fixed in 26.3 [S11].
- **Solution:** pinning (GFX-002) + upgrade only through EXP-003/EXP-008 gate.
- **Verification:** EXP-008 after every Mesa change.

### GFX-006 — Pro (Gladius) much slower than expected · `diagnosed`
- **Root cause:** Gladius register programming missing in older kernels → clock/register misconfig [S03].
- **Solution:** kernel with "Gladius registers fixed" (feeRnt 5.15/6.15 line, later trees) [S03][S30].
- **Verification:** EXP-003 on a Pro if available; else mark Pro "supported, untested" (project is Fat).

## NET — networking

### NET-001 — Wi-Fi missing entirely · `diagnosed` · severity: medium
- **Root cause:** chip lottery: Marvell 8797/8897 vs MediaTek MT7668; driver/firmware differs, and the
  current running kernel may lack the right branch [S03][S05].
- **Options:** (a) kernel branch with the matching driver; (b) **Ethernet**; (c) USB Wi-Fi dongle (works,
  some users report USB BT dongles not working [S21]).
- **Chosen:** (b) as default, (a) per-chip, (c) documented.
- **Verification:** EXP-011.

### NET-002 — Wi-Fi fails only after a reboot with MAC randomization · `diagnosed`
- **Root cause:** PS4 combo chip often fails with randomized MAC / WPA3-only.
- **Solution:** NetworkManager override `wifi.scan-rand-mac-address=no`,
  `wifi.cloned-mac-address=preserve`; prefer 2.4 GHz + WPA2 [S17].
- **Verification:** EXP-011 connects 5/5 after cold boots.

### NET-003 — Ethernet link up but no traffic / 1 Gbps negotiation issues · `reported`
- **Root cause:** link negotiation defaults; some routers/switches disagree at GbE.
- **Solution:** force `100 Mb/s full duplex` via `ethtool`/NM link negotiation [S39].
- **Verification:** EXP-011.

### NET-004 — Wi-Fi association performed by Orbis before kexec leaves interface dead · `reported`
- **Root cause:** the Wi-Fi module keeps its association across kexec; the new kernel's supplicant
  conflicts and the interface disappears until reboot [S37].
- **Solution:** instruct users to disconnect Wi-Fi in Orbis before loading the payload (or use Ethernet).
- **Verification:** EXP-011.

## SYS — system

### SYS-001 — Suspend/sleep breaks the machine · `wontfix (hardware/firmware)` · severity: medium
- **Root cause:** no working S3/ACPI path this Linux build; suspend breaks boot [S16][S19].
- **Solution:** mask targets; disable dim/blank in Plasma power settings; document "cold boot only".
- **Verification:** EXP-008 confirms masked units.

### SYS-002 — Fan stays quiet while SoC gets hot · `solution-proposed` · severity: high (hardware safety)
- **Root cause:** default fan curve comes from the PS4 firmware; Linux needs the ICC driver + a threshold
  (45–85 °C), and not every kernel exposes it [S22][S23][S18].
- **Resolved upstream (2026-11-13):** `feeRnt@7.0-Clean` ships `drivers/ps4/ps4-fan.c`, a hwmon driver
  exposing `temp1_input` (RO, milli-°C), `temp1_crit` (**RW, 45000–85000** = the ICC 45–85 °C range) and
  `fan1_input` (RO, RPM). Its header also documents that the legacy `ps4fancontrol` corrupted the EMC fan
  config (RPM reads 0 until a hard power cycle) because it wrote more than byte[5] [S43].
  → On candidate A: use hwmon, do **not** write ICC from userspace. On the 6.15.4 fallback (no `ps4-fan.c`):
  `ps4fancontrol` with the same 70–75 °C default and 65 °C floor.
- **Options:** (a) kernel with hwmon/ICC fan support; (b) `ps4fancontrol --set 70`; (c) accept default
  (unsafe under sustained load); (d) setting too-low thresholds → permanent jet engine [S23].
- **Chosen:** (a) as kernel requirement, (b) default 70–75 °C, warn about (d).
- **Verification:** EXP-012: 20 min stress (`stress-ng --cpu 8`) with temp logging; pass = temp stable
  < 80 °C and no shutdown.

### SYS-003 — Clock wrong (1970) after boot · `diagnosed`
- **Root cause:** no RTC exposed to this Linux build [S19].
- **Solution:** `systemd-timesyncd` enabled by default; if offline, manual time or phone hotspot sync.
- **Verification:** EXP-002 asserts NTP sync within 60 s of network.

### SYS-004 — USB root filesystem goes read-only / errors under heavy IO · `reported` · severity: high
- **Root cause:** cheap USB sticks, UAS quirks, or improper unmount on power loss; Baikal USB write
  issues in some installers [S17].
- **Solution:** mount with `errors=remount-ro` (ext4 default), `noatime`, `commit=30`; fsck on boot; use
  quality USB 3.0 SSD; monitor `dmesg` for resets; never yank the stick.
- **Verification:** EXP-013 (write amplification test + power-loss test).

### SYS-005 — Out-of-memory kills Plasma with 4 GB VRAM payload · `diagnosed`
- **Root cause:** VRAM carve-out reduces system RAM to ~4 GB; Plasma + browser + Steam exceed it.
- **Solution:** document payload ↔ workload table (`01` §4); enable zram; OOM score tuning optional.
- **Verification:** EXP-003 memory profile per payload.

### SYS-006 — Audio missing (HDMI) · `open` · severity: medium
- **Root cause:** HDMI audio codec support varies by kernel branch [S30]; some users report no audio
  device at all.
- **Options:** (a) USB audio (works); (b) kernel branch with HDMI audio; (c) Bluetooth audio (flaky).
- **Chosen:** (a) default recommendation; (b) tracked.
- **Verification:** EXP-010 audio rows.

### SYS-007 — Bluetooth headset/controller pairing lost every boot · `diagnosed`
- **Root cause:** pairing keys live in the PS4 firmware path, not copied to Linux (known, "will be fixed
  at some point") [S38].
- **Solution:** re-pair per boot (script helper), or use USB cable.
- **Verification:** EXP-010.

### SYS-008 — Console loses 4–8 GB free space per installed distro on internal installs · `diagnosed`
- **Root cause:** per-distro image files in `/user/home` (16 GB suggested + 10 GB kept free for PS4) [S17].
- **Solution:** USB installs by default; document sizing.

## APP — applications

### APP-001 — Steam game launches then black screen/crash · `diagnosed`
- **Root cause:** Proton Experimental → DXVK 3.x → Vulkan 1.4 requirement [S12][S13].
- **Solution:** force Proton 11.0/9.0-4; per-game compatibility override; verify DXVK version.
- **Verification:** EXP-009 includes one D3D9 and one D3D11 title.

### APP-002 — Chromium videos drop frames / CPU 100 % · `diagnosed`
- **Root cause:** the reference PS4 Mesa bundle is built `-Dgallium-va=disabled -Dvideo-codecs=` → **VA-API is
  compiled out**, not merely experimental [S43]; plus VP9/AV1 software decode on Jaguar is too slow.
- **Solution:** prefer H.264 sources; enable VA-API only after EXP-005 proves UVD; limit tabs.
- **Verification:** EXP-004.

### APP-003 — App dies with "Illegal instruction (core dumped)" · `diagnosed`
- **Root cause:** binary requires AVX2/FMA/BMI2 that Jaguar lacks [S32].
- **Solution:** rebuild with `-march=btver2`; ban AVX2 packages in the image; document.
- **Verification:** `hwinfo`/`lscpu` flags audit in EXP-001.

### APP-004 — LibreOffice cold start 15 s+, UI stutter · `diagnosed`
- **Root cause:** CPU + USB IO; Java/OpenCL/OpenGL options make it worse.
- **Solution:** ship tuned `registrymodifications.xcu` (Java off, OpenCL off, graphics off).
- **Verification:** EXP-014 startup timing.

### APP-005 — Emulator (Dolphin) low FPS on Wii titles · `diagnosed (hardware)`
- **Root cause:** CPU-bound, per the PS4-native fork's own notes [S28].
- **Solution:** ship recommended settings; "Emulated CPU clock: Auto"; frame-limit Auto 60/30; accept 40 fps.
- **Verification:** EXP-015 FPS log on 2–3 known titles.

---

## Backlog quick view

| ID | Severity | Status | Owner |
|---|---|---|---|
| BOOT-001…008 | blocker→low | mixed | coding (T-001…T-006) |
| GFX-001…006 | blocker→medium | mixed | coding (T-007…T-010) |
| NET-001…004 | medium | mixed | coding (T-011) |
| SYS-001…008 | high→low | mixed | coding (T-012) |
| APP-001…005 | medium | mixed | coding (T-015) |

Full machine-readable version: `backlog.yaml`.
