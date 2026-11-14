# PS4 Mesa Patch Mirror & Attribution Notice

Per `research/11-risks-legal.md` §5 and `research/14-pinned-inputs.lock.yaml`, these three
patch files are mirrored verbatim from upstream to prevent link-rot build failures:

| File | Upstream Source | Git Blob SHA-1 | SHA-256 | Purpose |
|---|---|---|---|---|
| `0001-ps4-liverpool-gladius.patch` | `blue0x1/ps4-multiboot` (lineage: `striker91n/ps4-flatpak-mesa` -> `DionKill/ps4-video-archlinux` -> `fail0verflow/ps4-radeon-patches`) | `0cea1186d9d2b1d9cc1977f40075a729414a2c67` | `10b9778bd8f44a30e1787568f95a8a804c01d5a296cca8dff93ded1afbdfd318` | Adds Liverpool (`0x9920`/`0x9922`/`0x9923`) & Gladius (`0x9924`) PCI IDs, GFX7 mapping, raster config `0x2a00161a`, RADV fast-clear predication fix |
| `0002-radv-ps4-no-hiz.patch` | `blue0x1/ps4-multiboot` | `6069650e6a14260917f451af533948700d630ba1` | `cef4aa15d0329050368dafd724969f4c01ff2329bd297cbb5db7c55ad6a77b97` | Disables RADV HiZ (`use_hiz = false`) on `CHIP_LIVERPOOL` / `CHIP_GLADIUS` (fixes GFX-002 `ring gfx timeout` on DXVK) |
| `0003-aco-ps4-no-flat-global.patch` | `blue0x1/ps4-multiboot` | `8766cc72c9a00668e484787701241a70771a4d4e` | `b3fcbac66a89aef9040017cac3b000b6e4074914ac6f0fb23ad5e0b02f489e03` | Forces MUBUF `addr64` instead of `FLAT` global memory instructions in ACO on Liverpool/Gladius (prevents `flat_store_dwordx4` GPU hang in `vkCmdFillBuffer`) |

## Licence

- Upstream Mesa is MIT-licensed.
- `blue0x1/ps4-multiboot` packaging is GPL-2.0; patch headers and upstream authorship
  credits are preserved intact.
