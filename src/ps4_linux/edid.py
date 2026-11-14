"""Binary EDID 1.3/1.4 & CEA-861 Extension Parser for PS4 HDMI Display Protection.

Parses raw 128-byte / 256-byte EDID payloads from `/sys/class/drm/card*-HDMI-A-*/edid`:
  - Validates 8-byte EDID magic header and per-128-byte block checksums
  - Extracts Manufacturer PNP ID, Monitor Name, Range Limits (min/max VHz, max MHz)
  - Extracts Established Timings I/II/III, Standard Timings (1..8), Detailed Timing
    Descriptors (DTDs, marking the first DTD as Preferred Native Timing)
  - Parses CEA-861 Extension Blocks (0x02): Short Video Descriptors (VIC 1..107),
    Audio Data Blocks (LPCM HDMI audio capability), and HDMI Vendor-Specific Data
    Block (IEEE OUI 00-0C-03, Deep Color support flags, max TMDS clock)
"""

from __future__ import annotations

from dataclasses import dataclass, field
import struct
from typing import Iterable

EDID_HEADER = b"\x00\xff\xff\xff\xff\xff\xff\x00"

# Established Timings I & II (byte 35 & byte 36) -> (width, height, refresh_hz, interlaced)
ESTABLISHED_TIMINGS_I: list[tuple[int, int, int, int, bool]] = [
    (0x80, 720, 400, 70, False),
    (0x40, 720, 400, 88, False),
    (0x20, 640, 480, 60, False),
    (0x10, 640, 480, 67, False),
    (0x08, 640, 480, 72, False),
    (0x04, 640, 480, 75, False),
    (0x02, 800, 600, 56, False),
    (0x01, 800, 600, 60, False),
]

ESTABLISHED_TIMINGS_II: list[tuple[int, int, int, int, bool]] = [
    (0x80, 800, 600, 72, False),
    (0x40, 800, 600, 75, False),
    (0x20, 832, 624, 75, False),
    (0x10, 1024, 768, 87, True),
    (0x08, 1024, 768, 60, False),
    (0x04, 1024, 768, 70, False),
    (0x02, 1024, 768, 75, False),
    (0x01, 1280, 1024, 75, False),
]

# CEA-861 Video Identification Codes (VIC) -> (width, height, refresh_hz, interlaced, pixel_clock_khz)
CEA_VIC_MODES: dict[int, tuple[int, int, int, bool, int]] = {
    1: (640, 480, 60, False, 25_175),
    2: (720, 480, 60, False, 27_000),
    3: (720, 480, 60, False, 27_000),
    4: (1280, 720, 60, False, 74_250),
    5: (1920, 1080, 60, True, 74_250),
    16: (1920, 1080, 60, False, 148_500),
    17: (720, 576, 50, False, 27_000),
    18: (720, 576, 50, False, 27_000),
    19: (1280, 720, 50, False, 74_250),
    20: (1920, 1080, 50, True, 74_250),
    31: (1920, 1080, 50, False, 148_500),
    32: (1920, 1080, 24, False, 74_250),
    33: (1920, 1080, 25, False, 74_250),
    34: (1920, 1080, 30, False, 74_250),
    60: (1280, 720, 24, False, 59_400),
    62: (1280, 720, 30, False, 74_250),
    93: (3840, 2160, 24, False, 297_000),
    95: (3840, 2160, 30, False, 297_000),
    96: (3840, 2160, 50, False, 594_000),
    97: (3840, 2160, 60, False, 594_000),
}


@dataclass(frozen=True)
class DisplayMode:
    width: int
    height: int
    refresh_hz: int
    interlaced: bool = False
    preferred: bool = False
    pixel_clock_khz: int = 0
    source: str = "edid"

    @property
    def kms_mode_str(self) -> str:
        suffix = "i" if self.interlaced else ""
        return f"{self.width}x{self.height}{suffix}@{self.refresh_hz}"

    @property
    def drm_mode_name(self) -> str:
        suffix = "i" if self.interlaced else ""
        return f"{self.width}x{self.height}{suffix}"

    @property
    def pixels(self) -> int:
        return self.width * self.height


