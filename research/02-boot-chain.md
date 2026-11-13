# 02 — Boot chain: from Orbis to KDE

Understanding this chain is what separates "it boots sometimes" from a reproducible product.
Every failure the project has seen maps to one of the six stages below.

---

## 1. The chain

```
[1] Orbis OS (PS4 system software)
      │  user opens the jailbreak host page (browser / PC-served page)
      ▼
[2] WebKit exploit → kernel R/W → GoldHEN
      │  GoldHEN provides:  FTP :2121,  payload loader :9020/:9090, BinLoader
      ▼
[3] Linux loader payload  (e.g. linux-1024mb.elf)
      │  detects firmware + southbridge + Pro at runtime, reads vram.txt
      │  loads bzImage + initramfs into memory
      ▼
[4] kexec → Linux kernel  (bzImage from /data/linux/boot/ or USB)
      │  early boot: initramfs
      ▼
[5] initramfs
      │  finds root by LABEL/UUID, mounts it, switch_root
      ▼
[6] root filesystem on USB → systemd → display manager → KDE Plasma
```

Facts per stage:

| Stage | Ownership | Critical detail | Source |
|---|---|---|---|
| [2] Jailbreak | User, before every boot | GoldHEN must be running; exploit re-armed each cold start | [S16][S25] |
| [3] Loader | Payload (`linux-*.elf` / `.bin`) | Firmware-agnostic loader normalises 12.02 → 12.00 offsets and embeds kexec for all supported FW | [S14] |
| [3] VRAM | `vram.txt` (MB!) or payload name | Invalid value → silent fallback to compiled default | [S14] |
| [4] Kernel source | `/data/linux/boot/bzImage` **preferred over USB** | Putting a `bzImage` on the USB breaks the "one USB, all consoles" property | [S16] |
| [4] Kernel choice | southbridge (Aeolia/Belize vs Baikal) | Mismatch = steady **white light**, no boot | [S16][S31] |
| [5] initramfs | Usually shipped inside loader releases | Must match kernel (modules/firmware) | [S14][S17] |
| [6] Rootfs | USB preferred; internal = destructive | Baikal + some installers: USB may be read-only | [S17][S27] |

## 2. File precedence & required files

**Mandatory**

| File | Where | Notes |
|---|---|---|
| `bzImage` | `/data/linux/boot/` (FTP) | Name must be exactly this; per-console kernel |
| `initramfs.cpio.gz` | `/data/linux/boot/` | Must match the kernel build |

**Optional but recommended**

| File | Where | Notes |
|---|---|---|
| `bootargs.txt` | `/data/linux/boot/` | Kernel command line; without it you inherit an old default |
| `vram.txt` | USB root | **MB** (`1024`); bad values fall back silently |
| rootfs image/partition | USB | Label-based discovery (`LABEL=…`) |

**Legacy defaults seen in the wild** (a classic footgun): `root=UUID=<old uuid>`,
`console=ttyS0` and `vram.txt=1` left over from an older loaders [S14]. The first Linux boot of a new
build must verify the effective command line (`cat /proc/cmdline`).

## 3. Boot arguments — what matters and why

Typical working sets used by maintained projects:

```
panic=0 clocksource=tsc consoleblank=0 net.ifnames=0
radeon.dpm=0 amdgpu.dpm=0 drm.debug=0
console=uart8250,mmio32,0xd0340000 console=ttyS0,115200n8 console=tty0
drm.edid_firmware=edid/1920x1080.bin
```

| Argument | Purpose | When to remove |
|---|---|---|
| `amdgpu.dpm=0` / `radeon.dpm=0` | disable dynamic power management — historically required on PS4 clocks | try enabling later for power savings (EXP-006) |
| `drm.edid_firmware=…1080p` | force a known EDID, works around "no signal" on some monitors | remove if the real EDID works |
| `console=…uart8250,mmio32,0xd0340000` | PS4 UART at `0xd0340000` — the **only** debug channel when video dies | keep for any debugging build |
| `consoleblank=0` | HDMI must not blank (display bridge quirks) | keep on desktop images |
| `net.ifnames=0` | stable `eth0/wlan0` names in docs and scripts | keep |
| `amdgpu.dc=1` / `dc=0` | display core on/off — varies by kernel branch | test per kernel |

