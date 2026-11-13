# 09 — Experiment protocols

A claim without a number is an opinion. Every experiment below is copy-pasteable, has pass/fail criteria,
and produces a result block that gets pasted back into `06-issues-registry.md`.

**Rules**
1. Run experiments on the **target console** (not a PC) unless stated.
2. Record: date, profile (from `profile.example.yaml`), kernel, Mesa, payload VRAM.
3. Save raw logs under `results/<EXP-ID>/<date>/`.
4. Never mark an issue `verified` without a completed result block.

---

## EXP-001 — Baseline hardware & software facts · prerequisite for everything

```bash
# identity
cat /etc/os-release; uname -a
lscpu | sed -n '1,25p'; lscpu | grep -io 'avx2\|fma\|bmi2' | sort -u   # expect: EMPTY
lspci -nnk | grep -A3 -i vga
cat /proc/cmdline
# what the loader actually gave us
grep -i 'memory\|vram' /proc/cmdline /var/log/* 2>/dev/null
free -h; cat /proc/meminfo | head -3
# graphics identity
glxinfo -B 2>/dev/null | grep -i 'renderer\|OpenGL version'
vulkaninfo --summary 2>/dev/null | grep -i 'apiVersion\|deviceName\|driverName'
# thermal
sensors 2>/dev/null; ls -l /dev/icc 2>/dev/null
# storage
lsblk -f; mount | grep ' / '
```
**Pass:** renderer contains `LIVERPOOL`/`GLADIUS`, Vulkan API = 1.3.x, `avx2` absent, root on USB ext4.

**Result block**
```yaml
exp: EXP-001
date: 
profile: {model: , southbridge: , fw: , payload_vram_mb: }
kernel: 
mesa: 
observed: {ram_total: , renderer: , vulkan: , temp_idle: , root_dev: }
pass: true|false
notes: 
```

---

## EXP-002 — Boot latency & reliability (10 cold boots)

**Procedure:** for i in 1..10: full power-off → Orbis → jailbreak → send payload → start timer → desktop reachable.
Record each phase: t_jailbreak, t_payload_sent, t_blue_light, t_login, t_desktop.

**Pass:** ≥ 9/10 boots reach desktop; desktop ≤ 120 s; no `LABEL` errors.
**Fail actions:** BOOT-001/002/005/006 checks.

```yaml
exp: EXP-002
boots: [{n: 1, phases: [..], ok: true, failure_id: null}, ...]
p95_total_s: 
pass: 
```

---

## EXP-003 — Desktop performance & memory

```bash
# idle profile (Plasma running, nothing else), sample 60 s
free -h; vmstat 1 60 | awk 'NR>2{s+=$13;n++} END{print "avg idle CPU%:",s/n}'
ps_mem 2>/dev/null | sort -k3 -h | tail -10     # or: ps aux --sort=-rss | head -10
# interaction
# measure: (a) window drag smoothness, (b) Dolphin open time, (c) Konsole open time
```
**Pass:** idle RAM ≤ 900 MB, idle CPU ≤ 8 %, no compositor "software" warning in `journalctl -b | grep -i kwin`.

```yaml
exp: EXP-003
idle_ram_mb: 
idle_cpu_pct: 
app_open_ms: {dolphin: , konsole: }
renderer: 
pass: 
```

---

## EXP-004 — Browser workload

| Test | Method | Pass |
|---|---|---|
| Page load | 3 fixed sites, cold cache | ≤ 6 s each |
| JS | Speedometer 2.1 in Firefox/Chromium | record score (no target; baseline for regressions) |
| Video 1080p H.264 | YouTube "stats for nerds" codec avc1, 5 min | ≥ 24 fps, audio smooth, CPU ≤ 90 % |
| Video 1080p VP9 | same, codec vp09 | record (likely fails → document) |
| Tabs | 6 heavy tabs | no OOM, system responsive |

```yaml
exp: EXP-004
browser: 
speedometer: 
h264: {fps: , dropped: , cpu_pct: }
vp9:  {fps: , dropped: , cpu_pct: }
pass: 
```

---

## EXP-005 — Display power management (`amdgpu.dpm=1`)

**Background:** PS4 kernels ship with `dpm=0` disabled for clock/PM stability (S04). Enabling it could
reduce heat/noise, but has historically broken GPU init.

**Procedure:** boot 5× with `amdgpu.dpm=1`, run EXP-003 + a 10-min browser session, log `journalctl -b -k | grep -i amdgpu`.
**Pass:** 5/5 boots, no GPU reset, no flicker. **Fail:** revert to `dpm=0` (documented default).

---

## EXP-006 — Scan-out corruption (`AMD_DEBUG=notiling`)

**Procedure:** reproduce GFX-003 (diagonal tear / scanlines) with default, then with `AMD_DEBUG=notiling`.
**Pass:** toggle cleanly removes corruption; screenshots before/after stored.

