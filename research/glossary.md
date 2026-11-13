# Glossary

Vocabulary used across this handbook. Keep it short and precise; the coding chat uses the same terms.

**Aeolia** — southbridge of launch PS4 Fat (CUH-10xx/11xx). Selects one kernel family.
**Belize** — southbridge of CUH-12xx Fat and many Slims/Pros. Best-supported family in 2026.
**Baikal** — southbridge of many Slims/Pros. Needs its own kernel branch (and Ethernet quirks).
**Southbridge** — the I/O die revision that determines which kernel binary a console needs.
**Orbis OS** — Sony's PS4 system software. Cold boot always enters Orbis; no Linux boot entry exists.
**GoldHEN** — homebrew enabler payload; provides FTP (2121) and payload loader (9020/9090).
**Payload** — the ELF/BIN sent to GoldHEN that loads Linux (`linux-1024mb.elf`, etc.).
**VRAM carve-out** — memory reserved for the GPU out of the shared 8 GB GDDR5 before Linux boots.
**Liverpool / Gladius** — codenames of the PS4 / PS4 Pro GPU. GFX7-class in Mesa terms.
**GFX6/GFX7** — AMD GPU generations (GCN 1.0/1.1). PS4 is GFX7-class → **Vulkan 1.3 maximum**.
**RadeonSI** — Mesa's OpenGL driver for GCN+ AMD GPUs.
**RADV** — Mesa's Vulkan driver for AMD GPUs.
**Mesa (patched)** — Mesa rebuilt with PS4 PCI IDs; without it the desktop renders in software.
**llvmpipe** — Mesa's CPU software renderer. Seeing it on PS4 = GFX-001.
**DXVK** — Direct3D 9/10/11 → Vulkan translation layer. Version 3.x requires Vulkan 1.4 (unusable on PS4).
**VKD3D-Proton** — Direct3D 12 → Vulkan. Effectively out of reach on this GPU.
**Proton** — Valve's Wine fork used by Steam; pins a specific DXVK version (Proton 11 → DXVK 2.7.1).
**ICC** — PS4's internal controller for fan/thermal/power/LED; exposes `/dev/icc` in some kernels.
**bzImage** — compressed Linux kernel image the loader kexecs.
**initramfs** — early userspace image that finds and mounts the root filesystem.
**switch_root** — handing control from initramfs to the real root filesystem.
**kexec** — loading a new kernel from a running kernel (how Orbis hands over to Linux).
**EDID** — display capability data; PS4 builds often force `edid/1920x1080.bin`.
**UART** — serial debug console at `0xd0340000`; the only debug output when video fails.
**btver2** — GCC/LLVM target for AMD Jaguar. Required for binaries that run natively on the PS4 CPU.
**AVX2/FMA/BMI2** — CPU extensions the Jaguar **lacks**; binaries using them die with SIGILL.
**zram** — compressed RAM swap; the standard memory trick on low-RAM consoles.
**UVD** — AMD's fixed-function video decoder block; experimental on PS4 Linux.
**VA-API** — Linux hardware video decode API (depends on UVD).
**PS4 Fat** — CUH-10xx/11xx (Aeolia) and CUH-12xx (Belize): the project's primary target.
**payload VRAM profile** — 512 MB / 1 GB / 2 GB / 4 GB variants of the loader.
**doctor** — the diagnostic tool (`ps4-doctor`) that maps symptoms to registry IDs.
