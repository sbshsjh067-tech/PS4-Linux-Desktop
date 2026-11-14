# PS4-TEST-REPORT — Automated Verification Suite (`TEST A`..`TEST M`) & Strict Repair Records

**Execution Date:** 2026-11-14  
**Test Runners Executed:**
1. `PATH="$HOME/.local/bin:$PATH" pytest -v tests/` -> **`13 passed in 0.46s`**
2. `make test` (`build-initramfs-guard` + `verify-patches` + `lint` + `python3 -m unittest discover -s tests -v`) -> **`Ran 13 tests in 0.453s — OK`**

---

## 1. Automated Verification Matrix (`TEST A` through `TEST M`)

Every test in `tests/test_ps4_suite.py` executes deterministic assertions against the real C binary, Python modules, shell scripts, systemd presets, and synthetic PS4 hardware fixtures:

| Test ID | Mandatory Specification Scope | Verification Assertions Executed | Result |
|---|---|---|---|
| **TEST A** | Payload Loading (`bin/ps4-send-payload`, `binary_inspect.py`) | Generates minimal valid ELF64 `x86_64` payload, spins up local ephemeral TCP mock GoldHEN BinLoader listener, streams payload via `ps4-send-payload`, verifies byte-for-byte SHA-256 arrival; verifies corrupted non-ELF payload is rejected before network send | **PASS** |
| **TEST B** | Kernel Loading, Hardware Matrix & Config Repair (`boot_writer.py`, `build-kernel-safe.sh`) | Verifies `CUH-10xx/11xx` (`Aeolia`) & `CUH-12xx` (`Belize`) select `feeRnt/ps4-linux-12xx` `7.0-Clean` (`8ec5c28`) while `CUH-20xx` (`Baikal`) selects `5.4.247-baikal-dfaus`; enforces `D-08` refusal when `bzImage` exists in both USB & internal dirs; verifies `ps4-desktop-fat.config` sets `CONFIG_DRM_AMDGPU=y` and eliminates hardcoded `/home/rmux/...` path | **PASS** |
| **TEST C** | AMDGPU Initialization & Firmware CPIO Trap (`ps4-initramfs-tool`, `doctor.py`) | Packs two CPIO initramfs archives: (1) clean archive (`has_init=True`, `conflicting_gpu_firmware=[]`), and (2) poisoned archive containing `lib/firmware/amdgpu/liverpool_pfp.bin`; verifies `audit` and `ps4-doctor` flag the firmware-shadowing black-screen trap and detect `-2` microcode `dmesg` errors | **PASS** |
| **TEST D** | DRM Subsystem Initialization (`safe_boot.py`, `doctor.py`) | Verifies `BOOT STAGE 5` passes with valid `card0` + `card0-HDMI-A-1` sysfs hierarchy and fails deterministically when DRM nodes are absent | **PASS** |
| **TEST E** | HDMI Detection & Jaguar C Binary Guard (`ps4_hdmi_guard`, `hdmi_bridge.py`) | Executes compiled `initramfs/bin/ps4_hdmi_guard --self-test` against mock sysfs; runs `objdump -d initramfs/bin/ps4_hdmi_guard` across the entire static ELF binary and asserts **`0` AVX2 / FMA / BMI2 instructions** (`vpbroadcast`, `vperm2i128`, `vfmadd`, `mulx`, `pdep`, `pext`); tests `MockBridgeTransport` MN864729 mute detection & ICC `0x10` unmute (`0x1e00=0x01`, `0x1e02=0x70`, `0x705f=0x10`) | **PASS** |
| **TEST F** | EDID Parsing & Deep Color Hazard (`edid.py`) | Synthesizes valid 256-byte EDID 1.3 + CEA-861 extension (`1920x1080@60`, `1280x720@60`, HDMI VSDB 36-bit Deep Color), verifies PnP ID, checksum, VIC decoding, and `supports_deep_color` `BOOT-006` warning; verifies corrupt checksum rejection | **PASS** |
| **TEST G** | Safe Display Mode Selection & Anti-Out-of-Range (`display_protector.py`) | Proves 3 critical invariants: (1) `1920x1080@60` requested on a `1280x720@60`-only monitor is **REJECTED** and falls back to `1280x720@60`; (2) missing/corrupt EDID never forces `1080p60` and engages the `720p60 -> 1024x768 -> 800x600 -> 640x480` cascade; (3) `3840x2160@60` and `1920x1080@120` are blocked on PS4 Fat | **PASS** |
| **TEST H** | RootFS, `linux.img` Lifecycle & `D-01` Orbis Protection (`manage-linux-img.sh`, `make-ps4-usb-safe.sh`) | Creates real `64 MiB` ext4 `linux.img` via `manage-linux-img.sh create`, runs `manage-linux-img.sh verify` (`e2fsck`), tests `D-01` refusal when non-removable `/dev/sda` internal disk is passed to `make-ps4-usb-safe.sh` or mounted in `ps4-doctor` | **PASS** |
| **TEST I** | Desktop Startup, Patched Mesa Verification & X11 Safe Fallback (`ps4-mesa-select`, `ps4-rescue-desktop`, `build-ps4-mesa.sh`) | Verifies SHA-256 of `patches/mesa/0001..0003`; executes `ps4-mesa-select` without `/opt/ps4-mesa` (asserts `AccelMethod "none"` + `ShadowFB "true"` written) and with mock `/opt/ps4-mesa` + DRI node (asserts `glamor` + `DRI "3"` written); verifies `ps4-rescue-desktop --check-only` | **PASS** |
| **TEST J** | Input Readiness & Hardware Profile Collector (`ps4-profile-collector`, `safe_boot.py`) | Feeds simulated `/proc/bus/input/devices` (USB keyboard + USB mouse) and DMI/PCI sysfs into `ps4-profile-collector` and `BOOT STAGE 11`, asserting full keyboard/mouse detection | **PASS** |
| **TEST K** | Reboot Stability, Sleep Masking & Thermal Guard (`90-ps4-desktop.preset`, `ps4-thermal-guard`) | Verifies `sleep.target`, `suspend.target`, `hibernate.target`, and `hybrid-sleep.target` are masked (`SYS-001`); runs `scripts/ps4-thermal-guard --once` against simulated `ps4_fan` `hwmon` sysfs and verifies `temp1_crit` clamped safely to `72000` m°C (`72°C`) | **PASS** |
| **TEST L** | Repeated 11-Stage Safe Boot Cycles (`safe_boot.py`) | Executes 5 consecutive end-to-end `BOOT STAGE 1`..`BOOT STAGE 11` boot simulations across Fat `Aeolia` (`0x9920`) and Fat `Belize` (`0x9922`), asserting deterministic `PASS` and complete per-stage logs (`stage-01`..`stage-11`) on every run | **PASS** |
| **TEST M** | Display Recovery & Black-Screen Post-Mortem Pinpointer (`display_protector.py`, `doctor.py`) | Simulates muted `CUH-12xx` MN864729 (`0x1e00=0x00`, `0x705f=0x80`) -> runs `run_display_protection_pass(perform_recovery=True)` -> asserts bridge unmuted in a single atomic pass and `"Unmuted MN864729"` logged; simulates Stage 4 microcode failure -> asserts `pinpoint_black_screen_stage` reports `last_succeeded_stage=STAGE 3` and `first_failed_stage=STAGE 4` | **PASS** |

