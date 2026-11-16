# Third-party notices

This title project is tooling around other people's work. It ships no game
code, ROM, BIOS, firmware, save, fan-translation text or generated bank.

| Component | Use | Licence / distribution |
|---|---|---|
| **ndsrecomp** (`RetroPortingToolKit/ndsrecomp`) | static recompiler and runner | PolyForm Noncommercial 1.0.0 for the repository; runner sources MIT; melonDS-derived files GPL-3.0-or-later |
| **recomp-ui** (`RetroPortingToolKit/recomp-ui`) | in-game runtime UI | see its upstream licence |
| **melonDS** | DS hardware models vendored by ndsrecomp | GPL-3.0-or-later |
| **FreeBIOS** (`mstan/freebios`) | default BIOS (no dumps needed) | BSD-2-Clause |
| **libslirp** | emulated network backend | BSD-3-Clause |
| **SDL3** | Android window/input/audio backend | zlib licence (`android/SDL3-LICENSE.txt`) |
| **toml++** | config parser | MIT |
| **arm-recomp-core** | shared ARM decode/IR core | see upstream |
| **Operation Decoded T-En v1.1** | English fan translation | distributed by its authors; not bundled |
| **Xzonn DSLEChsLocalization v1.0.1** | simplified-Chinese fan translation | distributed by its authors; downloaded separately and verified by hash |
| **NitroPatcher** | `.xzp` patch format/tool | by Xzonn; see upstream |

Do not distribute ROMs, patched images, BIOS/firmware dumps, saves, or the
generated `generated/` banks. They are game-derived data and stay on the
machine that owns the cartridge.

If you distribute a runner binary, remember that it is a GPL-3.0-or-later
combined work through the vendored melonDS code; ship the licence and make the
corresponding source available.