@dataclass
class RangeLimits:
    min_vrate_hz: int
    max_vrate_hz: int
    min_hrate_khz: int
    max_hrate_khz: int
    max_pixel_clock_mhz: int


@dataclass
class EdidInfo:
    valid: bool
    raw_size: int
    checksum_ok: bool
    manufacturer: str = ""
    product_code: int = 0
    serial_number: int = 0
    manufacture_year: int = 0
    edid_version: str = ""
    digital_input: bool = True
    monitor_name: str = ""
    range_limits: RangeLimits | None = None
    has_cea_extension: bool = False
    has_hdmi_vsdb: bool = False
    supports_basic_audio: bool = False
    deep_color_30bit: bool = False
    deep_color_36bit: bool = False
    max_tmds_clock_mhz: int = 0
    modes: list[DisplayMode] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def unique_resolutions(self) -> list[str]:
        seen: dict[tuple[int, int, bool], str] = {}
        for m in sorted(self.modes, key=lambda x: (-x.pixels, x.interlaced)):
            key = (m.width, m.height, m.interlaced)
            if key not in seen:
                seen[key] = m.drm_mode_name
        return list(seen.values())

    def supported_refresh_rates(self, width: int | None = None, height: int | None = None) -> list[int]:
        rates = {
            m.refresh_hz
            for m in self.modes
            if (width is None or m.width == width) and (height is None or m.height == height)
        }
        return sorted(rates, reverse=True)

    def to_dict(self) -> dict[str, object]:
        return {
            "valid": self.valid,
            "raw_size": self.raw_size,
            "checksum_ok": self.checksum_ok,
            "manufacturer": self.manufacturer,
            "product_code": self.product_code,
            "monitor_name": self.monitor_name,
            "edid_version": self.edid_version,
            "digital_input": self.digital_input,
            "has_cea_extension": self.has_cea_extension,
            "has_hdmi_vsdb": self.has_hdmi_vsdb,
            "supports_basic_audio": self.supports_basic_audio,
            "deep_color_30bit": self.deep_color_30bit,
            "deep_color_36bit": self.deep_color_36bit,
            "max_tmds_clock_mhz": self.max_tmds_clock_mhz,
            "range_limits": (
                {
                    "min_vrate_hz": self.range_limits.min_vrate_hz,
                    "max_vrate_hz": self.range_limits.max_vrate_hz,
                    "max_pixel_clock_mhz": self.range_limits.max_pixel_clock_mhz,
                }
                if self.range_limits
                else None
            ),
            "modes": [
                {
                    "mode": m.kms_mode_str,
                    "width": m.width,
                    "height": m.height,
                    "refresh_hz": m.refresh_hz,
                    "interlaced": m.interlaced,
                    "preferred": m.preferred,
                    "pixel_clock_khz": m.pixel_clock_khz,
                    "source": m.source,
                }
                for m in self.modes
            ],
            "errors": list(self.errors),
        }


def _decode_manufacturer(raw2: bytes) -> str:
    val = (raw2[0] << 8) | raw2[1]
    c1 = ((val >> 10) & 0x1F) + ord("A") - 1
    c2 = ((val >> 5) & 0x1F) + ord("A") - 1
    c3 = (val & 0x1F) + ord("A") - 1
    if all(ord("A") <= c <= ord("Z") for c in (c1, c2, c3)):
        return chr(c1) + chr(c2) + chr(c3)
    return "UNK"


def _encode_manufacturer(pnp: str) -> bytes:
    p = (pnp.upper() + "AAA")[:3]
    val = (
        (((ord(p[0]) - ord("A") + 1) & 0x1F) << 10)
        | (((ord(p[1]) - ord("A") + 1) & 0x1F) << 5)
        | ((ord(p[2]) - ord("A") + 1) & 0x1F)
    )
    return bytes([(val >> 8) & 0xFF, val & 0xFF])


