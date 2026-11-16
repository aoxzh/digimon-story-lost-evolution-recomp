#!/usr/bin/env python3
"""One-click setup and launch for Windows (called by play.bat).

On a fresh install this:

1. finds your ROMs (in roms\\, dragged onto play.bat, or picked in a dialog),
   identifies each one by SHA-1 and files it under the name the build expects;
2. downloads a private toolchain into kit\\ (llvm-mingw, CMake, Ninja, SDL3,
   xdelta3, ndspy), each SHA-256 verified, nothing installed system-wide;
3. makes the simplified-Chinese image from the Japanese dump when it can;
4. builds the game with tools/lostevo.py (log: run\\build.log);
5. starts it.

Later launches skip straight to step 5 unless the ROMs or the tooling changed.

    setup_kit.py [ROM ...]        normal launch (play.bat passes dropped files)
    setup_kit.py --rebuild        force a full rebuild
    setup_kit.py --no-play        set up and build, but do not start the game
    setup_kit.py --offline        never download; fail if the kit is missing

Nothing is written outside this folder and no administrator rights are needed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Language names (日本語, 简体中文) must not crash a legacy-codepage console.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

KIT = ROOT / "kit"
DOWNLOADS = KIT / "downloads"
ROM_DIR = Path(os.environ.get("LOSTEVO_ROM_DIR", ROOT / "roms"))
RUN = ROOT / "run"
BUILD_LOG = RUN / "build.log"
BUILD_ID = RUN / "kit-build-id.json"
LOSTEVO = ROOT / "tools" / "lostevo.py"
MANIFEST = ROOT / "languages" / "manifest.json"
NINJA_STEP = re.compile(r"^\[(\d+)/(\d+)\]")


@dataclass(frozen=True)
class Component:
    name: str
    url: str
    sha256: str
    kind: str          # "zip", "tar.gz" or "wheel"
    target: str        # directory under kit/
    probe: str         # file inside target that proves it is unpacked
    strip_top: bool = True
    size: int = 0


# Same pins as the sibling Sunburst port, plus xdelta3 for the Chinese patch.
COMPONENTS: tuple[Component, ...] = (
    Component(
        "llvm-mingw 20261020",
        "https://github.com/mstorsjo/llvm-mingw/releases/download/20261020/"
        "llvm-mingw-20261020-ucrt-x86_64.zip",
        "fd5462b7f5d93b2ff981fcd3f9c7e427e47f3203c64ea91c27bcc444eebd74cd",
        "zip", "llvm-mingw", "bin/clang.exe", size=190612575,
    ),
    Component(
        "CMake 4.4.4",
        "https://github.com/Kitware/CMake/releases/download/v4.4.4/"
        "cmake-4.4.4-windows-x86_64.zip",
        "bace36e94b31c68ab6fa295f26dfa11219e0701cf7c94b0284a7d1cb13dac536",
        "zip", "cmake", "bin/cmake.exe", size=54400562,
    ),
    Component(
        "Ninja 1.13.2",
        "https://github.com/ninja-build/ninja/releases/download/v1.13.2/ninja-win.zip",
        "07fc8261b42b20e71d1720b39068c2e14ffcee6396b76fb7a795fb460b78dc65",
        "zip", "ninja", "ninja.exe", strip_top=False, size=291570,
    ),
    Component(
        "SDL 3.4.18",
        "https://github.com/libsdl-org/SDL/releases/download/release-3.4.18/"
        "SDL3-devel-3.4.18-mingw.tar.gz",
        "049b9dd711e3fb3f8d84feb998dfec54a75e17cf539c4a80ff4d058d839771cf",
        "tar.gz", "sdl3", "x86_64-w64-mingw32/lib/cmake/SDL3/SDL3Config.cmake",
        size=5294572,
    ),
    Component(
        "xdelta3 3.0.11",
        "https://github.com/jmacd/xdelta-gpl/releases/download/v3.0.11/"
        "xdelta3-3.0.11-x86_64.exe.zip",
        "eca90daab9cd8388ffa17fb4d6808bb0616cc5d37a7682126485dba1c79f86bf",
        "zip", "xdelta3", "xdelta3-3.0.11-x86_64.exe", strip_top=False, size=217850,
    ),
    Component(
        "ndspy 4.2.0",
        "https://files.pythonhosted.org/packages/07/01/"
        "c60b57a0aa66074552acbbc16786b34c93caa72f3fdda64fada11866482a/"
        "ndspy-4.2.0-py3-none-any.whl",
        "d3b03e57ef5ba450e766035e1908293f7a6ba1a738736fae42b2c66952abb85b",
        "wheel", "python-libs", "ndspy/rom.py", strip_top=False, size=139822,
    ),
)


def say(message: str = "") -> None:
    print(message, flush=True)


def fail(message: str) -> "NoReturn":  # type: ignore[name-defined]
    raise SystemExit(f"\nsetup: {message}")


def sha(path: Path, algorithm: str = "sha1") -> str:
    h = hashlib.new(algorithm)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# ROMs


def rom_target(lang: dict) -> Path:
    return ROM_DIR / Path(lang["rom"]).name


def import_roms(extra: list[Path]) -> None:
    """File every recognisable dump under its canonical name in roms/."""
    manifest = load_manifest()
    by_sha = {lang["sha1"]: lang for lang in manifest["languages"]}
    ROM_DIR.mkdir(parents=True, exist_ok=True)
    candidates = [p for p in extra if p.is_file()]
    candidates += [p for p in ROM_DIR.glob("*.nds") if p.is_file()]
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.stat().st_size < 16 << 20:
            continue
        digest = sha(resolved)
        lang = by_sha.get(digest)
        if lang is None:
            if resolved.parent == ROM_DIR.resolve():
                say(f"  ignoring {resolved.name}: not one of the supported dumps "
                    f"(SHA-1 {digest})")
            else:
                say(f"  {resolved.name} is not a supported dump (SHA-1 {digest})")
            continue
        target = rom_target(lang)
        if target.resolve() == resolved:
            continue
        if target.is_file() and sha(target) == digest:
            continue
        if resolved.parent == ROM_DIR.resolve():
            resolved.replace(target)
            say(f"  {lang['native_name']}: renamed {resolved.name}")
        else:
            shutil.copyfile(resolved, target)
            say(f"  {lang['native_name']}: copied {resolved.name} into roms\\")


def present_languages() -> list[dict]:
    out = []
    for lang in load_manifest()["languages"]:
        target = rom_target(lang)
        if target.is_file() and target.stat().st_size == lang["rom_size"]:
            out.append(lang)
    return out


def pick_roms_dialog() -> list[Path]:
    try:
        import tkinter
        from tkinter import filedialog
    except Exception:  # noqa: BLE001 - no Tk in this Python
        return []
    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    names = filedialog.askopenfilenames(
        title="Select your Digimon Story: Lost Evolution ROM(s)",
        filetypes=[("Nintendo DS ROM", "*.nds"), ("All files", "*.*")],
    )
    root.destroy()
    return [Path(name) for name in names]


def explain_roms() -> None:
    say("\nNo supported ROM found. Put one or more of your own dumps in")
    say(f"  {ROM_DIR}")
    say("(any file name), or drag them onto play.bat. Supported dumps:")
    for lang in load_manifest()["languages"]:
        if lang.get("patch"):
            say(f"  {lang['native_name']:10} made automatically from the Japanese dump")
        else:
            say(f"  {lang['native_name']:10} {lang['rom_size']:>11,} bytes  SHA-1 {lang['sha1']}")


# ---------------------------------------------------------------------------
# toolchain kit


def _progress(done: int, total: int) -> None:
    if total:
        pct = done * 100 // total
        print(f"\r    {done / 1048576:7.1f} / {total / 1048576:.1f} MiB  {pct:3d}%",
              end="", flush=True)


def download(component: Component, offline: bool) -> Path:
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    archive = DOWNLOADS / component.url.rsplit("/", 1)[1]
    if archive.is_file() and sha(archive, "sha256") == component.sha256:
        return archive
    if offline:
        fail(f"{component.name} is missing and --offline was given")
    say(f"  downloading {component.name} ...")
    partial = archive.with_suffix(archive.suffix + ".part")
    request = urllib.request.Request(component.url,
                                     headers={"User-Agent": "lostevo-recomp-kit"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=120) as response, \
                    partial.open("wb") as out:
                total = int(response.headers.get("Content-Length") or component.size)
                done = 0
                while True:
                    chunk = response.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    _progress(done, total)
            print(flush=True)
            break
        except OSError as exc:
            print(flush=True)
            if attempt == 2:
                fail(f"could not download {component.url}: {exc}")
            say(f"    retrying ({exc})")
            time.sleep(3)
    actual = sha(partial, "sha256")
    if actual != component.sha256:
        partial.unlink(missing_ok=True)
        fail(f"{component.name}: SHA-256 mismatch (expected {component.sha256}, "
             f"got {actual}); the download was discarded")
    partial.replace(archive)
    return archive


def unpack(component: Component, archive: Path) -> None:
    target = KIT / component.target
    staging = KIT / (component.target + ".tmp")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    if component.kind in ("zip", "wheel"):
        with zipfile.ZipFile(archive) as z:
            z.extractall(staging)
    else:
        with tarfile.open(archive, "r:gz") as t:
            t.extractall(staging, filter="data")
    source = staging
    if component.strip_top:
        entries = list(staging.iterdir())
        if len(entries) == 1 and entries[0].is_dir():
            source = entries[0]
    shutil.rmtree(target, ignore_errors=True)
    shutil.move(str(source), str(target))
    shutil.rmtree(staging, ignore_errors=True)
    if not (target / component.probe).is_file():
        fail(f"{component.name}: unexpected archive layout ({component.probe} missing)")


def ensure_kit(offline: bool) -> None:
    missing = [c for c in COMPONENTS if not (KIT / c.target / c.probe).is_file()]
    if not missing:
        return
    total = sum(c.size for c in missing)
    say(f"\nFetching the private build kit into kit\\ ({total / 1048576:.0f} MiB, "
        "one time only)")
    for component in missing:
        unpack(component, download(component, offline))
    say("  kit ready")


def kit_env() -> dict[str, str]:
    env = dict(os.environ)
    llvm = KIT / "llvm-mingw" / "bin"
    sdl = KIT / "sdl3" / "x86_64-w64-mingw32"
    cmake = KIT / "cmake" / "bin" / "cmake.exe"
    env.update({
        "CMAKE": str(cmake),
        "NINJA": str(KIT / "ninja" / "ninja.exe"),
        "CC": str(llvm / "clang.exe"),
        "CXX": str(llvm / "clang++.exe"),
        "CMAKE_PREFIX_PATH": str(sdl),
        "XDELTA3": str(KIT / "xdelta3" / "xdelta3-3.0.11-x86_64.exe"),
        "LOSTEVO_ROM_DIR": str(ROM_DIR),
        "PYTHONUTF8": "1",
    })
    env["PYTHONPATH"] = os.pathsep.join(
        [str(KIT / "python-libs")] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
    )
    env["PATH"] = os.pathsep.join([
        str(llvm), str(sdl / "bin"), str(KIT / "ninja"), str(cmake.parent),
        env.get("PATH", ""),
    ])
    return env


# ---------------------------------------------------------------------------
# build


def runner_path() -> Path:
    sys.path.insert(0, str(ROOT / "tools"))
    import lostevo  # noqa: E402  (after the path fix)
    return lostevo.RUNNER


def build_identity(languages: list[dict]) -> dict:
    h = hashlib.sha256()
    for rel in ("VERSION", "tools/lostevo.py", "tools/prepare_lostevo.py",
                "ndsrecomp.pin", "recomp-ui.pin", "game.toml", "game-ja.toml",
                "game-zh.toml"):
        path = ROOT / rel
        if path.is_file():
            h.update(path.read_bytes())
    for patch in sorted((ROOT / "patches").glob("*.patch")):
        h.update(patch.read_bytes())
    return {"tooling": h.hexdigest(),
            "languages": sorted(lang["sha1"] for lang in languages)}


def run_logged(args: list[str], env: dict[str, str], title: str) -> None:
    say(f"\n{title}")
    RUN.mkdir(parents=True, exist_ok=True)
    with BUILD_LOG.open("a", encoding="utf-8", errors="replace") as log:
        log.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} {' '.join(args)}\n")
        proc = subprocess.Popen(
            [sys.executable, str(LOSTEVO), *args], cwd=str(ROOT), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        assert proc.stdout is not None
        tail: list[str] = []
        for line in proc.stdout:
            log.write(line)
            tail = (tail + [line.rstrip()])[-40:]
            text = line.strip()
            step = NINJA_STEP.match(text)
            key_line = text.startswith((
                "===", "BIOS:", "runner ready", "framework:",
                "language patch ready", "download:", "skipping"))
            if key_line or (step and int(step.group(1)) % 25 == 0):
                say(f"  {text[:110]}")
        rc = proc.wait()
    if rc != 0:
        say("\n".join(f"    {line}" for line in tail[-15:]))
        fail(f"{title.strip()} failed. Full log: {BUILD_LOG}")


def copy_runtime_dlls(runner: Path) -> None:
    for dll in (KIT / "sdl3" / "x86_64-w64-mingw32" / "bin" / "SDL3.dll",
                KIT / "llvm-mingw" / "x86_64-w64-mingw32" / "bin" / "libc++.dll",
                KIT / "llvm-mingw" / "x86_64-w64-mingw32" / "bin" / "libunwind.dll"):
        if dll.is_file():
            shutil.copy2(dll, runner.parent / dll.name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("roms", nargs="*", type=Path, help="ROM files to import")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--no-play", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--language", help="start this language without the menu")
    args = parser.parse_args(argv)

    if os.name != "nt":
        fail("the one-click kit is for Windows; on Linux/macOS follow the README "
             "(python3 tools/lostevo.py build && python3 tools/lostevo.py play)")
    if sys.version_info < (3, 10):
        fail("Python 3.10 or newer is required")

    say("Digimon Story: Lost Evolution Recomp")
    import_roms(args.roms)
    languages = present_languages()
    if not languages:
        picked = pick_roms_dialog()
        if picked:
            import_roms(picked)
            languages = present_languages()
    if not languages:
        explain_roms()
        return 1

    ensure_kit(args.offline)
    env = kit_env()

    manifest = load_manifest()
    by_id = {lang["id"]: lang for lang in manifest["languages"]}
    have = {lang["id"] for lang in languages}
    zh = by_id.get("zh-Hans")
    if zh and "zh-Hans" not in have and "ja" in have and not args.offline:
        run_logged(["patch", "zh-Hans"], env,
                   "Making the simplified-Chinese image from your Japanese dump")
        languages = present_languages()
    say("\nEditions found: " + ", ".join(lang["native_name"] for lang in languages))

    runner = runner_path()
    identity = build_identity(languages)
    previous = None
    if BUILD_ID.is_file():
        try:
            previous = json.loads(BUILD_ID.read_text(encoding="utf-8"))
        except ValueError:
            previous = None
    if args.rebuild or previous != identity or not runner.is_file():
        BUILD_LOG.unlink(missing_ok=True)
        build_args = ["build"]
        if args.rebuild:
            build_args.append("--force")
        run_logged(build_args, env,
                   "Building the game from your ROM(s). The first build takes "
                   "about 5-15 minutes.")
        if not runner.is_file():
            fail(f"the build finished but {runner} is missing. Log: {BUILD_LOG}")
        BUILD_ID.write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")
    copy_runtime_dlls(runner)

    if args.no_play:
        say("\nReady. Run play.bat to start the game.")
        return 0
    play = [sys.executable, str(LOSTEVO), "play"]
    if args.language:
        play += ["--language", args.language]
    say("")
    return subprocess.run(play, cwd=str(ROOT), env=env).returncode


if __name__ == "__main__":
    raise SystemExit(main())
