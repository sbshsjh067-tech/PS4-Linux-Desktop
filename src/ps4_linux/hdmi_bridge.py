"""PS4 Panasonic MN86471A / MN864729 DP->HDMI Bridge Inspector & Keep-Alive Engine.

Hardware architecture (verified from drivers/gpu/drm/amd/amdgpu/ps4_bridge.c):
  - PS4 Fat CUH-10xx/11xx (Aeolia, PCI 1002:9920): Panasonic MN86471A bridge.
  - PS4 Fat CUH-12xx (Belize, PCI 1002:9922 / 1002:9923) & Slim/Pro (1002:9924):
    Panasonic MN864729 bridge.

On MN864729 consoles (including CUH-12xx PS4 Fat Belize), TV HDMI re-handshakes
or modesets can clear HDMI output enable registers (0x1e00 bit 0, 0x1e02 bits 4..6)
and set video mute (VMUTECNT 0x705f bit 7 = CCVMUTE), causing "No Signal" black
screens even while Linux and KDE Plasma are running normally.

Safety rule:
  Hardware ioctls to /dev/icc (char major 73, minor 0, ICC service 0x10) are ONLY
  issued when a genuine PS4 GPU PCI ID (1002:9920..9924) is detected or an explicit
  mock transport is supplied for automated testing.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import fcntl
import os
from pathlib import Path
import struct
from typing import Protocol

from . import AMD_VENDOR_ID, PS4_GPU_PCI_IDS

ICC_DEV_PATH = "/dev/icc"
ICC_MAJOR_NR = 73
ICC_BRIDGE_SERVICE = 0x10

# Register map from drivers/gpu/drm/amd/amdgpu/ps4_bridge.c
REG_HDMI_OUT_EN = 0x1E00       # bit 0 = master HDMI output enable (MN864729)
REG_HDMI_LANE_EN = 0x1E02      # bits 4..6 (0x70) = TMDS lane output enables
REG_TSYSCTRL = 0x7005          # bit 7 = HDMI mode (vs DVI)
REG_TMONREG = 0x7008           # bit 3 = monitor HPD present
REG_VMUTECNT = 0x705F          # bit 7 = CCVMUTE (video mute active), 0x10 = unmuted normal

CMD_READ = (1, 1)
CMD_WRITE = (2, 2)
CMD_MASK = (2, 3)


class _IccCmdStruct(ctypes.Structure):
    _fields_ = [
        ("major", ctypes.c_uint8),
        ("minor", ctypes.c_uint16),
        ("data", ctypes.c_void_p),
        ("length", ctypes.c_uint16),
        ("reply", ctypes.c_void_p),
        ("reply_length", ctypes.c_uint16),
    ]


ICC_IOCTL_CMD = (3 << 30) | (ctypes.sizeof(_IccCmdStruct) << 16) | (ord("I") << 8) | 1


class BridgeTransport(Protocol):
    def read_reg(self, addr: int) -> int: ...
    def write_reg(self, addr: int, val: int) -> None: ...
    def mask_reg(self, addr: int, val: int, mask: int) -> None: ...


class IccBridgeTransport:
    """Real PS4 /dev/icc I2C command-queue transport for MN86471A / MN864729."""

    def __init__(self, dev_path: str = ICC_DEV_PATH) -> None:
        self.dev_path = dev_path
        self._fd: int | None = None

    def open(self) -> None:
        if self._fd is not None:
            return
        if not os.path.exists(self.dev_path):
            raise FileNotFoundError(f"{self.dev_path} not present (PS4 ICC driver not loaded)")
        self._fd = os.open(self.dev_path, os.O_RDWR)

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def _queue(self, ops: list[tuple[tuple[int, int], bytes]], code: int = 4) -> bytes:
        self.open()
        assert self._fd is not None
        body = b""
        groups = 0
        idx = 0
        while idx < len(ops):
            kind = ops[idx][0]
            chunk = b""
            count = 0
            while idx < len(ops) and ops[idx][0] == kind:
                chunk += ops[idx][1]
                count += 1
                idx += 1
            body += struct.pack("<BBBB", kind[0], 4 + len(chunk), kind[1], count) + chunk
            groups += 1
        req = struct.pack("<BHB", code, 4 + len(body), groups) + body

        data_buf = ctypes.create_string_buffer(req, len(req))
        reply_len = 0x7F0
        reply_buf = ctypes.create_string_buffer(reply_len)
        cmd = _IccCmdStruct(
            ICC_BRIDGE_SERVICE,
            0,
            ctypes.cast(data_buf, ctypes.c_void_p),
            len(req),
            ctypes.cast(reply_buf, ctypes.c_void_p),
            reply_len,
        )
        n = fcntl.ioctl(self._fd, ICC_IOCTL_CMD, cmd)
        raw = reply_buf.raw
        if n < 5 or raw[0] != 0 or raw[1] != 0:
            raise RuntimeError(f"ICC bridge command failed: n={n} status=({raw[0]}, {raw[1]})")
        return raw[:n]

    def read_reg(self, addr: int) -> int:
        payload = bytes([1]) + struct.pack(">H", addr) + b"\x00"
        rep = self._queue([(CMD_READ, payload)], code=1)
        if len(rep) < 9:
            raise RuntimeError(f"Short ICC bridge read reply ({len(rep)} bytes)")
        return rep[8]

    def write_reg(self, addr: int, val: int) -> None:
        payload = b"\x01" + struct.pack(">H", addr) + bytes([val & 0xFF])
        self._queue([(CMD_WRITE, payload)], code=4)

    def mask_reg(self, addr: int, val: int, mask: int) -> None:
        payload = b"\x01" + struct.pack(">H", addr) + bytes([val & 0xFF, mask & 0xFF])
        self._queue([(CMD_MASK, payload)], code=4)


class MemoryBridgeTransport:
    """In-memory MN86471A / MN864729 register simulator for automated unit tests."""

    def __init__(self, initial: dict[int, int] | None = None) -> None:
        self.regs: dict[int, int] = {
            REG_HDMI_OUT_EN: 0x01,
            REG_HDMI_LANE_EN: 0x70,
            REG_TSYSCTRL: 0x80,
            REG_TMONREG: 0x08,
            REG_VMUTECNT: 0x10,
        }
        if initial:
            self.regs.update(initial)
        self.write_log: list[tuple[str, int, int, int]] = []

    def read_reg(self, addr: int) -> int:
        return self.regs.get(addr, 0x00) & 0xFF

    def write_reg(self, addr: int, val: int) -> None:
        self.regs[addr] = val & 0xFF
        self.write_log.append(("write", addr, val & 0xFF, 0xFF))

    def mask_reg(self, addr: int, val: int, mask: int) -> None:
        cur = self.regs.get(addr, 0x00)
        self.regs[addr] = ((cur & ~mask) | (val & mask)) & 0xFF
        self.write_log.append(("mask", addr, val & 0xFF, mask & 0xFF))


@dataclass
class BridgeHealth:
    ps4_gpu_detected: bool
    pci_device_id: str
    bridge_chip: str
    affected_by_mute_quirk: bool
    icc_accessible: bool
    monitor_hpd_sense: bool | None
    output_enabled: bool | None
    video_muted: bool | None
    unmute_applied: bool
    notes: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "ps4_gpu_detected": self.ps4_gpu_detected,
            "pci_device_id": self.pci_device_id,
            "bridge_chip": self.bridge_chip,
            "affected_by_mute_quirk": self.affected_by_mute_quirk,
            "icc_accessible": self.icc_accessible,
            "monitor_hpd_sense": self.monitor_hpd_sense,
            "output_enabled": self.output_enabled,
            "video_muted": self.video_muted,
            "unmute_applied": self.unmute_applied,
            "notes": list(self.notes),
        }


def detect_ps4_gpu_pci_id(sysfs_root: Path = Path("/sys")) -> str | None:
    """Locate a PS4 Liverpool/Gladius PCI GPU device in sysfs."""
    candidates = [sysfs_root / "bus/pci/devices/0000:00:01.0"]
    drm_dir = sysfs_root / "class/drm"
    if drm_dir.is_dir():
        for card in sorted(drm_dir.glob("card[0-9]*")):
            if "-" not in card.name:
                candidates.append(card / "device")

    for dev in candidates:
        vendor_file = dev / "vendor"
        device_file = dev / "device"
        if vendor_file.is_file() and device_file.is_file():
            vendor = vendor_file.read_text(encoding="utf-8", errors="ignore").strip().lower()
            device = device_file.read_text(encoding="utf-8", errors="ignore").strip().lower()
            if vendor == AMD_VENDOR_ID and device in PS4_GPU_PCI_IDS:
                return device
    return None


def check_and_heal_hdmi_bridge(
    sysfs_root: Path = Path("/sys"),
    icc_dev_path: str = ICC_DEV_PATH,
    transport: BridgeTransport | None = None,
    auto_unmute: bool = True,
) -> BridgeHealth:
    """Inspect PS4 DP->HDMI bridge health and optionally unmute MN864729 output."""
    notes: list[str] = []
    pci_id = detect_ps4_gpu_pci_id(sysfs_root=sysfs_root)
    if not pci_id:
        return BridgeHealth(
            ps4_gpu_detected=False,
            pci_device_id="non-ps4",
            bridge_chip="none",
            affected_by_mute_quirk=False,
            icc_accessible=False,
            monitor_hpd_sense=None,
            output_enabled=None,
            video_muted=None,
            unmute_applied=False,
            notes=["Host does not expose a PS4 Liverpool/Gladius PCI ID (1002:9920..9924); skipping ICC ioctl."],
        )

    meta = PS4_GPU_PCI_IDS[pci_id]
    bridge_chip = meta["hdmi_bridge"]
    affected = meta["bridge_mute_quirk"] == "true"

    if not affected and transport is None:
        notes.append(
            f"GPU {pci_id} uses {bridge_chip} (Aeolia Fat); not affected by MN864729 self-mute quirk."
        )
        return BridgeHealth(
            ps4_gpu_detected=True,
            pci_device_id=pci_id,
            bridge_chip=bridge_chip,
            affected_by_mute_quirk=False,
            icc_accessible=os.path.exists(icc_dev_path),
            monitor_hpd_sense=None,
            output_enabled=True,
            video_muted=False,
            unmute_applied=False,
            notes=notes,
        )

    owns_transport = False
    if transport is None:
        if not os.path.exists(icc_dev_path):
            notes.append(f"{icc_dev_path} missing; cannot query {bridge_chip} registers.")
            return BridgeHealth(
                ps4_gpu_detected=True,
                pci_device_id=pci_id,
                bridge_chip=bridge_chip,
                affected_by_mute_quirk=affected,
                icc_accessible=False,
                monitor_hpd_sense=None,
                output_enabled=None,
                video_muted=None,
                unmute_applied=False,
                notes=notes,
            )
        if os.geteuid() != 0:
            notes.append(f"Root privileges required to open {icc_dev_path} for {bridge_chip} keep-alive.")
            return BridgeHealth(
                ps4_gpu_detected=True,
                pci_device_id=pci_id,
                bridge_chip=bridge_chip,
                affected_by_mute_quirk=affected,
                icc_accessible=False,
                monitor_hpd_sense=None,
                output_enabled=None,
                video_muted=None,
                unmute_applied=False,
                notes=notes,
            )
        transport = IccBridgeTransport(dev_path=icc_dev_path)
        owns_transport = True

    try:
        tmon = transport.read_reg(REG_TMONREG)
        out_en = transport.read_reg(REG_HDMI_OUT_EN)
        vmute = transport.read_reg(REG_VMUTECNT)

        hpd = bool(tmon & 0x08)
        enabled = bool(out_en & 0x01)
        muted = bool(vmute & 0x80)
        unmuted_now = False

        if affected and auto_unmute and (not enabled or muted):
            transport.mask_reg(REG_HDMI_LANE_EN, 0x70, 0x70)
            transport.mask_reg(REG_HDMI_OUT_EN, 0x01, 0x01)
            transport.write_reg(REG_VMUTECNT, 0x10)
            unmuted_now = True
            enabled = bool(transport.read_reg(REG_HDMI_OUT_EN) & 0x01)
            muted = bool(transport.read_reg(REG_VMUTECNT) & 0x80)
            notes.append(
                f"MN864729 bridge had output disabled/muted (0x1e00=0x{out_en:02x}, 0x705f=0x{vmute:02x}); restored output and cleared CCVMUTE."
            )
        else:
            notes.append(
                f"{bridge_chip} healthy (TMON=0x{tmon:02x}, 0x1e00=0x{out_en:02x}, VMUTE=0x{vmute:02x})."
            )

        return BridgeHealth(
            ps4_gpu_detected=True,
            pci_device_id=pci_id,
            bridge_chip=bridge_chip,
            affected_by_mute_quirk=affected,
            icc_accessible=True,
            monitor_hpd_sense=hpd,
            output_enabled=enabled,
            video_muted=muted,
            unmute_applied=unmuted_now,
            notes=notes,
        )
    except Exception as exc:
        notes.append(f"Bridge register inspection failed: {exc}")
        return BridgeHealth(
            ps4_gpu_detected=True,
            pci_device_id=pci_id,
            bridge_chip=bridge_chip,
            affected_by_mute_quirk=affected,
            icc_accessible=False,
            monitor_hpd_sense=None,
            output_enabled=None,
            video_muted=None,
            unmute_applied=False,
            notes=notes,
        )
    finally:
        if owns_transport and isinstance(transport, IccBridgeTransport):
            transport.close()
