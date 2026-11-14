# PS4-NEXT-STEPS — Build Completion & Physical PS4 Fat Validation Runbook

**Safety Golden Rules (NEVER Violate):**
1. **NEVER update PS4 Orbis Firmware (`D-02`).** Leave the console at its current jailbreakable firmware (`<= 11.00` / `<= 13.52`).
2. **NEVER partition, mount RW, or install onto the internal PS4 HDD (`/dev/sda`) (`D-01`).** All Linux files live exclusively on an external USB 3.0 SSD/flash drive.
3. **Disable HDR & Deep Color in PS4 Orbis Settings** (`Settings -> Sound and Screen -> Video Output Settings -> HDR: Off, Deep Color Output: Off`) **before** launching GoldHEN and the Linux payload (`BOOT-006`).

---

## Step 1 — Install Missing Build Packages on Your Linux Workstation

Inside this cloud sandbox, `bc`, `flex`, `bison`, `libssl-dev`, `meson`, and `ninja` were absent (`PS4-TOOLCHAIN-REPORT.md`). On a standard Ubuntu 22.04/24.04 or Debian 12 x86_64 workstation, install them once:

```bash
sudo apt update
sudo apt install -y \
  bc flex bison libssl-dev libelf-dev dwarves kmod cpio zstd \
  meson ninja-build cmake pkg-config python3-mako python3-yaml python3-pytest \
  libdrm-dev libx11-dev libxext-dev libxfixes-dev libxcb-glx0-dev \
  libxcb-shm0-dev libx11-xcb-dev libxcb-dri2-0-dev libxcb-dri3-dev \
  libxcb-present-dev libxshmfence-dev libxxf86vm-dev libxrandr-dev \
  libwayland-dev wayland-protocols llvm-dev glslang-tools \
  parted dosfstools e2fsprogs edid-decode x11-xserver-utils
```

---

## Step 2 — Build `bzImage`, Patched `/opt/ps4-mesa`, and `initramfs.cpio.gz`

From the repository root:

```bash
# 1. Verify Jaguar HDMI guard + mirrored Mesa patches + full 13-test suite
make test

# 2. Pack the safe PS4 initramfs (includes Stage 5..8 /init + 8.9 KiB ps4_hdmi_guard; zero GPU firmware conflict)
make pack-initramfs
./bin/ps4-initramfs-tool audit artifacts/boot/initramfs.cpio.gz

# 3. Compile the pinned PS4 Fat Kernel (feeRnt/ps4-linux-12xx @ 7.0-Clean 8ec5c28)
./scripts/build-kernel-safe.sh --track fat_primary --output-dir artifacts/boot

# 4. Compile Patched PS4 Mesa 26.2.5 (patches 0001 + 0002 + 0003) into /opt/ps4-mesa tarball
./scripts/build-ps4-mesa.sh --output-dir artifacts/mesa
```

---

## Step 3 — Provision the External USB 3.0 Drive Safely (`D-01`)

Plug in a **dedicated external USB 3.0 SSD** (64 GB+ recommended; identify it carefully with `lsblk -o NAME,SIZE,RM,TRAN,MODEL`):

```bash
# 1. Partition USB into Partition 1: FAT32 (LABEL=PS4BOOT) + Partition 2: ext4 (LABEL=PS4LINUX)
#    (Refuses non-USB/internal drives automatically!)
sudo ./scripts/make-ps4-usb-safe.sh --device /dev/sdX --yes-format-usb

# 2. Or, if using a loop-mounted linux.img on exFAT/ext4 (LABEL=PS4KD):
./scripts/manage-linux-img.sh create --image /mnt/ps4kd/linux.img --size-gb 32

# 3. Write Southbridge-matched bzImage + initramfs.cpio.gz + safe bootargs.txt + vram.txt (1024 MB)
#    Replace CUH-1215A with your exact PS4 Fat model (CUH-10xxA, CUH-11xxA, or CUH-12xxA)
./bin/ps4-kernel-writer write \
  --cuh-model CUH-1215A \
  --layout usb_fat32 \
  --usb-boot-dir /mnt/ps4boot \
  --bzimage artifacts/boot/bzImage \
  --initramfs artifacts/boot/initramfs.cpio.gz \
  --vram-mb 1024
```

*(Notice `bootargs.txt` is written **without** blind `1920x1080@60`; `ps4_hdmi_guard` and `ps4-display-protector` negotiate the monitor's real EDID mode safely.)*

---

## Step 4 — Install RootFS Overlays Into USB `PS4LINUX` (or `linux.img`)

Copy the repository's protection services, Mesa bundle, and KDE/network/thermal configs into your target Debian/Arch x86_64 rootfs on `PS4LINUX`:

1. Extract `artifacts/mesa/ps4-mesa-26.2.5.tar.gz` to `/mnt/ps4linux/opt/ps4-mesa`.
2. Copy `src/ps4_linux/`, `bin/ps4-*`, and `scripts/*` to `/mnt/ps4linux/usr/local/`.
3. Copy `systemd/ps4-hdmi-protector.service` and `systemd/ps4-thermal-guard.service` to `/mnt/ps4linux/etc/systemd/system/`, and `systemd/90-ps4-desktop.preset` to `/mnt/ps4linux/etc/systemd/system-preset/`.
4. Copy `configs/desktop/kde/*` to `/etc/xdg/`, `configs/network/90-ps4-wifi-quirks.conf` to `/etc/NetworkManager/conf.d/`, `configs/system/90-ps4-zram-usb-tuning.conf` settings to `/etc/systemd/zram-generator.conf`, and `configs/freeze/*` to `/etc/apt/preferences.d/` (or `/etc/pacman.d/`).

---

## Step 5 — Safe First Boot & Hardware Verification (`EXP-001`..`EXP-015`)

1. Insert the USB drive into the **rear/right-most USB 3.0 port** on the PS4 Fat, plus a wired USB keyboard & mouse.
2. Boot PS4 into Orbis OS, verify **HDR = Off** and **Deep Color = Off**, activate **GoldHEN**, and enable **BinLoader Server (`:9090`)**.
3. Send the `1024 MB` firmware-agnostic payload from your PC:
   ```bash
   ./bin/ps4-send-payload --host <PS4_IP> --port 9090 --payload linux-1024mb.elf
   ```
4. **Wait 60–120 seconds (`BOOT-005`):**
   - If boot succeeds into KDE Plasma, open Konsole and run:
     ```bash
     ps4-profile-collector --output ~/profile.yaml
     ps4-doctor --output-md ~/doctor-first-boot.md
     ps4-display-protector --json
     ```
   - If a black screen occurs, power off cleanly, move the USB stick to your PC, inspect `/mnt/ps4boot/ps4-linux-fail-*.log`, and run:
     ```bash
     ./bin/ps4-doctor --boot-dir /mnt/ps4boot
     ```
     `ps4-doctor` will print the exact `last_succeeded_stage` and `first_failed_stage` (`BOOT STAGE 1`..`BOOT STAGE 11`).
   - To switch to the lightweight XFCE + `ShadowFB` recovery desktop at any time (`TTY2` `Ctrl+Alt+F2` or chroot):
     ```bash
     sudo /usr/local/scripts/ps4-rescue-desktop --mode xfce-safe
     ```