---

## 2. Strict 8-Item Engineering Repair Records (Part 5 Compliance)

Every bug uncovered during codebase audit, compilation, and testing was fixed one-by-one and verified immediately:

### Repair Record #1 — Upstream Kernel Hardcoded Developer Firmware Path & Modular KMS Hazard
1. **Problem:** Upstream `feeRnt/ps4-linux-12xx` `config` hardcodes a developer workstation path for `CONFIG_EXTRA_FIRMWARE_DIR`, breaking reproducible kernel builds or omitting built-in KMS firmware glue.
2. **Evidence:** Direct inspection of `feeRnt/ps4-linux-12xx@8ec5c28:config` revealed `CONFIG_EXTRA_FIRMWARE_DIR="/home/rmux/ps4_testing/ps4-linux-12xx/extra_firmware"`.
3. **Root Cause:** Unsanitized local path committed upstream.
4. **Responsible Files:** `configs/kernel/ps4-desktop-fat.config` and `scripts/build-kernel-safe.sh`.
5. **Change Applied:** Overrode `CONFIG_EXTRA_FIRMWARE_DIR=""` in `ps4-desktop-fat.config` (and dynamically bound `${EXTRA_FW_DIR}` in `build-kernel-safe.sh` when extra firmware is present), enforced `CONFIG_DRM_AMDGPU=y`, `CONFIG_DRM_AMDGPU_SI=y`, `CONFIG_DRM_AMDGPU_CIK=y`, and enforced `-march=btver2 -mtune=btver2`.
6. **Rollback Plan:** `git checkout -- configs/kernel/ps4-desktop-fat.config scripts/build-kernel-safe.sh`.
7. **Test Executed:** `TEST B` (`test_B_kernel_loading_matrix_and_config_repair`) + `./scripts/build-kernel-safe.sh --dry-run-audit`.
8. **Result:** **VERIFIED (`PASS`)** — zero hardcoded `/home/rmux` references; AMDGPU built-in flags enforced.

