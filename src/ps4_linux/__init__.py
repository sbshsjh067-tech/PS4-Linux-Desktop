"""PS4 Linux Desktop — Core Engineering & Diagnostic Suite.

Targets PlayStation 4 Fat (CUH-10xx/11xx Aeolia & CUH-12xx Belize) while
maintaining compatibility metadata for Slim/Pro revisions, enforcing all
binding safety decisions (D-01..D-08) from research/decisions.md.
"""

from __future__ import annotations

__version__ = "3.0.0"

# PS4 AMD APU GPU PCI IDs (Vendor 0x1002 = AMD/ATI)
AMD_VENDOR_ID = "0x1002"

PS4_GPU_PCI_IDS: dict[str, dict[str, str]] = {
    "0x9920": {
        "codename": "Liverpool",
        "gfx_level": "GFX7",
        "console_models": "CUH-10xx / CUH-11xx (PS4 Fat Launch)",
        "southbridge_hint": "aeolia",
        "hdmi_bridge": "MN86471A",
        "bridge_mute_quirk": "false",
    },
    "0x9922": {
        "codename": "Liverpool",
        "gfx_level": "GFX7",
        "console_models": "CUH-12xx (PS4 Fat 2015)",
        "southbridge_hint": "belize",
        "hdmi_bridge": "MN864729",
        "bridge_mute_quirk": "true",
    },
    "0x9923": {
        "codename": "Liverpool",
        "gfx_level": "GFX7",
        "console_models": "CUH-12xx / CUH-2xxx (PS4 Fat Belize / Slim)",
        "southbridge_hint": "belize",
        "hdmi_bridge": "MN864729",
        "bridge_mute_quirk": "true",
    },
    "0x9924": {
        "codename": "Gladius",
        "gfx_level": "GFX7",
        "console_models": "CUH-7xxx (PS4 Pro)",
        "southbridge_hint": "belize_or_baikal",
        "hdmi_bridge": "MN864729",
        "bridge_mute_quirk": "true",
    },
}

# Allowed VRAM carve-out values in MiB (Decision D-03, Ticket T-003)
ALLOWED_VRAM_MB: tuple[int, ...] = (32, 64, 128, 256, 512, 1024, 2048, 3072, 4096)
DEFAULT_DESKTOP_VRAM_MB: int = 1024
GAMING_PROFILE_VRAM_MB: int = 2048

# Forbidden CPU instruction sets on AMD Jaguar (btver2) — Ticket T-001, APP-003
FORBIDDEN_JAGUAR_FLAGS: tuple[str, ...] = ("avx2", "fma", "bmi2", "avx512f")

# Pinned upstream build inputs from research/14-pinned-inputs.lock.yaml (Decision D-07)
PINNED_KERNELS: dict[str, dict[str, str]] = {
    "primary_fat_7_0": {
        "id": "primary_fat_7_0",
        "repo": "https://github.com/feeRnt/ps4-linux-12xx",
        "branch": "7.0-Clean",
        "commit": "8ec5c282abda91f6c2e4014de206105aa7912516",
        "version": "7.0.0",
        "southbridges": "aeolia,belize",
        "fan_driver": "hwmon_ps4_fan",
        "mesa_lock": "true",
    },
    "fallback_fat_6_15": {
        "id": "fallback_fat_6_15",
        "repo": "https://github.com/feeRnt/ps4-linux-12xx",
        "branch": "6.15.4-aeolia-belize-crashniels",
        "commit": "3cba9d4db59422c8fc4dd55a39958def042e8816",
        "version": "6.15.4",
        "southbridges": "aeolia,belize",
        "fan_driver": "icc_userspace",
        "mesa_lock": "false",
    },
    "baikal_5_4": {
        "id": "baikal_5_4",
        "repo": "https://github.com/feeRnt/ps4-linux-12xx",
        "branch": "5.4.247-baikal-dfaus",
        "commit": "1fdfbd9a4c5690602893f6d5f65e154c6d9ba711",
        "version": "5.4.247",
        "southbridges": "baikal",
        "fan_driver": "icc_userspace",
        "mesa_lock": "false",
    },
}

PINNED_MESA: dict[str, object] = {
    "primary": {
        "version": "26.2.5",
        "sha256": "794b3d1729075dae7ebd47c7283b7ca0cdb5dec668f7f11cc0a5d82f6138a0a5",
        "libdrm_version": "2.4.134",
        "libdrm_sha256": "ac5e74d157830eb8bee44c6a6bf3ad49774ef0dd2a72bdad74a8f20308b52a95",
        "prefix": "/opt/ps4-mesa",
        "patches": [
            "0001-ps4-liverpool-gladius.patch",
            "0002-radv-ps4-no-hiz.patch",
            "0003-aco-ps4-no-flat-global.patch",
        ],
    },
    "control_b": "25.3.5",
    "control_c": "26.0.4",
    "vulkan_max": "1.3",
    "dxvk_max": "2.7.1",
    "proton_max": "11.0",
}

# PS4 Fat HDMI 1.4 hardware limits
PS4_FAT_MAX_WIDTH = 1920
PS4_FAT_MAX_HEIGHT = 1080
PS4_FAT_MAX_REFRESH_HZ = 60
PS4_FAT_MAX_PIXEL_CLOCK_KHZ = 165_000  # HDMI 1.4 single-link safe ceiling on Liverpool

# Thermal safety limits in Celsius (Decision SYS-002 / Ticket T-012)
THERMAL_FLOOR_C = 65
THERMAL_DEFAULT_TARGET_C = 72
THERMAL_MAX_SAFE_C = 80
THERMAL_HWMON_MIN_MC = 45_000
THERMAL_HWMON_MAX_MC = 85_000