---

## EXP-007 — (reserved) GL/VK overrides
Do **not** override `MESA_GL_VERSION_OVERRIDE`. This slot exists to record that decision and the reasons.

---

## EXP-008 — Stability soak

**Procedure:** 30 min idle Plasma + 10 display-manager restarts (`systemctl restart sddm`) + 3 HDMI
source switches (if a monitor) + 1 browser session.

**Pass:** zero GPU hang (`journalctl -k | grep -i 'amdgpu.*error\|ring.*timeout'` empty), desktop returns after every restart.

---

## EXP-009 — Steam/DXVK compatibility & GPU-hang gate

**Prerequisite:** EXP-001 confirms Vulkan 1.3.

| Step | Pass |
|---|---|
| `vulkaninfo --summary` | API 1.3.x, PS4 GPU |
| D3D11 test title (e.g. a free D3D11 demo or Portal 2 class title) via Proton ≤ 11 | launches, 10 min, no hang |
| D3D9 test title via DXVK 2.x | launches, 10 min, no hang |
| Record Mesa + DXVK + Proton versions | must be ≤ pinned |
| Repeat with Mesa candidate B (25.3.5 vs 26.0.4) | one of them stable ≥ 400 s |

**Fail → GFX-002 actions** (switch Mesa build, do not raise DXVK version).

```yaml
exp: EXP-009
mesa: ; dxvk: ; proton: 
titles: [{name: , api: D3D11, minutes: , fps_avg: , hang: false}]
pass: 
```

---

## EXP-010 — Peripheral matrix

| Device | Connect | Pass |
|---|---|---|
| DS4 wired | USB | detected as gamepad (`evtest`/`jstest`), input in Plasma settings |
| DS4 BT | pair → reboot → pair | document actual behaviour (expected: lost) |
| USB keyboard/mouse | both | input, no lag |
| USB audio | play test tone | sound, no crackle |
| HDMI audio | same | record yes/no |
| USB stick | `dd` 1 GB write | ≥ 20 MB/s, no reset in `dmesg` |
| Webcam | `ffplay /dev/video0` | image, CPU cost noted |

---

## EXP-011 — Network matrix

| Case | Pass |
|---|---|
| Ethernet cable, cold boot ×5 | IP within 20 s, `ping 1.1.1.1` 0 % loss |
| Ethernet 1 GbE vs forced 100 Mb | record which negotiates (NET-003) |
| Wi-Fi (chip-dependent) | associate 5/5, survive reboot (NET-002) |
| Wi-Fi after Orbis association | document NET-004 behaviour |
| `nmcli` MAC randomization off | 5/5 associations |

---

## EXP-012 — Thermal stress (safety gate)

```bash
# terminal 1
stress-ng --cpu 8 --vm 2 --vm-bytes 512M --timeout 20m
# terminal 2
while :; do date +%T; sensors 2>/dev/null | grep -i -E 'temp|fan'; sleep 30; done | tee thermal.log
```
**Pass:** SoC ≤ 80 °C sustained, no throttling below 1.2 GHz, fan audible but stable, no shutdown, no USB dropout.
**Fail → SYS-002**: set `ps4fancontrol --set 70`, re-run; never below 65 °C (jet-engine risk, S23).

---

## EXP-013 — Storage resilience

| Test | Method | Pass |
|---|---|---|
| Sustained write | `fio --rw=write --size=2G --bs=1M` | no I/O errors in `dmesg` |
| Power loss | hard power-off during write → boot | fsck recovers, desktop reachable |
| USB reset count | `dmesg | grep -c 'reset SuperSpeed'` after 1 h | 0 |

---

## EXP-014 — Office workload
Cold start LibreOffice Writer, open a 20-page .odt, scroll, export PDF. Record timings and RAM.
**Pass:** open ≤ 15 s, scroll smooth, export ≤ 30 s.

---

## EXP-015 — Emulation
Run 3 reference titles (one GC "light", one GC "heavy", one Wii) with DolphinPS4 recommended settings.
Record avg/min fps over 5 min of gameplay and compare to published table in `05` §4.
**Pass:** within 10 % of published numbers; no crash in 15 min.

---

## Measurement toolbox (install in image)

`glxinfo/mesa-utils`, `vulkan-tools`, `drm_info`, `lm_sensors`, `ps_mem`, `stress-ng`, `fio`, `ethtool`,
`iw`, `evtest`, `jstest`, `htop`, `systemd-analyze`, `perf` (optional), `radeontop` (GPU utilisation).

---

## Results index format

`results/INDEX.md` — one line per run:

```
| EXP-009 | 2026-11-20 | Belize 7.0.8 | Mesa 25.3.5 | PASS 420s | results/EXP-009/2026-11-20/ |
```

This index is what the coding chat cites when it closes a ticket.