### Repair Record #2 — Missing Third PS4 Mesa ACO Patch (`0003-aco-ps4-no-flat-global.patch`)
1. **Problem:** Early research notes referenced Mesa patches `0001` (Liverpool/Gladius PCI IDs + `/dev/ps4-mesa-lock`) and `0002` (disable RADV HiZ), but `blue0x1/ps4-multiboot` ships a critical **third** patch required to prevent GPU `gfx` ring hangs on Vulkan `vkCmdFillBuffer`.
2. **Evidence:** Authenticated GitHub API inspection of `blue0x1/ps4-multiboot/patches/mesa` revealed `0003-aco-ps4-no-flat-global.patch` (`blob 8766cc72c9a00668e484787701241a70771a4d4e`).
3. **Root Cause:** Liverpool/Gladius (`gfx7`) hangs the `gfx` ring when executing ACO `FLAT` global store instructions (`flat_store_dwordx4`); global memory must use `MUBUF` `addr64` descriptors (`program->dev.no_flat_global = true`).
4. **Responsible Files:** `patches/mesa/0003-aco-ps4-no-flat-global.patch` and `scripts/build-ps4-mesa.sh`.
5. **Change Applied:** Mirrored verbatim `0001`, `0002`, and `0003` into `patches/mesa/` with SHA-256 lock verification in `scripts/build-ps4-mesa.sh --verify-patches`.
6. **Rollback Plan:** Remove `0003-aco-ps4-no-flat-global.patch` from patch array in `scripts/build-ps4-mesa.sh`.
7. **Test Executed:** `make verify-patches` and `TEST I` (`test_I_desktop_startup_and_mesa_select_guard`).
8. **Result:** **VERIFIED (`PASS`)** — all 3 patches match upstream blob/SHA-256 digests cleanly.

### Repair Record #3 — GNU `glibc` Static Linker Injecting AVX2 (`vpbroadcast`) Into Jaguar Initramfs Binary
1. **Problem:** Whole-binary disassembly (`objdump -d`) of `initramfs/bin/ps4_hdmi_guard` detected `vpbroadcast` AVX2 opcodes when linked with standard `-static`, failing `TEST E` and risking `SIGILL` audit false-positives or Jaguar crashes.
2. **Evidence:** `TEST E` failed on first test run (`found illegal opcodes in ps4_hdmi_guard`). Compiling `ps4_hdmi_guard.o` alone showed **`0` AVX2 instructions**, proving `vpbroadcast` came from GNU `glibc` `libc.a` (`__memset_avx2_unaligned_erms` IFUNC routines).
3. **Root Cause:** Debian's prebuilt `libc.a` embeds multi-ISA AVX2/AVX-512 string/memory routines regardless of `-march=btver2 -mno-avx2` compiler flags.
4. **Responsible Files:** `initramfs/src/ps4_hdmi_guard.c` and `Makefile`.
5. **Change Applied:** Rewrote `ps4_hdmi_guard.c` as a clean freestanding Linux `x86_64` syscall binary (`-static -nostdlib -fno-builtin -fno-stack-protector -march=btver2 -mno-avx2 -mno-fma -mno-bmi2`), eliminating `libc.a` completely and shrinking the binary from `671 KiB` to **`8.9 KiB`**.
6. **Rollback Plan:** `git diff initramfs/src/ps4_hdmi_guard.c Makefile` / restore libc headers if dynamic linking were ever desired.
7. **Test Executed:** `make build-initramfs-guard`, `./initramfs/bin/ps4_hdmi_guard --self-test`, `objdump -d` AVX2/FMA/BMI2 opcode count, and `TEST E`.
8. **Result:** **VERIFIED (`PASS`)** — **`0` AVX2/FMA/BMI2 instructions** in the entire `8.9 KiB` static ELF binary.

### Repair Record #4 — Double HDMI Bridge Unmute Suppressing Recovery Action Log (`TEST M`)
1. **Problem:** Calling `run_display_protection_pass(..., perform_recovery=True)` unmuted the MN864729 bridge, but `report.recovery_actions` reported `unmute_needed=False` instead of logging `"Unmuted MN864729"`.
2. **Evidence:** `TEST M` caught the missing `"Unmuted MN864729"` entry in `report.recovery_actions` on first pytest run.
3. **Root Cause:** `run_display_protection_pass()` called `check_and_heal_hdmi_bridge(..., auto_unmute=True)` **before** calling `recover_display()`, which called `check_and_heal_hdmi_bridge()` a second time after the registers had already been healed!
4. **Responsible File:** `src/ps4_linux/display_protector.py`.
5. **Change Applied:** Refactored `recover_display()` to perform the single atomic `check_and_heal_hdmi_bridge()` pass and return `(BridgeHealth, actions)` directly to `run_display_protection_pass()`.
6. **Rollback Plan:** `git checkout -- src/ps4_linux/display_protector.py`.
7. **Test Executed:** `TEST M` (`test_M_display_recovery_and_black_screen_postmortem`) + full `pytest -v tests/`.
8. **Result:** **VERIFIED (`PASS`)** — bridge unmutes once atomically and logs exact recovery action (`13/13` tests green).
