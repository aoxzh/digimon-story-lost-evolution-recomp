# Focused ndsrecomp patches

These are the only changes this title project needs in the shared framework.
All other framework code stays at the pinned revision (`ndsrecomp.pin`).

| Patch | Purpose |
|---|---|
| `0001-cartridge-power-of-two-capacity.patch` | Load trimmed ROMs into a zero-padded power-of-two backing store and derive the B7 chip capacity from it. Includes the synthetic `cart_rom_test`. |
| `0002-windows-build-fixes.patch` | Normalize title-bank paths to CMake separators before glob verification, and add `<cstdlib>` to melonDS `Savestate.cpp` for clang 23 on Windows. |
| `0003-single-screen-layout.patch` | Add the `single` screen layout (top screen + side-panel touch screen, plus portrait composition), the shared virtual-controls overlay, composed-window screenshot hook (`NDS_FRONTEND_SHOT_DIR` / `NDS_FRONTEND_SHOT_AT`), and deterministic frontend input hook (`NDS_FRONTEND_INPUT`). |
| `0004-android-runner.patch` | Build `nds_runner` as `libmain.so` on Android with an `SDL_main` wrapper rooted in the app's internal `files/` directory, 16 KB-compatible shared libraries, and the Android `live_overlay.cpp` guard (the NDK lacks the Linux `posix_spawn` helpers). |

`tools/lostevo.py build` applies the capacity, single-screen and Android
patches when missing and makes the Windows fixes idempotently, so a clean
`bootstrap` checkout builds without manual editing. The patches are also kept as
standalone files for upstreaming.

Apply from the framework root:

```bash
git -C ndsrecomp apply ../patches/0001-cartridge-power-of-two-capacity.patch
git -C ndsrecomp apply ../patches/0002-windows-build-fixes.patch
git -C ndsrecomp apply ../patches/0003-single-screen-layout.patch
git -C ndsrecomp apply ../patches/0004-android-runner.patch
```

`git apply --reverse --check` succeeds against the currently built tree. Patch
`0004` is only required for Android builds; desktop builds can skip it (the
`if(ANDROID)` branch stays dormant).