def _parse_dtd(desc: bytes, preferred: bool = False, source: str = "dtd") -> DisplayMode | None:
    if len(desc) < 18:
        return None
    pclk_10khz = desc[0] | (desc[1] << 8)
    if pclk_10khz == 0:
        return None
    pclk_khz = pclk_10khz * 10
    h_active = desc[2] | ((desc[4] & 0xF0) << 4)
    h_blank = desc[3] | ((desc[4] & 0x0F) << 8)
    v_active = desc[5] | ((desc[7] & 0xF0) << 4)
    v_blank = desc[6] | ((desc[7] & 0x0F) << 8)
    interlaced = bool(desc[17] & 0x80)
    h_total = h_active + h_blank
    v_total = v_active + v_blank
    if h_active <= 0 or v_active <= 0 or h_total <= 0 or v_total <= 0:
        return None
    v_lines = v_active * 2 if interlaced else v_active
    raw_hz = (pclk_khz * 1000.0) / (h_total * v_total)
    refresh_hz = int(round(raw_hz))
    if refresh_hz <= 0 or refresh_hz > 240:
        return None
    return DisplayMode(
        width=h_active,
        height=v_lines,
        refresh_hz=refresh_hz,
        interlaced=interlaced,
        preferred=preferred,
        pixel_clock_khz=pclk_khz,
        source=source,
    )


def _dedupe_modes(modes: Iterable[DisplayMode]) -> list[DisplayMode]:
    by_key: dict[tuple[int, int, int, bool], DisplayMode] = {}
    for m in modes:
        key = (m.width, m.height, m.refresh_hz, m.interlaced)
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = m
        else:
            # Preserve preferred=True and non-zero pixel clock
            if m.preferred and not existing.preferred:
                by_key[key] = m
            elif existing.pixel_clock_khz == 0 and m.pixel_clock_khz > 0:
                by_key[key] = DisplayMode(
                    width=existing.width,
                    height=existing.height,
                    refresh_hz=existing.refresh_hz,
                    interlaced=existing.interlaced,
                    preferred=existing.preferred or m.preferred,
                    pixel_clock_khz=m.pixel_clock_khz,
                    source=existing.source,
                )
    return sorted(
        by_key.values(),
        key=lambda x: (not x.preferred, x.interlaced, -x.pixels, -x.refresh_hz),
    )


