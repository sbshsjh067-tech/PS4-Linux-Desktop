"""Automated Verification Suite for PS4 Linux Desktop (PART 5 §13: TEST A .. TEST M).

Important Technical Honesty Note (PART 6 §15):
  These automated tests execute deterministic host-level, binary-format, CPIO, ext4,
  EDID binary, mock-ICC register, and sysfs-simulation verification inside the x86_64
  build sandbox. Physical PlayStation 4 Fat kexec/GPU/HDMI hardware validation remains
  explicitly classified as `HARDWARE TEST REQUIRED` in PS4-TEST-REPORT.md.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from ps4_linux.binary_inspect import (  # noqa: E402
    CpioEntry,
    build_cpio_newc,
    inspect_bzimage,
    inspect_ext4_image,
    inspect_initramfs,
    inspect_payload,
    verify_usb_device_safety,
)
from ps4_linux.boot_writer import (  # noqa: E402
    check_dual_kernel_conflict,
    select_kernel_for_southbridge,
    stage_boot_files,
    validate_vram_mb,
)
from ps4_linux.display_protector import (  # noqa: E402
    run_display_protection_pass,
    select_safe_display_mode,
)
from ps4_linux.doctor import (  # noqa: E402
    analyze_black_screen_logs,
    collect_console_profile,
    run_doctor,
)
from ps4_linux.edid import DisplayMode, build_synthetic_edid, parse_edid  # noqa: E402
from ps4_linux.hdmi_bridge import (  # noqa: E402
    MemoryBridgeTransport,
    REG_HDMI_LANE_EN,
    REG_HDMI_OUT_EN,
    REG_VMUTECNT,
    check_and_heal_hdmi_bridge,
)
from ps4_linux.safe_boot import SafeBootContext, run_safe_boot_pipeline  # noqa: E402


def _make_synthetic_elf64(machine: int = 0x3E, phnum: int = 2) -> bytes:
    """Construct a minimal valid 64-bit little-endian ELF header + program header."""
    buf = bytearray(256)
    buf[0:4] = b"\x7fELF"
    buf[4] = 2  # ELFCLASS64
    buf[5] = 1  # ELFDATA2LSB
    buf[6] = 1  # EV_CURRENT
    struct.pack_into("<HH", buf, 16, 2, machine)  # ET_EXEC, e_machine
    struct.pack_into("<I", buf, 20, 1)
    struct.pack_into("<Q", buf, 24, 0x401000)     # e_entry
    struct.pack_into("<Q", buf, 32, 64)           # e_phoff
    struct.pack_into("<H", buf, 52, 64)           # e_ehsize
    struct.pack_into("<H", buf, 54, 56)           # e_phentsize
    struct.pack_into("<H", buf, 56, phnum)        # e_phnum
    return bytes(buf)


def _make_synthetic_bzimage(version_str: str = "7.0.0-Clean-belize (ps4@jaguar) #1 SMP") -> bytes:
    """Construct a minimal Linux x86 Boot Protocol 2.15 compliant bzImage header."""
    buf = bytearray(4096)
    buf[0x1F1] = 4  # setup_sects
    struct.pack_into("<H", buf, 0x1FE, 0xAA55)
    buf[0x202:0x206] = b"HdrS"
    struct.pack_into("<H", buf, 0x206, 0x020F)  # protocol 2.15
    ver_off = 0x400  # -> abs offset 0x600
    struct.pack_into("<H", buf, 0x20E, ver_off)
    buf[0x211] = 0x01  # LOADED_HIGH (bzImage)
    buf[0x234] = 0x01  # relocatable_kernel
    ver_bytes = version_str.encode("utf-8") + b"\x00"
    buf[0x600 : 0x600 + len(ver_bytes)] = ver_bytes
    return bytes(buf)


def _populate_mock_sysfs(
    root: Path,
    gpu_pci: str = "0x9923",
    conn_status: str = "connected",
    edid_bytes: bytes = b"",
    drm_modes: list[str] | None = None,
) -> None:
    pci_dir = root / "bus/pci/devices/0000:00:01.0"
    pci_dir.mkdir(parents=True, exist_ok=True)
    (pci_dir / "vendor").write_text("0x1002\n", encoding="utf-8")
    (pci_dir / "device").write_text(f"{gpu_pci}\n", encoding="utf-8")

    card_dev = root / "class/drm/card0/device"
    card_dev.mkdir(parents=True, exist_ok=True)
    (card_dev / "vendor").write_text("0x1002\n", encoding="utf-8")
    (card_dev / "device").write_text(f"{gpu_pci}\n", encoding="utf-8")
    drv_target = root / "bus/pci/drivers/amdgpu"
    drv_target.mkdir(parents=True, exist_ok=True)
    if not (card_dev / "driver").exists():
        os.symlink(drv_target, card_dev / "driver")

    hdmi_dir = root / "class/drm/card0-HDMI-A-1"
    hdmi_dir.mkdir(parents=True, exist_ok=True)
    (hdmi_dir / "status").write_text(f"{conn_status}\n", encoding="utf-8")
    (hdmi_dir / "enabled").write_text("enabled\n", encoding="utf-8")
    (hdmi_dir / "dpms").write_text("On\n", encoding="utf-8")
    modes_list = drm_modes if drm_modes is not None else ["1920x1080", "1280x720", "1024x768", "720x480", "640x480"]
    (hdmi_dir / "modes").write_text("\n".join(modes_list) + "\n", encoding="utf-8")
    (hdmi_dir / "edid").write_bytes(edid_bytes)


class TestPS4EngineeringSuite(unittest.TestCase):
    """Covers TEST A through TEST M from MASTER ENGINEERING PROMPT V3 PART 5 §13."""

    # ------------------------------------------------------------------
    # TEST A — Payload Loading & Verification
    # ------------------------------------------------------------------
    def test_A_payload_loading_and_tcp_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdir = Path(td)
            good_elf = tdir / "linux-1024mb.elf"
            good_elf.write_bytes(_make_synthetic_elf64(machine=0x3E, phnum=2))

            info = inspect_payload(good_elf)
            self.assertTrue(info.valid)
            self.assertEqual(info.kind, "elf64_x86_64")
            self.assertEqual(info.inferred_vram_mb, 1024)
            self.assertEqual(info.sha256, hashlib.sha256(good_elf.read_bytes()).hexdigest())

            # Reject ARM64 ELF disguised as PS4 payload
            bad_arm = tdir / "wrong-arch.elf"
            bad_arm.write_bytes(_make_synthetic_elf64(machine=0xB7, phnum=2))
            bad_info = inspect_payload(bad_arm)
            self.assertFalse(bad_info.valid)
            self.assertTrue(any("0x3e" in msg for msg in bad_info.issues))

            # Verify local loopback TCP delivery to mock GoldHEN BinLoader (:9020 equivalent)
            received: list[bytes] = []
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.bind(("127.0.0.1", 0))
            srv.listen(1)
            port = srv.getsockname()[1]

            def _accept() -> None:
                conn, _ = srv.accept()
                with conn:
                    chunks = []
                    while True:
                        data = conn.recv(4096)
                        if not data:
                            break
                        chunks.append(data)
                    received.append(b"".join(chunks))
                srv.close()

            th = threading.Thread(target=_accept, daemon=True)
            th.start()

            proc = subprocess.run(
                [sys.executable, str(REPO_ROOT / "bin/ps4-send-payload"), "--payload", str(good_elf), "--ps4-ip", "127.0.0.1", "--port", str(port)],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            th.join(timeout=5)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertEqual(received[0], good_elf.read_bytes())

    # ------------------------------------------------------------------
    # TEST B — Kernel Loading, Matrix, Dual-Location Guard & Config Repair
    # ------------------------------------------------------------------
    def test_B_kernel_loading_matrix_and_config_repair(self) -> None:
        cand_fat = select_kernel_for_southbridge("belize")
        self.assertEqual(cand_fat.commit, "8ec5c282abda91f6c2e4014de206105aa7912516")
        self.assertEqual(cand_fat.version, "7.0.0")
        cand_baikal = select_kernel_for_southbridge("baikal")
        self.assertEqual(cand_baikal.commit, "1fdfbd9a4c5690602893f6d5f65e154c6d9ba711")

        # Validate VRAM MB policy (catches BOOT-004 legacy '1' GB footgun)
        ok_gb, _, msg_gb = validate_vram_mb("1")
        self.assertFalse(ok_gb)
        self.assertIn("BOOT-004", msg_gb)
        ok_mb, val_mb, _ = validate_vram_mb("1024")
        self.assertTrue(ok_mb)
        self.assertEqual(val_mb, 1024)

        with tempfile.TemporaryDirectory() as td:
            tdir = Path(td)
            bz = tdir / "bzImage"
            bz.write_bytes(_make_synthetic_bzimage("7.0.0-Clean-belize"))
            k_info = inspect_bzimage(bz)
            self.assertTrue(k_info.valid)
            self.assertEqual(k_info.boot_protocol, "2.15")
            self.assertIn("7.0.0-Clean-belize", k_info.version_string)

            # Build valid initramfs
            ir = tdir / "initramfs.cpio.gz"
            ir.write_bytes(
                build_cpio_newc(
                    [
                        CpioEntry("init", 0o100755, 12, b"#!/bin/sh\n"),
                        CpioEntry("bin/ps4_hdmi_guard", 0o100755, 4, b"\x7fELF"),
                    ]
                )
            )

            usb_boot = tdir / "usb_ps4boot"
            int_boot = tdir / "internal_boot"
            manifest = stage_boot_files(
                layout="usb_fat32",
                southbridge="belize",
                bzimage_src=bz,
                initramfs_src=ir,
                dest_dir=usb_boot,
                other_layout_dir=int_boot,
                vram_mb=1024,
            )
            self.assertEqual(manifest["vram_mb"], 1024)
            self.assertNotIn("1920x1080@60D", str(manifest["bootargs"]))

            # Create dual-kernel conflict (BOOT-003) and assert blocker triggers
            int_boot.mkdir(parents=True)
            (int_boot / "bzImage").write_bytes(bz.read_bytes())
            conflict = check_dual_kernel_conflict("usb_fat32", usb_boot, int_boot)
            self.assertFalse(conflict.valid)
            self.assertTrue(any("BOOT-003" in x for x in conflict.issues))

            # Verify upstream kernel config repair fixes hardcoded /home/rmux/... path
            broken_cfg = tdir / "config"
            broken_cfg.write_text(
                'CONFIG_EXTRA_FIRMWARE_DIR="/home/rmux/ps4_testing/ps4-linux-12xx/extra_firmware"\n'
                "# CONFIG_DRM_AMDGPU is not set\n"
                "# CONFIG_OVERLAY_FS is not set\n",
                encoding="utf-8",
            )
            rep_proc = subprocess.run(
                ["bash", str(REPO_ROOT / "scripts/build-kernel-safe.sh"), "--repair-config", str(broken_cfg)],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(rep_proc.returncode, 0, msg=rep_proc.stderr)
            repaired_txt = broken_cfg.read_text(encoding="utf-8")
            self.assertNotIn("/home/rmux/", repaired_txt)
            self.assertIn("CONFIG_DRM_AMDGPU=y", repaired_txt)
            self.assertIn("CONFIG_OVERLAY_FS=y", repaired_txt)

    # ------------------------------------------------------------------
    # TEST C — AMDGPU Initialization & Initramfs Firmware Overwrite Trap
    # ------------------------------------------------------------------
    def test_C_amdgpu_init_and_firmware_trap_detection(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdir = Path(td)
            # Trap: initramfs containing liverpool_mec2.bin overwrites loader-extracted Orbis ucode!
            bad_ir = tdir / "bad_initramfs.cpio.gz"
            bad_ir.write_bytes(
                build_cpio_newc(
                    [
                        CpioEntry("init", 0o100755, 10, b"#!/bin/sh\n"),
                        CpioEntry("lib/firmware/amdgpu/liverpool_mec2.bin", 0o100644, 16, b"\x00" * 16),
                    ]
                )
            )
            ir_audit = inspect_initramfs(bad_ir)
            self.assertFalse(ir_audit.valid)
            self.assertIn("lib/firmware/amdgpu/liverpool_mec2.bin", ir_audit.conflicting_gpu_firmware)

            # Verify real repo initramfs packs cleanly with ZERO firmware conflicts
            good_ir = tdir / "good_initramfs.cpio.gz"
            pack_proc = subprocess.run(
                [sys.executable, str(REPO_ROOT / "bin/ps4-initramfs-tool"), "pack", str(REPO_ROOT / "initramfs"), str(good_ir)],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            self.assertEqual(pack_proc.returncode, 0, msg=pack_proc.stderr)
            good_audit = inspect_initramfs(good_ir)
            self.assertTrue(good_audit.valid)
            self.assertTrue(good_audit.has_init)
            self.assertTrue(good_audit.has_hdmi_guard)
            self.assertEqual(good_audit.conflicting_gpu_firmware, [])

    # ------------------------------------------------------------------
    # TEST D — DRM Initialization & Doctor Blocker Checks
    # ------------------------------------------------------------------
    def test_D_drm_initialization_and_doctor_checks(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            sysfs = Path(td) / "sys"
            edid_1080 = build_synthetic_edid(preferred_mode=(1920, 1080, 60))
            _populate_mock_sysfs(sysfs, gpu_pci="0x9923", conn_status="connected", edid_bytes=edid_1080)

            # Case 1: Simulated llvmpipe software rendering -> Doctor MUST fail with GFX-001 and exit 1
            rep_fail = run_doctor(
                sysfs_root=sysfs,
                glxinfo_override="OpenGL renderer string: llvmpipe (LLVM 19.1.0, 128 bits)",
                vulkaninfo_override="apiVersion = 1.3.289\ndeviceName = AMD Liverpool",
                root_tran_override="usb",
            )
            self.assertEqual(rep_fail.exit_code, 1)
            self.assertTrue(any(c.registry_id == "GFX-001" and c.status == "FAIL" for c in rep_fail.checks))

            # Case 2: Hardware Liverpool RadeonSI + Vulkan 1.3 + DXVK 2.7.1 -> Doctor exits 0
            mesa_dir = Path(td) / "opt/ps4-mesa"
            (mesa_dir / "lib").mkdir(parents=True)
            (mesa_dir / "lib/libgallium-26.2.5.so").write_bytes(b"ELF...AMD LIVERPOOL 0x9923...")
            rep_ok = run_doctor(
                sysfs_root=sysfs,
                glxinfo_override="OpenGL renderer string: AMD Liverpool (PlayStation 4) (radeonsi, LLVM 19)",
                vulkaninfo_override="apiVersion = 1.3.289\ndeviceName = AMD Liverpool (PlayStation 4)",
                dmesg_override="[    2.100] [drm] Initialized amdgpu 3.61.0 for 0000:00:01.0 on minor 0",
                root_tran_override="usb",
                mesa_prefix=mesa_dir,
                dxvk_version="2.7.1",
                proton_version="11.0",
            )
            self.assertEqual(rep_ok.exit_code, 0)

    # ------------------------------------------------------------------
    # TEST E — HDMI Connector & MN864729 vs MN86471A Bridge Detection
    # ------------------------------------------------------------------
    def test_E_hdmi_detection_and_jaguar_c_guard(self) -> None:
        # Verify compiled C initramfs guard has ZERO AVX2/FMA/BMI2 instructions
        guard_bin = REPO_ROOT / "initramfs/bin/ps4_hdmi_guard"
        self.assertTrue(guard_bin.is_file(), "initramfs/bin/ps4_hdmi_guard must be compiled")
        disasm = subprocess.run(
            ["objdump", "-d", str(guard_bin)],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        ).stdout
        for bad_op in ("vpbroadcast", "vperm2i128", "vfmadd", "pdep", "pext"):
            self.assertNotIn(bad_op, disasm)

        with tempfile.TemporaryDirectory() as td:
            sysfs = Path(td) / "sys"
            edid_1080 = build_synthetic_edid(preferred_mode=(1920, 1080, 60))
            _populate_mock_sysfs(sysfs, gpu_pci="0x9920", conn_status="connected", edid_bytes=edid_1080)

            # Run C binary self-test against synthetic sysfs
            c_res = subprocess.run(
                [str(guard_bin), "--self-test", "--sysfs-root", str(sysfs)],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            self.assertIn("pci_id=0x9920", c_res.stdout)
            self.assertIn("edid_valid=1", c_res.stdout)

            # Aeolia 0x9920 uses MN86471A -> not affected by MN864729 mute quirk
            bh_aeolia = check_and_heal_hdmi_bridge(sysfs_root=sysfs)
            self.assertEqual(bh_aeolia.bridge_chip, "MN86471A")
            self.assertFalse(bh_aeolia.affected_by_mute_quirk)

    # ------------------------------------------------------------------
    # TEST F — Binary EDID 1.3/1.4 + CEA-861 Parsing & Checksum Validation
    # ------------------------------------------------------------------
    def test_F_edid_parsing_and_deep_color_warning(self) -> None:
        raw_edid = build_synthetic_edid(
            monitor_name="SONY-BRAVIA",
            manufacturer="SNY",
            preferred_mode=(1920, 1080, 60),
            cea_vics=(16, 4, 31, 19, 2),
            include_cea=True,
            deep_color=True,
        )
        self.assertEqual(len(raw_edid), 256)
        parsed = parse_edid(raw_edid)
        self.assertTrue(parsed.valid)
        self.assertTrue(parsed.checksum_ok)
        self.assertEqual(parsed.manufacturer, "SNY")
        self.assertEqual(parsed.monitor_name, "SONY-BRAVIA")
        self.assertTrue(parsed.has_cea_extension)
        self.assertTrue(parsed.has_hdmi_vsdb)
        self.assertTrue(parsed.supports_basic_audio)
        self.assertTrue(parsed.deep_color_30bit)
        self.assertIn("1920x1080", parsed.unique_resolutions())
        self.assertIn(60, parsed.supported_refresh_rates(1920, 1080))
        self.assertIn(50, parsed.supported_refresh_rates(1920, 1080))

        # Corrupt checksum must be flagged invalid
        corrupt = build_synthetic_edid(corrupt_checksum=True)
        bad_parsed = parse_edid(corrupt)
        self.assertFalse(bad_parsed.valid)
        self.assertFalse(bad_parsed.checksum_ok)

    # ------------------------------------------------------------------
    # TEST G — Safe Display Mode Selection (NEVER Blindly Force 1080p@60Hz!)
    # ------------------------------------------------------------------
    def test_G_display_mode_selection_and_anti_out_of_range(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            # 1. HD-Ready 1366x768@60 TV -> MUST reject requested 1920x1080@60 and pick 1366x768@60!
            sys_768 = Path(td) / "sys_768"
            edid_768 = build_synthetic_edid(
                monitor_name="HDREADY-TV",
                preferred_mode=(1366, 768, 60),
                cea_vics=(4, 2, 1),
                max_pclk_mhz=90,
            )
            _populate_mock_sysfs(
                sys_768,
                edid_bytes=edid_768,
                drm_modes=["1366x768", "1280x720", "1024x768", "640x480"],
            )
            rep_768 = run_display_protection_pass(
                sysfs_root=sys_768,
                requested_mode=DisplayMode(1920, 1080, 60),
                dry_run=True,
            )
            self.assertEqual(rep_768.decision.selected_mode.kms_mode_str, "1366x768@60")
            self.assertTrue(any("1920x1080@60" in r["mode"] for r in rep_768.decision.rejected_modes))

            # 2. PAL 50Hz-only display (max_vrate_hz=50) -> MUST reject 60Hz and pick 1920x1080@50!
            sys_50 = Path(td) / "sys_50"
            edid_50 = build_synthetic_edid(
                monitor_name="PAL-50HZ",
                preferred_mode=(1920, 1080, 50),
                cea_vics=(31, 19, 17),
                max_vrate_hz=50,
            )
            _populate_mock_sysfs(sys_50, edid_bytes=edid_50, drm_modes=["1920x1080", "1280x720"])
            rep_50 = run_display_protection_pass(
                sysfs_root=sys_50,
                requested_mode=DisplayMode(1920, 1080, 60),
                dry_run=True,
            )
            self.assertEqual(rep_50.decision.selected_mode.kms_mode_str, "1920x1080@50")

            # 3. 4K TV advertising 3840x2160@60 -> MUST block 4K on PS4 Fat and pick 1920x1080@60!
            sys_4k = Path(td) / "sys_4k"
            edid_4k = build_synthetic_edid(
                monitor_name="UHD-4K-TV",
                preferred_mode=(3840, 2160, 60),
                cea_vics=(97, 16, 4),
                max_pclk_mhz=600,
            )
            _populate_mock_sysfs(sys_4k, edid_bytes=edid_4k, drm_modes=["3840x2160", "1920x1080", "1280x720"])
            rep_4k = run_display_protection_pass(sysfs_root=sys_4k, dry_run=True)
            self.assertEqual(rep_4k.decision.selected_mode.kms_mode_str, "1920x1080@60")
            self.assertTrue(any("3840x2160" in r["mode"] for r in rep_4k.decision.rejected_modes))

            # 4. Broken DDC / 0-byte EDID -> MUST NOT force 1080p60; MUST select 1280x720@60 fallback!
            sys_noedid = Path(td) / "sys_noedid"
            _populate_mock_sysfs(sys_noedid, edid_bytes=b"", drm_modes=[])
            rep_fb = run_display_protection_pass(
                sysfs_root=sys_noedid,
                requested_mode=DisplayMode(1920, 1080, 60),
                dry_run=True,
            )
            self.assertTrue(rep_fb.decision.used_fallback)
            self.assertEqual(rep_fb.decision.selected_mode.kms_mode_str, "1280x720@60")
            self.assertEqual(rep_fb.decision.fallback_mode.kms_mode_str, "1024x768@60")

            # Also verify select_safe_display_mode tier step-down
            dec_tier2 = select_safe_display_mode(None, fallback_tier=2)
            self.assertEqual(dec_tier2.selected_mode.kms_mode_str, "720x480@60")

    # ------------------------------------------------------------------
    # TEST H — RootFS Mounting, `linux.img` Creation & D-01 Internal-Disk Guard
    # ------------------------------------------------------------------
    def test_H_rootfs_linux_img_and_d01_usb_guard(self) -> None:
        # D-01 guard MUST block SATA (PS4 internal HDD), NVMe, and virtio internal disks
        ok_sata, msg_sata = verify_usb_device_safety("/dev/sda", lsblk_override="sata")
        self.assertFalse(ok_sata)
        self.assertIn("D-01", msg_sata)

        ok_nvme, _ = verify_usb_device_safety("/dev/nvme0n1", lsblk_override="usb")
        self.assertFalse(ok_nvme)

        ok_usb, _ = verify_usb_device_safety("/dev/sdb", lsblk_override="usb")
        self.assertTrue(ok_usb)

        # Create real ext4 `linux.img` using manage-linux-img.sh and verify with e2fsck & superblock parser
        with tempfile.TemporaryDirectory() as td:
            img = Path(td) / "linux.img"
            c_proc = subprocess.run(
                ["bash", str(REPO_ROOT / "scripts/manage-linux-img.sh"), "create", str(img), "16"],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            self.assertEqual(c_proc.returncode, 0, msg=c_proc.stderr)
            ext_info = inspect_ext4_image(img)
            self.assertTrue(ext_info.valid_ext4)
            self.assertEqual(ext_info.volume_label, "PS4KD")
            self.assertTrue(ext_info.clean_state)

    # ------------------------------------------------------------------
    # TEST I — Desktop Startup & X11 `glamor` vs `ShadowFB` Anti-Black-Screen Guard
    # ------------------------------------------------------------------
    def test_I_desktop_startup_and_mesa_select_guard(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            etc_dir = Path(td) / "etc"
            mesa_dir = Path(td) / "opt/ps4-mesa"
            env = dict(os.environ, PS4_ETC_ROOT=str(etc_dir), PS4_MESA_PREFIX=str(mesa_dir))

            # 1. Without /opt/ps4-mesa, --auto-safe MUST configure ShadowFB so X11 doesn't black-screen!
            p1 = subprocess.run(
                ["bash", str(REPO_ROOT / "scripts/ps4-mesa-select"), "--auto-safe"],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            self.assertIn("ShadowFB", p1.stdout)
            xorg_cfg = (etc_dir / "X11/xorg.conf.d/20-ps4-gpu.conf").read_text(encoding="utf-8")
            self.assertIn('Option     "AccelMethod" "none"', xorg_cfg)
            self.assertIn('Option     "ShadowFB"    "true"', xorg_cfg)

            # 2. With verified Liverpool /opt/ps4-mesa, --auto-safe MUST enable glamor + DRI3 + RADV ICD!
            (mesa_dir / "lib").mkdir(parents=True)
            (mesa_dir / "lib/libgallium-26.2.5.so").write_bytes(b"\x7fELF...CHIP_LIVERPOOL...0x9923...")
            p2 = subprocess.run(
                ["bash", str(REPO_ROOT / "scripts/ps4-mesa-select"), "--auto-safe"],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            self.assertIn("glamor", p2.stdout)
            xorg_cfg_hw = (etc_dir / "X11/xorg.conf.d/20-ps4-gpu.conf").read_text(encoding="utf-8")
            self.assertIn('Option     "AccelMethod" "glamor"', xorg_cfg_hw)
            self.assertIn('Option     "DRI"         "3"', xorg_cfg_hw)
            self.assertTrue((etc_dir / "ld.so.conf.d/00-ps4-mesa.conf").is_file())

    # ------------------------------------------------------------------
    # TEST J — Keyboard, Mouse & DualShock 4 Input Readiness + T-001 Profile Collector
    # ------------------------------------------------------------------
    def test_J_input_readiness_and_profile_collector(self) -> None:
        kcfg = (REPO_ROOT / "configs/kernel/ps4-desktop-fat.config").read_text(encoding="utf-8")
        for sym in ("CONFIG_USB_HID=y", "CONFIG_HID_GENERIC=y", "CONFIG_HID_PLAYSTATION=y", "CONFIG_USB_XHCI_AEOLIA=y"):
            self.assertIn(sym, kcfg)

        with tempfile.TemporaryDirectory() as td:
            tdir = Path(td)
            out_yaml = tdir / "profile.yaml"
            out_txt = tdir / "ps4-report.txt"
            prof = collect_console_profile(
                output_yaml=out_yaml,
                output_report_txt=out_txt,
                layout="usb_fat32",
                root_tran_override="usb",
            )
            self.assertTrue(out_yaml.is_file())
            self.assertTrue(out_txt.is_file())
            hw = prof["hardware_checks"]  # type: ignore[index]
            self.assertIn("idle_ram_mib", hw)
            self.assertIn("image_size_mib", hw)
            self.assertTrue(hw["root_usb_verified"])

    # ------------------------------------------------------------------
    # TEST K — Reboot Stability, Sleep Masking & Thermal Safety Clamping
    # ------------------------------------------------------------------
    def test_K_reboot_stability_sleep_mask_and_thermal_guard(self) -> None:
        preset = (REPO_ROOT / "systemd/90-ps4-desktop.preset").read_text(encoding="utf-8")
        for unit in ("sleep.target", "suspend.target", "hibernate.target", "hybrid-sleep.target"):
            self.assertIn(f"disable {unit}", preset)

        with tempfile.TemporaryDirectory() as td:
            sysfs = Path(td) / "sys"
            hw0 = sysfs / "class/hwmon/hwmon0"
            hw0.mkdir(parents=True)
            (hw0 / "name").write_text("ps4_fan\n", encoding="utf-8")
            (hw0 / "temp1_input").write_text("58000\n", encoding="utf-8")
            (hw0 / "fan1_input").write_text("2100\n", encoding="utf-8")
            (hw0 / "temp1_crit").write_text("78000\n", encoding="utf-8")

            # Dangerous <65C target MUST be rejected (prevents jet-engine EMC lockup, S23)
            bad_th = subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts/ps4-thermal-guard"), "--sysfs-root", str(sysfs), "--target-c", "50", "--apply"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            self.assertNotEqual(bad_th.returncode, 0)

            # Safe 72C target MUST write 72000 mC to temp1_crit
            good_th = subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts/ps4-thermal-guard"), "--sysfs-root", str(sysfs), "--target-c", "72", "--apply", "--json"],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            data = json.loads(good_th.stdout)
            self.assertEqual(data["threshold_c"], 72.0)
            self.assertEqual((hw0 / "temp1_crit").read_text(encoding="utf-8").strip(), "72000")

    # ------------------------------------------------------------------
    # TEST L — Repeated Boot Testing (15 Simulated 11-Stage Safe Boot Cycles)
    # ------------------------------------------------------------------
    def test_L_repeated_11_stage_safe_boot_cycles(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdir = Path(td)
            sysfs = tdir / "sys"
            edid_1080 = build_synthetic_edid(preferred_mode=(1920, 1080, 60))
            _populate_mock_sysfs(sysfs, gpu_pci="0x9923", conn_status="connected", edid_bytes=edid_1080)

            boot_dir = tdir / "ps4boot"
            boot_dir.mkdir()
            payload = tdir / "linux-1024mb.elf"
            payload.write_bytes(_make_synthetic_elf64())
            bz = boot_dir / "bzImage"
            bz.write_bytes(_make_synthetic_bzimage("7.0.0-Clean-belize"))
            ir = boot_dir / "initramfs.cpio.gz"
            ir.write_bytes(
                build_cpio_newc(
                    [
                        CpioEntry("init", 0o100755, 10, b"#!/bin/sh\n"),
                        CpioEntry("bin/ps4_hdmi_guard", 0o100755, 4, b"\x7fELF"),
                    ]
                )
            )
            (boot_dir / "vram.txt").write_text("1024\n", encoding="utf-8")

            mesa_dir = tdir / "opt/ps4-mesa"
            (mesa_dir / "lib").mkdir(parents=True)
            (mesa_dir / "lib/libgallium-26.2.5.so").write_bytes(b"\x7fELF...LIVERPOOL...")
            xorg_conf = tdir / "20-ps4-gpu.conf"
            xorg_conf.write_text('Option "AccelMethod" "glamor"\n', encoding="utf-8")

            for run_i in range(15):
                bridge = MemoryBridgeTransport()
                ctx = SafeBootContext(
                    layout="usb_fat32",
                    southbridge="belize",
                    firmware_version="13.52",
                    usb_boot_dir=boot_dir,
                    payload_path=payload,
                    root_device="/dev/sdb2",
                    root_tran_override="usb",
                    sysfs_root=sysfs,
                    cpu_flags=["fpu", "sse4_2", "avx", "aes"],
                    memtotal_kib=6_800_000,
                    dmesg_text="[1.0] amdgpu: 1024M of VRAM memory ready\n[2.0] Initialized amdgpu",
                    dri_nodes=["card0", "renderD128"],
                    mesa_prefix=mesa_dir,
                    xorg_gpu_conf=xorg_conf,
                    masked_units=["sleep.target", "suspend.target", "hibernate.target", "hybrid-sleep.target"],
                    enabled_services=["systemd-timesyncd.service"],
                    desktop_sessions=["plasma.desktop", "xfce.desktop"],
                    input_devices=["USB HID Keyboard", "USB Optical Mouse"],
                    temp_celsius=56.0,
                    fan_threshold_celsius=72.0,
                    bridge_transport=bridge,
                    is_live_ps4=True,
                )
                log_dir = tdir / f"logs_run_{run_i}"
                rep = run_safe_boot_pipeline(ctx, log_dir=log_dir)
                self.assertEqual(rep.overall_status, "PASS", msg=f"Run {run_i} failed: {rep.to_dict()}")
                self.assertIsNone(rep.first_failed_stage)
                self.assertEqual(rep.last_successful_stage, "BOOT STAGE 11 — Display Stability Verification")
                self.assertTrue((log_dir / "safe-boot.log").is_file())

    # ------------------------------------------------------------------
    # TEST M — Display Recovery (MN864729 Unmute + Black-Screen Stage Isolation)
    # ------------------------------------------------------------------
    def test_M_display_recovery_and_black_screen_postmortem(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            sysfs = Path(td) / "sys"
            edid_1080 = build_synthetic_edid(preferred_mode=(1920, 1080, 60))
            _populate_mock_sysfs(sysfs, gpu_pci="0x9923", conn_status="connected", edid_bytes=edid_1080)

            # Simulate TV HDMI handshake muting PS4 Fat Belize MN864729 bridge:
            # 0x1e00 = 0x00 (output disabled), 0x1e02 = 0x00, 0x705f = 0x90 (bit 7 CCVMUTE=1)
            muted_bridge = MemoryBridgeTransport(
                initial={REG_HDMI_OUT_EN: 0x00, REG_HDMI_LANE_EN: 0x00, REG_VMUTECNT: 0x90}
            )
            rep = run_display_protection_pass(
                sysfs_root=sysfs,
                bridge_transport=muted_bridge,
                perform_recovery=True,
                dry_run=False,
            )
            self.assertEqual(muted_bridge.read_reg(REG_HDMI_LANE_EN) & 0x70, 0x70)
            self.assertEqual(muted_bridge.read_reg(REG_HDMI_OUT_EN) & 0x01, 0x01)
            self.assertEqual(muted_bridge.read_reg(REG_VMUTECNT), 0x10)
            self.assertTrue(any("Unmuted MN864729" in act for act in rep.recovery_actions))

            # Verify Black-Screen Post-Mortem Analyzer accurately pinpoints Last OK & First Failed stage:
            # Scenario 1: GPU Firmware Failure at Stage 6
            bs_fw = analyze_black_screen_logs(
                "Linux version 7.0.0-Clean\nUnpacking initramfs...\ngfx7: Failed to load firmware liverpool gfx firmware\n"
            )
            self.assertTrue(bs_fw.black_screen_detected)
            self.assertIn("BOOT STAGE 5", bs_fw.last_successful_stage)
            self.assertIn("BOOT STAGE 6", bs_fw.first_failed_stage)
            self.assertIn("BOOT-001", bs_fw.registry_ids)

            # Scenario 2: Display Manager glamor crash at Stage 10
            bs_dm = analyze_black_screen_logs(
                "Linux version 7.0.0-Clean\nUnpacking initramfs...\n[drm] Initialized amdgpu\n"
                "fb0: amdgpudrmfb frame buffer device\nEXT4-fs (sdb2): mounted filesystem\n"
                "Reached target Multi-User System\nsddm: glamor initialization failed\n"
            )
            self.assertTrue(bs_dm.black_screen_detected)
            self.assertIn("BOOT STAGE 9", bs_dm.last_successful_stage)
            self.assertIn("BOOT STAGE 10", bs_dm.first_failed_stage)
            self.assertIn("GFX-001", bs_dm.registry_ids)

    # ------------------------------------------------------------------
    # TEST N — PS4 PKG (param.sfo, icon0.png, CNT Verifier & Anti-Fake Gate)
    # ------------------------------------------------------------------
    def test_N_ps4_pkg_sfo_icon_cnt_verifier_and_honesty_gate(self) -> None:
        from ps4_linux.pkg_builder import (
            build_icon0_png,
            build_param_sfo,
            inspect_ps4_pkg,
            normalize_ps4_content_id,
            parse_param_sfo,
            stage_and_optionally_build_pkg,
        )

        # 1. Verify 35-char -> 36-char Sony Content ID normalization
        cid = normalize_ps4_content_id("IV0000-BREW00001_00-PS4LDESKTOP0000.pkg")
        self.assertTrue(cid.was_padded)
        self.assertEqual(cid.title_id, "BREW00001")
        self.assertEqual(cid.normalized_content_id, "IV0000-BREW00001_00-PS4LDESKTOP00000")
        self.assertEqual(len(cid.normalized_content_id), 36)

        # 2. Verify binary sce_sys/param.sfo generation & round-trip parsing
        sfo_bytes = build_param_sfo(content_id=cid.normalized_content_id, title_id="BREW00001")
        parsed_sfo = parse_param_sfo(sfo_bytes)
        self.assertEqual(parsed_sfo["TITLE_ID"], "BREW00001")
        self.assertEqual(parsed_sfo["CATEGORY"], "gd")
        self.assertEqual(parsed_sfo["CONTENT_ID"], "IV0000-BREW00001_00-PS4LDESKTOP00000")
        self.assertEqual(parsed_sfo["APP_TYPE"], 1)

        # 3. Verify Orbis 512x512 24-bit non-interlaced PNG icon0.png
        png_bytes = build_icon0_png(512, 512)
        self.assertEqual(png_bytes[:8], b"\x89PNG\r\n\x1a\n")
        w, h, bit_depth, color_type, comp, filt, interlace = struct.unpack(">IIBBBBB", png_bytes[16:29])
        self.assertEqual((w, h, bit_depth, color_type, interlace), (512, 512, 8, 2, 0))

        with tempfile.TemporaryDirectory() as td:
            tpath = Path(td)

            # 4. Reject a ZIP file disguised as .pkg
            fake_zip_pkg = tpath / "IV0000-BREW00001_00-PS4LDESKTOP0000.pkg"
            fake_zip_pkg.write_bytes(b"PK\x03\x04" + b"\x00" * 0x500)
            bad_insp = inspect_ps4_pkg(fake_zip_pkg)
            self.assertFalse(bad_insp.valid_ps4_pkg)
            self.assertTrue(any("ZIP archive" in e for e in bad_insp.errors))

            # 5. Accept a structurally valid \x7fCNT header layout
            cnt_buf = bytearray(0x800)
            cnt_buf[0x00:0x04] = b"\x7fCNT"
            cnt_buf[0x04:0x08] = struct.pack(">I", 0x00000001)
            cnt_buf[0x10:0x14] = struct.pack(">I", 8)
            cnt_buf[0x40:0x64] = b"IV0000-BREW00001_00-PS4LDESKTOP00000"
            # Orbis CNT header offsets (LibOrbisPkg PkgWriter): 0x410 pfs_image_offset,
            # 0x418 pfs_image_size, 0x430 package_size.
            cnt_buf[0x410:0x418] = struct.pack(">Q", 0x400)
            cnt_buf[0x418:0x420] = struct.pack(">Q", len(cnt_buf) - 0x400)
            cnt_buf[0x430:0x438] = struct.pack(">Q", len(cnt_buf))
            valid_cnt = tpath / "valid_header.pkg"
            valid_cnt.write_bytes(bytes(cnt_buf))
            ok_insp = inspect_ps4_pkg(valid_cnt)
            self.assertTrue(ok_insp.valid_ps4_pkg)
            self.assertEqual(ok_insp.content_id, "IV0000-BREW00001_00-PS4LDESKTOP00000")
            self.assertEqual(ok_insp.header_pkg_size, len(cnt_buf))
            self.assertEqual(ok_insp.pfs_image_size, len(cnt_buf) - 0x400)

            # 5b. Reject a CNT header whose package_size does not cover the file (truncation)
            truncated = bytearray(cnt_buf)
            truncated[0x430:0x438] = struct.pack(">Q", len(cnt_buf) - 1)
            trunc_pkg = tpath / "truncated.pkg"
            trunc_pkg.write_bytes(bytes(truncated))
            self.assertFalse(inspect_ps4_pkg(trunc_pkg).valid_ps4_pkg)

            # 5c. Reject a CNT header whose outer PFS image runs past EOF
            overrun = bytearray(cnt_buf)
            overrun[0x418:0x420] = struct.pack(">Q", len(cnt_buf) + 0x10000)
            overrun_pkg = tpath / "overrun.pkg"
            overrun_pkg.write_bytes(bytes(overrun))
            self.assertFalse(inspect_ps4_pkg(overrun_pkg).valid_ps4_pkg)

            # 6. Verify staging builds real repo assets & blocks fake PKG when Orbis/kernel binaries missing
            staging = tpath / "staging"
            out_pkg = tpath / "out" / "IV0000-BREW00001_00-PS4LDESKTOP0000.pkg"
            rep = stage_and_optionally_build_pkg(
                repo_root=REPO_ROOT,
                staging_dir=staging,
                requested_pkg_name="IV0000-BREW00001_00-PS4LDESKTOP0000.pkg",
                output_pkg_path=out_pkg,
            )
            self.assertFalse(rep.pkg_built)
            self.assertFalse(out_pkg.exists())
            self.assertTrue((staging / "sce_sys" / "param.sfo").is_file())
            self.assertTrue((staging / "sce_sys" / "icon0.png").is_file())
            self.assertTrue((staging / "assets" / "boot" / "initramfs.cpio.gz").is_file())
            self.assertTrue((staging / "pkg.gp4").is_file())
            self.assertGreaterEqual(len(rep.blocking_reasons), 5)


if __name__ == "__main__":
    unittest.main()