**UART is the lifeline.** Many PS4 projects debug entirely over UART without a working screen [S18][S29].
Research requirement: a documented UART dongle setup in the hardware test plan.

## 4. Failure modes and the decision tree

| Symptom | Stage | Likely cause | First action |
|---|---|---|---|
| Payload sent, nothing happens | [3] | loader/FW mismatch; wrong port | check FW → loader support table; try :9090 vs :9020 [S16] |
| Light stays **white** >20 s | [4] | wrong kernel for southbridge; bad bzImage | swap Aeolia/Belize ↔ Baikal kernel [S16] |
| Light turns blue but screen black 1–2 min | [4→6] | normal boot latency; EDID/HDMI bridge | wait; power-cycle the display; retry cold [S16][S17] |
| Rescue shell: `mounting LABEL=… failed` | [5] | USB not detected / wrong label | re-plug, check label, cold boot [S16] |
| Boots, then "login screen black" | [6] | display-manager/HDMI bridge at modeset | boot to `multi-user.target`, start session manually; try Wayland/X11 [S21] |
| Everything slow, CPU at 100% with no GPU use | [6] | **stock Mesa** (no PS4 PCI IDs) | `glxinfo -B` → install PS4-patched Mesa [S07][S17] |
| Wi-Fi absent | [6] | wrong kernel branch for the Wi-Fi chip | switch kernel branch; Ethernet fallback [S03][S05][S21] |
| Works once, then never | [2] | exploit state / GoldHEN not re-armed | full power-off, re-jailbreak |

The tree in `06-issues-registry.md` mirrors this table with IDs (`BOOT-001…`).

## 5. Persistence & "dual boot" semantics

- The PS4 has **no UEFI/Linux boot entry**. A cold boot **always** boots Orbis [S19].
- Therefore "dual boot" = *choose at runtime*: boot Orbis → jailbreak → send payload → Linux.
- Linux **restart** returns to Orbis (reboot re-enters the PS4 firmware). Shutdown powers off.
- There is no supported suspend: `sleep.target suspend.target hibernate.target hybrid-sleep.target`
  should be masked in images [S16].

**Product consequence:** the "boot to Linux" step must be reduced to *one tap* eventually (autostart
host + auto-send payload). Research item BOOT-010 tracks feasibility of auto-jailbreak-on-boot hosts —
this is user-land convenience, not a kernel problem.

## 6. Root filesystem placement — decision

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **USB 3.0 SSD/stick (ext4, whole device or labelled partition)** | non-destructive; Orbis untouched; fast enough; supported by every project | slower than good internal SSD by a little; stick can be unplugged | ✅ **default** |
| Internal `/user/home/<name>.img` file (loop-mounted) | no USB needed; used by PS4 Multiboot [S17] | writes into the PS4 user partition; space accounting; installer complexity | ⚠️ optional profile |
| Internal dedicated partition/`mkfs` | full bus speed | **destroys Orbis and all saves**; PS4 then needs a recovery USB and full reinstall | ❌ forbidden by policy (D-01) |

The "run Linux from the internal HDD" community trick explicitly requires reinstalling Orbis on every
reboot [S27]. That is not a desktop product; it is an experiment.

## 7. Boot latency budget (targets to measure, EXP-002)

| Phase | Target | Notes |
|---|---|---|
| Jailbreak + GoldHEN ready | ≤ 60 s | user-driven, host-page dependent |
| Payload → kernel handoff | ≤ 5 s | plus 10–120 s black screen (normal) [S17] |
| Kernel → display manager | ≤ 25 s | USB 3.0, VRAM 1 GB |
| Login → usable Plasma | ≤ 20 s | needs tuning (blur off, fewer services) |
| **Cold start → usable desktop** | **≤ 2 min** | product target; measure honestly |