def parse_edid(raw: bytes) -> EdidInfo:
    """Parse raw EDID bytes (128 or 256+ bytes) into structured EdidInfo."""
    if not raw:
        return EdidInfo(
            valid=False,
            raw_size=0,
            checksum_ok=False,
            errors=["EDID payload is empty (0 bytes)"],
        )
    if len(raw) < 128:
        return EdidInfo(
            valid=False,
            raw_size=len(raw),
            checksum_ok=False,
            errors=[f"EDID payload truncated ({len(raw)} bytes < 128 bytes)"],
        )

    base = raw[:128]
    errors: list[str] = []
    if base[:8] != EDID_HEADER:
        errors.append("Invalid 8-byte EDID base header")
        return EdidInfo(
            valid=False,
            raw_size=len(raw),
            checksum_ok=False,
            errors=errors,
        )

    base_checksum_ok = (sum(base) & 0xFF) == 0
    if not base_checksum_ok:
        errors.append(f"EDID base block checksum invalid (sum mod 256 = {sum(base) & 0xFF})")

    manufacturer = _decode_manufacturer(base[8:10])
    product_code = struct.unpack("<H", base[10:12])[0]
    serial_number = struct.unpack("<I", base[12:16])[0]
    manufacture_year = 1990 + base[17]
    edid_version = f"{base[18]}.{base[19]}"
    digital_input = bool(base[20] & 0x80)
    preferred_timing_in_dtd1 = bool(base[24] & 0x02)

    modes: list[DisplayMode] = []

    # 1. Established Timings I & II (bytes 35, 36) + Manuf (37 bit 7 = 1152x870@75)
    b35, b36, b37 = base[35], base[36], base[37]
    for mask, w, h, hz, inter in ESTABLISHED_TIMINGS_I:
        if b35 & mask:
            modes.append(DisplayMode(w, h, hz, inter, False, 0, "established"))
    for mask, w, h, hz, inter in ESTABLISHED_TIMINGS_II:
        if b36 & mask:
            modes.append(DisplayMode(w, h, hz, inter, False, 0, "established"))
    if b37 & 0x80:
        modes.append(DisplayMode(1152, 870, 75, False, False, 0, "established"))

    # 2. Standard Timings (bytes 38..53, 8 pairs)
    for offset in range(38, 54, 2):
        b0, b1 = base[offset], base[offset + 1]
        if (b0, b1) in ((0x01, 0x01), (0x00, 0x00), (0x20, 0x20)):
            continue
        width = (b0 + 31) * 8
        aspect = (b1 >> 6) & 0x03
        if aspect == 0:
            height = (width * 10) // 16 if (base[18], base[19]) >= (1, 3) else width
        elif aspect == 1:
            height = (width * 3) // 4
        elif aspect == 2:
            height = (width * 4) // 5
        else:
            height = (width * 9) // 16
        refresh_hz = (b1 & 0x3F) + 60
        modes.append(DisplayMode(width, height, refresh_hz, False, False, 0, "standard"))

    # 3. Four 18-byte descriptors (bytes 54..125)
    monitor_name = ""
    range_limits: RangeLimits | None = None
    first_dtd_seen = False
    for idx in range(4):
        start = 54 + idx * 18
        desc = base[start : start + 18]
        if desc[0] != 0 or desc[1] != 0:
            is_pref = (not first_dtd_seen) and (preferred_timing_in_dtd1 or idx == 0)
            first_dtd_seen = True
            dtd_mode = _parse_dtd(desc, preferred=is_pref, source="dtd")
            if dtd_mode:
                modes.append(dtd_mode)
        else:
            tag = desc[3]
            if tag == 0xFC:  # Monitor Name
                monitor_name = desc[5:18].decode("ascii", errors="ignore").split("\n")[0].strip()
            elif tag == 0xFD:  # Monitor Range Limits
                v_min_off = 255 if (desc[4] & 0x01) else 0
                v_max_off = 255 if (desc[4] & 0x02) else 0
                h_min_off = 255 if (desc[4] & 0x04) else 0
                h_max_off = 255 if (desc[4] & 0x08) else 0
                range_limits = RangeLimits(
                    min_vrate_hz=desc[5] + v_min_off,
                    max_vrate_hz=desc[6] + v_max_off,
                    min_hrate_khz=desc[7] + h_min_off,
                    max_hrate_khz=desc[8] + h_max_off,
                    max_pixel_clock_mhz=desc[9] * 10,
                )

    # 4. Extension Blocks (CEA-861 = tag 0x02)
    ext_count = base[126]
    has_cea = False
    has_hdmi_vsdb = False
    supports_audio = False
    dc_30 = False
    dc_36 = False
    max_tmds_mhz = 0
    all_checksums_ok = base_checksum_ok

    available_exts = min(ext_count, (len(raw) - 128) // 128)
    if ext_count > available_exts:
        errors.append(
            f"EDID declares {ext_count} extension block(s) but only {available_exts} present"
        )

    for ext_i in range(available_exts):
        ext = raw[128 * (ext_i + 1) : 128 * (ext_i + 2)]
        if (sum(ext) & 0xFF) != 0:
            all_checksums_ok = False
            errors.append(f"Extension block {ext_i + 1} checksum invalid")
        if ext[0] != 0x02:
            continue

        has_cea = True
        dtd_offset = ext[2]
        supports_audio = supports_audio or bool(ext[3] & 0x40)

        if 4 <= dtd_offset <= 127:
            pos = 4
            while pos < dtd_offset:
                hdr = ext[pos]
                blk_tag = (hdr >> 5) & 0x07
                blk_len = hdr & 0x1F
                payload = ext[pos + 1 : min(pos + 1 + blk_len, dtd_offset)]
                pos += 1 + blk_len

                if blk_tag == 2:  # Video Data Block (SVDs)
                    for svd in payload:
                        native = bool(svd & 0x80) and (1 <= (svd & 0x7F) <= 64)
                        vic = (svd & 0x7F) if (1 <= (svd & 0x7F) <= 64) else svd
                        if vic in CEA_VIC_MODES:
                            w, h, hz, inter, pclk = CEA_VIC_MODES[vic]
                            modes.append(
                                DisplayMode(
                                    width=w,
                                    height=h,
                                    refresh_hz=hz,
                                    interlaced=inter,
                                    preferred=native,
                                    pixel_clock_khz=pclk,
                                    source=f"cea_vic_{vic}",
                                )
                            )
                elif blk_tag == 1:  # Audio Data Block
                    if payload:
                        supports_audio = True
                elif blk_tag == 3 and len(payload) >= 3:  # Vendor-Specific Data Block
                    oui = (payload[2] << 16) | (payload[1] << 8) | payload[0]
                    if oui == 0x000C03:  # HDMI Licensing, LLC
                        has_hdmi_vsdb = True
                        if len(payload) >= 6:
                            dc_flags = payload[5]
                            dc_30 = bool(dc_flags & 0x10)
                            dc_36 = bool(dc_flags & 0x20)
                        if len(payload) >= 7 and payload[6] > 0:
                            max_tmds_mhz = payload[6] * 5

            # Parse DTDs inside CEA extension
            cea_pos = dtd_offset
            while cea_pos + 18 <= 127:
                desc = ext[cea_pos : cea_pos + 18]
                if desc[0] == 0 and desc[1] == 0:
                    break
                cea_dtd = _parse_dtd(desc, preferred=False, source="cea_dtd")
                if cea_dtd:
                    modes.append(cea_dtd)
                cea_pos += 18

    deduped = _dedupe_modes(modes)
    return EdidInfo(
        valid=base_checksum_ok,
        raw_size=len(raw),
        checksum_ok=all_checksums_ok,
        manufacturer=manufacturer,
        product_code=product_code,
        serial_number=serial_number,
        manufacture_year=manufacture_year,
        edid_version=edid_version,
        digital_input=digital_input,
        monitor_name=monitor_name,
        range_limits=range_limits,
        has_cea_extension=has_cea,
        has_hdmi_vsdb=has_hdmi_vsdb,
        supports_basic_audio=supports_audio,
        deep_color_30bit=dc_30,
        deep_color_36bit=dc_36,
        max_tmds_clock_mhz=max_tmds_mhz,
        modes=deduped,
        errors=errors,
    )


def _pack_dtd(
    width: int,
    height: int,
    h_blank: int,
    v_blank: int,
    pixel_clock_khz: int,
    interlaced: bool = False,
) -> bytes:
    b = bytearray(18)
    pclk_10khz = pixel_clock_khz // 10
    b[0] = pclk_10khz & 0xFF
    b[1] = (pclk_10khz >> 8) & 0xFF
    b[2] = width & 0xFF
    b[3] = h_blank & 0xFF
    b[4] = (((width >> 8) & 0x0F) << 4) | ((h_blank >> 8) & 0x0F)
    v_lines = height // 2 if interlaced else height
    b[5] = v_lines & 0xFF
    b[6] = v_blank & 0xFF
    b[7] = (((v_lines >> 8) & 0x0F) << 4) | ((v_blank >> 8) & 0x0F)
    b[8] = 48  # hsync offset
    b[9] = 32  # hsync pulse
    b[10] = (3 << 4) | 5  # vsync offset / pulse
    b[12] = 0x0F  # image size placeholder
    b[13] = 0x09
    b[17] = (0x80 if interlaced else 0x00) | 0x1E
    return bytes(b)


def build_synthetic_edid(
    monitor_name: str = "PS4-SAFE-TV",
    manufacturer: str = "SNY",
    preferred_mode: tuple[int, int, int] = (1920, 1080, 60),
    cea_vics: tuple[int, ...] = (16, 4, 31, 19, 2, 1),
    include_cea: bool = True,
    deep_color: bool = False,
    max_vrate_hz: int = 60,
    max_pclk_mhz: int = 170,
    corrupt_checksum: bool = False,
) -> bytes:
    """Build a standards-compliant 128-byte or 256-byte EDID 1.3 + CEA-861 binary."""
    base = bytearray(128)
    base[0:8] = EDID_HEADER
    base[8:10] = _encode_manufacturer(manufacturer)
    base[10:12] = struct.pack("<H", 0x1200)
    base[12:16] = struct.pack("<I", 1)
    base[16] = 1
    base[17] = 36  # 2026
    base[18] = 1
    base[19] = 3
    base[20] = 0x80  # Digital input
    base[21] = 52
    base[22] = 29
    base[23] = 120  # gamma 2.2
    base[24] = 0x0A  # RGB + preferred timing in DTD 1
    base[35] = 0x21  # 640x480@60 + 800x600@60
    base[36] = 0x08  # 1024x768@60
    for off in range(38, 54, 2):
        base[off] = 0x01
        base[off + 1] = 0x01

    # DTD 1: Preferred Timing
    pw, ph, phz = preferred_mode
    if (pw, ph, phz) == (1920, 1080, 60):
        dtd1 = _pack_dtd(1920, 1080, 280, 45, 148_500)
    elif (pw, ph, phz) == (1920, 1080, 50):
        dtd1 = _pack_dtd(1920, 1080, 720, 45, 148_500)
    elif (pw, ph, phz) == (1366, 768, 60):
        dtd1 = _pack_dtd(1366, 768, 426, 30, 85_500)
    elif (pw, ph, phz) == (1280, 720, 60):
        dtd1 = _pack_dtd(1280, 720, 370, 30, 74_250)
    elif (pw, ph, phz) == (3840, 2160, 60):
        dtd1 = _pack_dtd(3840, 2160, 560, 90, 594_000)
    else:
        h_blank = max(160, pw // 5)
        v_blank = max(25, ph // 24)
        pclk_khz = ((pw + h_blank) * (ph + v_blank) * phz) // 1000
        dtd1 = _pack_dtd(pw, ph, h_blank, v_blank, pclk_khz)
    base[54:72] = dtd1

    # Descriptor 2: Monitor Name (0xFC)
    name_desc = bytearray(18)
    name_desc[3] = 0xFC
    padded_name = (monitor_name[:12] + "\n").ljust(13, " ").encode("ascii", errors="ignore")
    name_desc[5:18] = padded_name
    base[72:90] = name_desc

    # Descriptor 3: Monitor Range Limits (0xFD)
    range_desc = bytearray(18)
    range_desc[3] = 0xFD
    range_desc[5] = 24
    range_desc[6] = min(255, max_vrate_hz)
    range_desc[7] = 15
    range_desc[8] = 90
    range_desc[9] = max(1, max_pclk_mhz // 10)
    range_desc[10] = 0x00
    base[90:108] = range_desc

    # Descriptor 4: Dummy (0x10)
    dummy_desc = bytearray(18)
    dummy_desc[3] = 0x10
    base[108:126] = dummy_desc

    base[126] = 1 if include_cea else 0
    base[127] = (-sum(base[:127])) & 0xFF
    if corrupt_checksum:
        base[127] ^= 0x55

    if not include_cea:
        return bytes(base)

    ext = bytearray(128)
    ext[0] = 0x02  # CEA-861
    ext[1] = 0x03  # Rev 3
    ext[3] = 0x70  # Underscan + basic audio + YCbCr 4:4:4 + 4:2:2

    pos = 4
    if cea_vics:
        svd_bytes = bytearray()
        for idx, vic in enumerate(cea_vics):
            if idx == 0 and 1 <= vic <= 64:
                svd_bytes.append(vic | 0x80)
            else:
                svd_bytes.append(vic & 0xFF)
        ext[pos] = (2 << 5) | (len(svd_bytes) & 0x1F)
        pos += 1
        ext[pos : pos + len(svd_bytes)] = svd_bytes
        pos += len(svd_bytes)

    # Audio Data Block: 2ch LPCM 32/44.1/48 kHz
    adb = bytes([0x09, 0x07, 0x07])
    ext[pos] = (1 << 5) | len(adb)
    pos += 1
    ext[pos : pos + len(adb)] = adb
    pos += len(adb)

    # HDMI Vendor-Specific Data Block (OUI 00-0C-03)
    dc_byte = 0x30 if deep_color else 0x00
    vsdb = bytes([0x03, 0x0C, 0x00, 0x10, 0x00, dc_byte, max(33, max_pclk_mhz // 5)])
    ext[pos] = (3 << 5) | len(vsdb)
    pos += 1
    ext[pos : pos + len(vsdb)] = vsdb
    pos += len(vsdb)

    ext[2] = pos  # DTD start offset (no extra DTDs -> 00 00 marks end)
    ext[127] = (-sum(ext[:127])) & 0xFF
    return bytes(base) + bytes(ext)
