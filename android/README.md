# Android ARM64 runner (experimental)

This directory packages the same `nds_runner` native core as an Android
SDL3 application. It was built and tested on a **Galaxy Z Fold5** over wireless ADB.

## What works

- Native ARM64 runner (`libmain.so`) + SDL3 (`libSDL3.so`).
- One APK with English, Japanese and simplified-Chinese profiles; all three
  ROM SHA-1s are registered and all three boot on the Fold5.
- First-run `SetupActivity` with SAF file pickers, language selection, ROM
  SHA-1/size checks and automatic start when the profile is complete.
- True foldable posture layout through AndroidX `WindowInfoTracker`:
  tabletop (horizontal hinge) puts the top screen above the hinge and the
  touch screen + controls below it; book (vertical hinge) splits left/right.
  Flat posture returns to the audited 448×192 landscape or 256×480 portrait
  single-screen composition.
- On-screen DS controls with spring scale/glow animation: D-pad, A/B/X/Y,
  L/R, Start/Select.
- Virtual controls hide automatically when SDL reports a connected gamepad
  (`virtual_controls = "auto"`); hiding also releases held virtual keys.
- OpenSL ES audio fallback, because AAudio returned
  `AAUDIO_ERROR_DISCONNECTED` on the Fold5 during activity reconfiguration.
- 16 KB page-size compatible native libraries (Android 16+ requirement).

## Layout behaviour

The app requests `resizeableActivity="true"`, `screenOrientation="fullUser"`
and handles `orientation|screenLayout|screenSize|smallestScreenSize|density`
without recreating the activity. On every window resize/rotation the frontend
recomputes its single-screen canvas; the AndroidX listener adds hinge bounds.

| Window shape | Canvas | Composition |
|---|---|---|
| landscape / flat | 448×288 | top screen left, touch side panel right, controls strip below |
| portrait / flat | 256×480 | top screen above bottom screen, controls strip below |
| tabletop (horizontal hinge) | window aspect, 480 high | top screen above hinge, touch screen + controls below |
| book (vertical hinge) | window aspect, 480 wide | top screen left of hinge, touch screen + controls right |

`LostEvoActivity` accepts a debug-only `--es test_fold horizontal|vertical`
extra (forwarded by `SetupActivity`) to audit the two hinge layouts without
physically folding the device.

## First-run files

`SetupActivity` is the launcher. It uses `ACTION_OPEN_DOCUMENT` to copy the
user's own dumps into the app's internal directory; the APK bundles no game
data. The native wrapper reads:

```text
files/roms/lostevo-<lang>.nds
files/bios/biosnds9.rom        (optional; FreeBIOS is used without it)
files/bios/biosnds7.rom        (optional)
files/config/<lang>.toml
files/config/active-language
files/saves/lostevo-<lang>.sav
files/saves/firmware-<lang>.bin
```

The three bundled `game-*.toml` configs live in `app/src/main/assets/`.
Long-press the app icon →「文件设置」to reopen the setup screen.

## Build

Requirements: Android SDK platform 35, NDK 27.2, CMake/Ninja, JDK 21, SDL3
3.4.18 source; AndroidX Core/Window are fetched by Gradle.

```powershell
# 1. Build SDL3 for arm64-v8a with 16 KB page support
cmake -G Ninja -S SDL3-3.4.18 -B sdl-build-android `
  -DCMAKE_TOOLCHAIN_FILE=$NDK/build/cmake/android.toolchain.cmake `
  -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-24 `
  -DANDROID_SUPPORT_FLEXIBLE_PAGE_SIZES=ON `
  -DSDL_SHARED=ON -DSDL_STATIC=OFF -DSDL_TEST=OFF -DSDL_EXAMPLES=OFF
cmake --build sdl-build-android -j8
cmake --install sdl-build-android --prefix sdl-android-prefix

# 2. Build the runner as libmain.so with all three bank groups
cmake -G Ninja -S ndsrecomp/runner -B ndsrecomp/runner/build-android `
  -DCMAKE_TOOLCHAIN_FILE=$NDK/build/cmake/android.toolchain.cmake `
  -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-24 `
  -DANDROID_SUPPORT_FLEXIBLE_PAGE_SIZES=ON `
  -DNDS_SDL_BACKEND=SDL3 -DNDS_ENABLE_COMPUTE_RENDERER=OFF `
  -DNDS_BOOTSTRAP_FIRMWARE=ON `
  -DNDS_TITLE_BANK_DIRS=".../generated/recomp;.../generated/recomp-ja;.../generated/recomp-zh" `
  -DNDS_TITLE_ROM_SHA1S="83b410...;f18014...;e4798b..." `
  -DNDS_RECOMP_UI_ROOT=.../recomp-ui `
  -DSDL3_DIR=.../sdl-android-prefix/lib/cmake/SDL3
cmake --build ndsrecomp/runner/build-android --target nds_runner -j8

# 3. Package
cp ndsrecomp/runner/build-android/libmain.so app/src/main/jniLibs/arm64-v8a/
cp sdl-android-prefix/lib/libSDL3.so app/src/main/jniLibs/arm64-v8a/
$env:JAVA_HOME = .../jdk21
.\gradlew.bat assembleDebug
```

## Deploy and run

The app contains no game data. `tools/android_deploy.py` installs the APK,
copies the ROM, config and (optional) BIOS dumps into the internal `files/` tree through
`/data/local/tmp` + `run-as`, writes `active-language`, and can launch and pull
the log/screenshot:

```powershell
python tools/android_deploy.py `
  --serial <device> --language en --rom <your.nds> `
  --bios-dir run\bios --apk android\app\build\outputs\apk\debug\app-debug.apk `
  --launch --log run\android-run.log --screenshot run\android.png
```

`--dry-run` prints the adb commands without touching the device. The app log
is written to `files/android-run.log` because Android does not reliably
surface native stderr in logcat.

## Verified on the Fold5

- English, Japanese and Chinese profiles boot from the same APK.
- First-run setup screen and automatic start after files are complete.
- Tabletop and book hinge layouts (simulated posture, actual native path).
- Landscape/portrait single-screen layouts.
- Virtual controls visible without a pad and hidden with both an SDL virtual
  pad and a kernel-level `/dev/uinput` Xbox-style pad; controls returned after
  the kernel pad was removed.
- OpenGL ES 2 renderer, OpenSL ES audio at 32,728→44,100 Hz, 16 KB-aligned
  native libraries.

## Limitations

- A retail physical gamepad was not available; the kernel-uinput hot-plug/
  unplug path and SDL virtual pad path are verified. Physical fold posture was
  also simulated rather than folded by hand.
- 3D scenes fall back to the threaded software renderer (compute renderer is
  disabled on Android).
- Wi-Fi is disabled in the Android launch profile.
