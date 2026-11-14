#!/usr/bin/env python3
"""Structural analysis of an Orbis FSELF (`\\x4f\\x15\\x3d\\x1d`) and the ELF inside it.

Why this exists: a launcher that crashes before it can print anything is almost
always a load-time problem - entry point outside a PT_LOAD, a non-PIE image, or
a DT_NEEDED module that is not shipped in the package. This prints those facts
so they can be compared against a known-good OpenOrbis sample build.

Usage: analyze_self.py <file> [<file>...]
Every fact is emitted as its own ::notice so it survives without raw logs.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

SELF_MAGIC = 0x1D3D154F
PT_LOAD, PT_DYNAMIC, PT_INTERP, PT_PHDR = 1, 2, 3, 6
DT_NEEDED, DT_STRTAB, DT_STRSZ, DT_SONAME, DT_FLAGS = 1, 5, 10, 14, 30


def notice(title: str, text: str) -> None:
    body = text.replace("%", "%25").replace("\r", " ").replace("\n", "%0A")[:1200]
    print(f"::notice title={title}::{body}")


def parse_self(data: bytes) -> dict:
    magic, version, mode, endian, attr = struct.unpack_from("<IBBBB", data, 0)
    key_type, header_size, meta_size = struct.unpack_from("<IHH", data, 8)
    file_size = struct.unpack_from("<Q", data, 0x10)[0]
    num_entries, flags = struct.unpack_from("<HH", data, 0x18)
    entries = []
    for i in range(min(num_entries, 32)):
        off = 0x20 + i * 0x20
        if off + 0x20 > len(data):
            break
        props, offset, size, _pad = struct.unpack_from("<QQQQ", data, off)
        entries.append(
            {
                "index": i,
                "props": props,
                "segment": (props >> 20) & 0xFFF,
                "encrypted": bool(props & 0x2),
                "offset": offset,
                "size": size,
            }
        )
    return {
        "magic": magic,
        "version": version,
        "mode": mode,
        "endian": endian,
        "attr": attr,
        "key_type": key_type,
        "header_size": header_size,
        "meta_size": meta_size,
        "file_size": file_size,
        "num_entries": num_entries,
        "flags": flags,
        "entries": entries,
    }


def find_elf(data: bytes, self_hdr: dict) -> tuple[int, dict]:
    """Return (offset, elf_header) of the ELF inside the SELF."""
    candidates = []
    for entry in self_hdr["entries"]:
        off = entry["offset"]
        if off + 4 <= len(data) and data[off : off + 4] == b"\x7fELF":
            candidates.append(off)
    if not candidates and data[self_hdr["header_size"] : self_hdr["header_size"] + 4] == b"\x7fELF":
        candidates.append(self_hdr["header_size"])
    if not candidates:
        idx = data.find(b"\x7fELF")
        if idx >= 0:
            candidates.append(idx)
    off = candidates[0]
    elf = data[off:]
    e_type, e_machine = struct.unpack_from("<HH", elf, 0x10)
    e_entry = struct.unpack_from("<Q", elf, 0x18)[0]
    e_phoff = struct.unpack_from("<Q", elf, 0x20)[0]
    e_shoff = struct.unpack_from("<Q", elf, 0x28)[0]
    e_flags = struct.unpack_from("<I", elf, 0x30)[0]
    e_phnum = struct.unpack_from("<H", elf, 0x38)[0]
    e_shnum = struct.unpack_from("<H", elf, 0x3C)[0]
    return off, {
        "e_type": e_type,
        "e_machine": e_machine,
        "e_entry": e_entry,
        "e_phoff": e_phoff,
        "e_phnum": e_phnum,
        "e_shoff": e_shoff,
        "e_shnum": e_shnum,
        "e_flags": e_flags,
        "image": elf,
    }


def analyse(path: Path) -> None:
    data = path.read_bytes()
    name = path.name
    if len(data) < 0x40 or struct.unpack_from("<I", data, 0)[0] != SELF_MAGIC:
        notice(f"self-{name}", f"NOT a SELF (first4={data[:4].hex()}) size={len(data)}")
        return

    hdr = parse_self(data)
    notice(
        f"self-{name}",
        f"size={len(data)} declared={hdr['file_size']} version={hdr['version']} "
        f"key_type=0x{hdr['key_type']:x} header_size={hdr['header_size']} "
        f"meta={hdr['meta_size']} entries={hdr['num_entries']} flags=0x{hdr['flags']:x} "
        f"attr=0x{hdr['attr']:x}",
    )

    segments = sorted({e["segment"] for e in hdr["entries"]})
    notice(f"self-segments-{name}", f"segment_ids={segments}")

    for entry in hdr["entries"]:
        if entry["offset"] == 0 and entry["size"] == 0:
            continue
        notice(
            f"self-entry-{name}-{entry['index']}",
            f"seg={entry['segment']} props=0x{entry['props']:x} enc={entry['encrypted']} "
            f"off=0x{entry['offset']:x} size=0x{entry['size']:x}",
        )

    try:
        elf_off, elf = find_elf(data, hdr)
    except Exception as exc:  # pragma: no cover - diagnostic
        notice(f"elf-{name}", f"no ELF found inside the SELF: {exc}")
        return

    image = elf["image"]
    type_name = {1: "ET_REL", 2: "ET_EXEC", 3: "ET_DYN"}.get(elf["e_type"], str(elf["e_type"]))
    notice(
        f"elf-{name}",
        f"offset=0x{elf_off:x} type={type_name} machine=0x{elf['e_machine']:x} "
        f"entry=0x{elf['e_entry']:x} phoff=0x{elf['e_phoff']:x} phnum={elf['e_phnum']} "
        f"shnum={elf['e_shnum']} flags=0x{elf['e_flags']:x}",
    )

    loads = []
    dynamic = None
    interp = False
    phdr_seg = False
    for i in range(elf["e_phnum"]):
        base = elf["e_phoff"] + i * 56
        if base + 56 > len(image):
            break
        p_type, p_flags, p_off, p_vaddr, _p_paddr, p_filesz, p_memsz, p_align = struct.unpack_from(
            "<IIQQQQQQ", image, base
        )
        if p_type == PT_LOAD:
            loads.append((p_vaddr, p_vaddr + p_memsz, p_flags, p_off, p_filesz, p_memsz, p_align))
        elif p_type == PT_DYNAMIC:
            dynamic = (p_off, p_filesz)
        elif p_type == PT_INTERP:
            interp = True
        elif p_type == PT_PHDR:
            phdr_seg = True

    entry = elf["e_entry"]
    in_load = any(lo <= entry < hi for lo, hi, *_ in loads)
    rwx = ["".join(ch for bit, ch in ((4, "R"), (2, "W"), (1, "X")) if flags & bit) for _, _, flags, *_ in loads]
    notice(
        f"loads-{name}",
        f"count={len(loads)} entry_in_load={in_load} entry=0x{entry:x} "
        f"ranges=" + " ".join(f"0x{lo:x}-0x{hi:x}" for lo, hi, *_ in loads) + f" perms={rwx}",
    )
    notice(
        f"misc-{name}",
        f"pt_interp={interp} pt_phdr={phdr_seg} first_load_starts_at_vaddr="
        f"{('0x%x' % loads[0][0]) if loads else 'none'}",
    )

    needed: list[str] = []
    soname = None
    if dynamic:
        dyn_off, dyn_size = dynamic
        table: dict[int, int] = {}
        for i in range(0, dyn_size, 16):
            if dyn_off + i + 16 > len(image):
                break
            tag, val = struct.unpack_from("<qQ", image, dyn_off + i)
            if tag == 0:
                break
            table.setdefault(tag, val)
        strtab_vaddr = table.get(DT_STRTAB, 0)
        strtab_off = None
        for lo, hi, _f, p_off, _fs, _ms, _al in loads:
            if lo <= strtab_vaddr < hi:
                strtab_off = p_off + (strtab_vaddr - lo)
                break
        if strtab_off is not None:
            for i in range(0, dyn_size, 16):
                if dyn_off + i + 16 > len(image):
                    break
                tag, val = struct.unpack_from("<qQ", image, dyn_off + i)
                if tag == 0:
                    break
                if tag in (DT_NEEDED, DT_SONAME):
                    start = strtab_off + val
                    end = image.find(b"\x00", start)
                    text = image[start:end].decode("ascii", "replace")
                    if tag == DT_NEEDED:
                        needed.append(text)
                    else:
                        soname = text
    notice(f"deps-{name}", f"soname={soname} needed={needed or 'NONE (static)'}")


def main() -> int:
    paths = [Path(p) for p in sys.argv[1:]]
    if not paths:
        print("usage: analyze_self.py <file> [file...]", file=sys.stderr)
        return 2
    for path in paths:
        if not path.is_file():
            notice(f"missing-{path.name}", "file not found")
            continue
        try:
            analyse(path)
        except Exception as exc:  # pragma: no cover - diagnostic
            notice(f"error-{path.name}", f"{exc.__class__.__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
