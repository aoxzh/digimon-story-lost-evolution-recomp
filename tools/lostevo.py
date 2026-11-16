#!/usr/bin/env python3
"""Digimon Story: Lost Evolution recomp — build, language packs and launcher.

One entry point for the title project:

  python tools/lostevo.py status
  python tools/lostevo.py patch zh-Hans          # apply the Chinese fan patch
  python tools/lostevo.py build                  # framework + banks + runner
  python tools/lostevo.py verify                 # short boot check per language
  python tools/lostevo.py play                   # language menu + runner
  python tools/lostevo.py play --language zh-Hans

The tool is cross-platform (Windows, macOS, Linux). It fetches the pinned
ndsrecomp/recomp-ui sources into ndsrecomp/ and recomp-ui/ inside this
checkout (or uses NDSRECOMP_ROOT / RECOMP_UI_ROOT). Your ROMs go in roms/
(or LOSTEVO_ROM_DIR). No ROM, BIOS, save or generated code is ever tracked:
such files stay in roms/, run/, saves/ and generated/ (all ignored).

BIOS dumps are optional. Without them the runner boots on the bundled
open-source FreeBIOS; put biosnds9.rom/biosnds7.rom in run/bios/ to use your
own dumps instead.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Windows terminals often default to a legacy code page; keep the language
# names readable without changing the console's font or the rest of the app.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        pass



def _checkout(env_name: str, name: str, marker: str) -> Path:
    """Framework checkout: env override, then ./<name>, then ../<name>."""
    if os.environ.get(env_name):
        return Path(os.environ[env_name]).resolve()
    local = ROOT / name
    sibling = ROOT.parent / name
    if not (local / marker).is_file() and (sibling / marker).is_file():
        return sibling.resolve()
    return local.resolve()


FRAMEWORK = _checkout("NDSRECOMP_ROOT", "ndsrecomp", "runner/CMakeLists.txt")
UI_ROOT = _checkout("RECOMP_UI_ROOT", "recomp-ui", "src/common/recomp_runtime_ui.c")
BUILD_DIR = Path(
    os.environ.get("LOSTEVO_RUNNER_BUILD", FRAMEWORK / "runner" / "build-lostevo")
).resolve()
RUNNER = BUILD_DIR / ("nds_runner.exe" if os.name == "nt" else "nds_runner")
RECOMPILER = FRAMEWORK / "recompiler" / "build" / (
    "nds_recompile.exe" if os.name == "nt" else "nds_recompile"
)
MANIFEST = ROOT / "languages" / "manifest.json"
STATE_DIR = ROOT / ".state"
STATE_FILE = STATE_DIR / "selected-language.json"
RUN_DIR = ROOT / "run"
DOWNLOAD_DIR = ROOT / "downloads"
BIOS_DIR = ROOT / "run" / "bios"

EXPECTED_BIOS = {
    "biosnds9.rom": "bfaac75f101c135e32e2aaf541de6b1be4c8c62d",
    "biosnds7.rom": "24f67bdea115a2c847c8813a262502ee1607b7df",
}


# ---------------------------------------------------------------------------
# small utilities


def sha1_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest() -> dict:
    with MANIFEST.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_manifest(manifest: dict) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def language_map(manifest: dict) -> dict[str, dict]:
    return {lang["id"]: lang for lang in manifest["languages"]}


def resolve_language(manifest: dict, wanted: str | None) -> dict:
    languages = language_map(manifest)
    if not wanted:
        wanted = manifest.get("default", "en")
    if wanted in languages:
        return languages[wanted]
    matches = [lang for key, lang in languages.items() if key.lower().startswith(wanted.lower())]
    if len(matches) == 1:
        return matches[0]
    raise SystemExit(
        f"unknown language '{wanted}'; choose one of: {', '.join(languages)}"
    )


def rom_path(lang: dict) -> Path:
    rom_dir = os.environ.get("LOSTEVO_ROM_DIR")
    if rom_dir:
        return (Path(rom_dir) / Path(lang["rom"]).name).resolve()
    return (ROOT / lang["rom"]).resolve()


def base_rom_path(patch: dict) -> Path:
    rom_dir = os.environ.get("LOSTEVO_ROM_DIR")
    if rom_dir:
        return (Path(rom_dir) / Path(patch["base_rom"]).name).resolve()
    return (ROOT / patch["base_rom"]).resolve()


def inputs_path(lang: dict) -> Path:
    return (ROOT / lang.get("inputs", f"generated/inputs-{lang['id']}")).resolve()


def bank_path(lang: dict) -> Path:
    return (ROOT / lang["bank_dir"]).resolve()


def config_path(lang: dict) -> Path:
    return (ROOT / lang["config"]).resolve()


def run_dir(*parts: str) -> Path:
    path = RUN_DIR.joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_file(*parts: str) -> Path:
    path = RUN_DIR.joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# toolchain discovery


def _first_existing(candidates: list[str | Path]) -> Path | None:
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_file():
            return path
    return None


def find_cmake() -> Path:
    env = os.environ.get("CMAKE")
    if env:
        return Path(env)
    found = shutil.which("cmake")
    candidates = [
        found,
        r"C:\msys64\clang64\bin\cmake.exe",
        r"C:\msys64\ucrt64\bin\cmake.exe",
        "/opt/homebrew/bin/cmake",
        "/usr/local/bin/cmake",
        "/usr/bin/cmake",
    ]
    path = _first_existing(candidates)
    if not path:
        raise SystemExit(
            "cmake not found; install CMake 3.20+ or set the CMAKE environment variable"
        )
    return path


def find_ninja(cmake: Path) -> Path:
    env = os.environ.get("NINJA")
    if env:
        return Path(env)
    found = shutil.which("ninja")
    bin_dir = cmake.parent
    candidates = [
        found,
        bin_dir / ("ninja.exe" if os.name == "nt" else "ninja"),
        r"C:\msys64\clang64\bin\ninja.exe",
        "/opt/homebrew/bin/ninja",
        "/usr/local/bin/ninja",
        "/usr/bin/ninja",
    ]
    path = _first_existing(candidates)
    if not path:
        raise SystemExit(
            "ninja not found; install Ninja or set the NINJA environment variable"
        )
    return path


def build_env(cmake: Path) -> dict[str, str]:
    env = dict(os.environ)
    parts = [str(cmake.parent)]
    # A pinned toolchain (CMAKE set, e.g. by tools/setup_kit.py) must not be
    # mixed with a system MSYS2 install.
    if os.name == "nt" and not os.environ.get("CMAKE") and Path(
        r"C:\msys64\clang64\bin"
    ).is_dir():
        parts.append(r"C:\msys64\clang64\bin")
    env["PATH"] = os.pathsep.join(parts + [env.get("PATH", "")])
    env.setdefault("RECOMP_UI_ROOT", str(UI_ROOT))
    return env


def compiler_args(cmake: Path) -> list[str]:
    # An explicit CC/CXX (set by tools/setup_kit.py for the private
    # llvm-mingw kit) wins over the clang that sits next to cmake.
    if os.environ.get("CC") and os.environ.get("CXX"):
        args = [
            f"-DCMAKE_C_COMPILER={Path(os.environ['CC']).as_posix()}",
            f"-DCMAKE_CXX_COMPILER={Path(os.environ['CXX']).as_posix()}",
        ]
        if os.environ.get("NINJA"):
            args.append(f"-DCMAKE_MAKE_PROGRAM={Path(os.environ['NINJA']).as_posix()}")
        return args
    bin_dir = cmake.parent
    names = (
        ("clang.exe", "clang++.exe")
        if os.name == "nt"
        else ("clang", "clang++")
    )
    cc = _first_existing([bin_dir / names[0]])
    cxx = _first_existing([bin_dir / names[1]])
    if cc and cxx:
        return [
            f"-DCMAKE_C_COMPILER={cc.as_posix()}",
            f"-DCMAKE_CXX_COMPILER={cxx.as_posix()}",
        ]
    return []


def find_xdelta() -> Path:
    env = os.environ.get("XDELTA3")
    if env:
        return Path(env)
    found = shutil.which("xdelta3")
    candidates = [
        found,
        r"C:\msys64\usr\bin\xdelta3.exe",
        "/opt/homebrew/bin/xdelta3",
        "/usr/local/bin/xdelta3",
        "/usr/bin/xdelta3",
    ]
    path = _first_existing(candidates)
    if not path:
        raise SystemExit(
            "xdelta3 not found; install it (pacman -S xdelta3 / brew install xdelta) "
            "or set the XDELTA3 environment variable"
        )
    return path


def find_git() -> Path | None:
    env = os.environ.get("GIT")
    if env:
        return Path(env)
    found = shutil.which("git")
    candidates = [
        found,
        r"C:\msys64\usr\bin\git.exe",
        "/opt/homebrew/bin/git",
        "/usr/local/bin/git",
        "/usr/bin/git",
    ]
    return _first_existing(candidates)


def run(cmd: list[str | Path], *, cwd: Path | None = None, env: dict | None = None,
        capture: bool = False) -> subprocess.CompletedProcess:
    printable = " ".join(str(part) for part in cmd)
    print(f"> {printable}")
    if capture:
        result = subprocess.run(
            [str(part) for part in cmd], cwd=str(cwd) if cwd else None,
            env=env, text=True, capture_output=True,
        )
        if result.stdout:
            print(result.stdout.rstrip())
        if result.returncode != 0:
            if result.stderr:
                print(result.stderr.rstrip(), file=sys.stderr)
            raise SystemExit(f"command failed with exit code {result.returncode}")
        return result
    result = subprocess.run(
        [str(part) for part in cmd], cwd=str(cwd) if cwd else None, env=env
    )
    if result.returncode != 0:
        raise SystemExit(f"command failed with exit code {result.returncode}")
    return result


def run_logged(cmd: list[str | Path], log_path: Path, *, cwd: Path | None = None,
               env: dict | None = None) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", newline="\n") as log:
        log.write(" ".join(str(part) for part in cmd) + "\n\n")
        log.flush()
        process = subprocess.Popen(
            [str(part) for part in cmd], cwd=str(cwd) if cwd else None,
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        assert process.stdout is not None
        tail: list[str] = []
        for line in process.stdout:
            log.write(line)
            tail.append(line.rstrip())
            if len(tail) > 40:
                tail.pop(0)
        code = process.wait()
    print("\n".join(tail))
    if code != 0:
        raise SystemExit(f"command failed with exit code {code}; see {log_path}")


# ---------------------------------------------------------------------------
# framework bootstrap / compatibility fixes


def _normalize_cmake_paths() -> bool:
    cmake_file = FRAMEWORK / "runner" / "CMakeLists.txt"
    if not cmake_file.is_file():
        return False
    text = cmake_file.read_text(encoding="utf-8")
    needle = 'list(GET TITLE_GROUP_DIRS ${_gi} _group_dir)\n'
    if 'file(TO_CMAKE_PATH "${_group_dir}" _group_dir)' in text:
        return False
    if needle not in text:
        return False
    text = text.replace(
        needle,
        needle + '        file(TO_CMAKE_PATH "${_group_dir}" _group_dir)\n',
        1,
    )
    cmake_file.write_text(text, encoding="utf-8", newline="\n")
    print("framework: normalized title bank paths to CMake-style separators")
    return True


def _ensure_savestate_cstdlib() -> bool:
    source = FRAMEWORK / "runner" / "vendor" / "melonds" / "Savestate.cpp"
    if not source.is_file():
        return False
    text = source.read_text(encoding="utf-8")
    if "#include <cstdlib>" in text or "#include <stdlib.h>" in text:
        return False
    needle = "#include <cassert>\n"
    if needle not in text:
        return False
    text = text.replace(needle, needle + "#include <cstdlib>\n", 1)
    source.write_text(text, encoding="utf-8", newline="\n")
    print("framework: added <cstdlib> to melonDS Savestate.cpp (clang 23 build fix)")
    return True


def ensure_framework_patches() -> None:
    if not FRAMEWORK.is_dir():
        raise SystemExit(
            f"ndsrecomp not found at {FRAMEWORK}; run `python tools/lostevo.py bootstrap`"
        )
    _normalize_cmake_paths()
    _ensure_savestate_cstdlib()

    for name, label in (
        ("0001-cartridge-power-of-two-capacity.patch", "cartridge power-of-two capacity"),
        ("0003-single-screen-layout.patch", "single-screen layout + audit hooks"),
        ("0004-android-runner.patch", "Android ARM64 runner packaging"),
    ):
        _apply_patch_once(ROOT / "patches" / name, label)


PATCH_MARKER = ".lostevo-patches.json"


def _patch_marker() -> dict:
    marker = FRAMEWORK / PATCH_MARKER
    if marker.is_file():
        try:
            return json.loads(marker.read_text(encoding="utf-8"))
        except ValueError:
            return {}
    return {}


def _record_patch(patch: Path) -> None:
    data = _patch_marker()
    data[patch.name] = sha256_file(patch)
    (FRAMEWORK / PATCH_MARKER).write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _apply_patch_once(patch: Path, label: str) -> None:
    """Apply a framework patch unless it is already applied (idempotent).

    The release zip ships the framework already patched, with a marker that
    records each patch's hash, so players do not need git.
    """
    if _patch_marker().get(patch.name) == sha256_file(patch):
        return
    git = find_git()
    if not git:
        raise SystemExit(
            f"git is needed to apply {patch.name}; install git or apply it "
            f"manually to {FRAMEWORK}"
        )
    # The framework usually sits inside this repository's own git checkout.
    # Inside a repository, `git apply` resolves paths from the repository
    # root and silently skips files outside the current directory, so a patch
    # would "succeed" without changing anything. Stop git from discovering
    # the outer repository so the framework is patched as a plain tree.
    env = dict(os.environ)
    env["GIT_CEILING_DIRECTORIES"] = str(FRAMEWORK.parent)
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)

    def git_apply(*args: str, capture: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(git), "-c", "core.autocrlf=false", "apply", *args, str(patch)],
            cwd=str(FRAMEWORK), env=env,
            capture_output=capture, text=True,
        )

    if git_apply("--reverse", "--check").returncode == 0:
        _record_patch(patch)
        return
    check = git_apply("--check")
    if check.returncode != 0:
        raise SystemExit(
            f"{patch.name} neither applies nor is already applied to {FRAMEWORK}:\n"
            f"{check.stderr.strip()}\n"
            "re-fetch the pinned framework with `python tools/lostevo.py bootstrap --force`"
        )
    result = git_apply()
    if result.returncode != 0:
        raise SystemExit(f"applying {patch.name} failed:\n{result.stderr.strip()}")
    if git_apply("--reverse", "--check").returncode != 0:
        raise SystemExit(f"{patch.name} reported success but is not applied to {FRAMEWORK}")
    _record_patch(patch)
    print(f"framework: applied {label}")


def _download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    print(f"download: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "lostevo-recomp/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as out:
        shutil.copyfileobj(response, out)


def _extract_tarball(url: str, destination: Path) -> None:
    import tarfile

    archive = destination.parent / (destination.name + ".tar.gz")
    _download(url, archive)
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        prefix = members[0].name.split("/")[0] if members else ""
        for member in members:
            if not member.name.startswith(prefix + "/"):
                continue
            member.name = member.name[len(prefix) + 1:]
            if not member.name:
                continue
            tar.extract(member, destination)
    archive.unlink(missing_ok=True)
    print(f"extracted: {destination}")


def bootstrap_command(args: argparse.Namespace) -> None:
    """Fetch the pinned ndsrecomp/recomp-ui sources when they are not present."""
    pins = {}
    for name in ("ndsrecomp", "recomp-ui"):
        pin_file = ROOT / f"{name}.pin"
        if pin_file.is_file():
            pins[name] = pin_file.read_text(encoding="utf-8").strip()
    nds_pin = pins.get("ndsrecomp", "74efebb5a462e11f2e7eb42f54037d81fa056243")
    ui_pin = pins.get("recomp-ui", "41c88ffea852b970af8d50312620b17404e455ad")

    if not (FRAMEWORK / "runner" / "CMakeLists.txt").is_file() or args.force:
        if args.force and FRAMEWORK.exists():
            shutil.rmtree(FRAMEWORK)
        _extract_tarball(
            f"https://codeload.github.com/RetroPortingToolKit/ndsrecomp/tar.gz/{nds_pin}",
            FRAMEWORK,
        )
    else:
        print(f"ndsrecomp already present: {FRAMEWORK}")

    # Submodules are not included in GitHub source archives.
    arm_core = FRAMEWORK / "external" / "arm-recomp-core"
    if not (arm_core / "cmake" / "ArmRecompCore.cmake").is_file() or args.force:
        _extract_tarball(
            "https://codeload.github.com/mstan/arm-recomp-core/tar.gz/"
            "705e71b8aff3ad64fe78f77c3c94bd93158554dd",
            arm_core,
        )
    freebios = FRAMEWORK / "third_party" / "freebios"
    if not (freebios / "drastic_bios_arm9.bin").is_file() or args.force:
        _extract_tarball(
            "https://codeload.github.com/mstan/freebios/tar.gz/"
            "6d6cfb4953924e4abdaa130aedf71826a055508e",
            freebios,
        )

    if not (UI_ROOT / "src" / "common" / "recomp_runtime_ui.c").is_file() or args.force:
        if args.force and UI_ROOT.exists():
            shutil.rmtree(UI_ROOT)
        _extract_tarball(
            f"https://codeload.github.com/RetroPortingToolKit/recomp-ui/tar.gz/{ui_pin}",
            UI_ROOT,
        )
    else:
        print(f"recomp-ui already present: {UI_ROOT}")

    ensure_framework_patches()
    print("bootstrap complete; next: python tools/lostevo.py build")


# ---------------------------------------------------------------------------
# ROM patching


def _patch_mapping(rom, rel: str) -> tuple[str, bytes]:
    """Return (kind, source bytes) for one XZP member."""
    if rel == "arm9.bin":
        return "arm9", bytes(rom.arm9) + bytes(rom.arm9PostData)
    if rel.startswith("overlay/"):
        overlay_id = int(Path(rel).stem.removeprefix("overlay_"))
        overlay = rom.loadArm9Overlays()[overlay_id]
        return "file", bytes(rom.files[int(overlay.fileID)])
    name = rel
    if name.startswith("data/"):
        name = name[len("data/"):]
    if rom.filenames.idOf(name) is None:
        name = Path(name).name
    return "named", name, bytes(rom.getFileByName(name))


def apply_xzp(rom_file: Path, xzp_file: Path, output: Path,
              *, expect_base_sha1: str | None = None,
              expect_output_sha1: str | None = None) -> str:
    try:
        import ndspy.rom
    except ImportError as exc:  # pragma: no cover - environment problem
        raise SystemExit(
            "ndspy is required: python -m pip install -r requirements.txt"
        ) from exc

    base_sha1 = sha1_file(rom_file)
    if expect_base_sha1 and base_sha1 != expect_base_sha1:
        raise SystemExit(
            f"base ROM SHA-1 mismatch: got {base_sha1}, expected {expect_base_sha1}"
        )
    rom = ndspy.rom.NintendoDSRom.fromFile(rom_file)
    xdelta = find_xdelta()
    log: list[str] = []

    with zipfile.ZipFile(xzp_file) as archive, tempfile.TemporaryDirectory(
        prefix="lostevo-xzp-"
    ) as temp_name:
        temp = Path(temp_name)
        for info in archive.infolist():
            raw = info.filename.replace("\\", "/")
            if raw == "banner.bin":
                rom.iconBanner = archive.read(info)
                log.append(f"banner: {len(rom.iconBanner):,} bytes (direct)")
                continue
            if not raw.startswith("xdelta/"):
                name = raw
                if name.startswith("data/"):
                    name = name[len("data/"):]
                if rom.filenames.idOf(name) is not None:
                    data = archive.read(info)
                    rom.setFileByName(name, data)
                    log.append(f"{name}: {len(data):,} bytes (direct)")
                else:
                    log.append(f"{raw}: ignored (no matching ROM file)")
                continue
            rel = raw[len("xdelta/"):]
            patch_file = temp / (rel.replace("/", "_") + ".xdelta")
            patch_file.write_bytes(archive.read(info))
            mapped = _patch_mapping(rom, rel)
            kind = mapped[0]
            if kind == "named":
                _, name, source = mapped
            else:
                source = mapped[1]
                name = rel
            source_file = temp / (rel.replace("/", "_") + ".source")
            target_file = temp / (rel.replace("/", "_") + ".target")
            source_file.write_bytes(source)
            result = subprocess.run(
                [str(xdelta), "-d", "-f", "-s", str(source_file),
                 str(patch_file), str(target_file)],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                raise SystemExit(
                    f"xdelta failed for {rel}: {result.stderr.strip()}"
                )
            target = target_file.read_bytes()
            if kind == "arm9":
                if target[-12:-8] == b"\x21\x06\xC0\xDE":
                    rom.arm9 = target[:-12]
                    rom.arm9PostData = target[-12:]
                elif rom.arm9PostData and target.endswith(rom.arm9PostData):
                    rom.arm9 = target[:-len(rom.arm9PostData)]
                else:
                    rom.arm9 = target
            elif kind == "file":
                if rel.startswith("overlay/"):
                    overlay_id = int(Path(rel).stem.removeprefix("overlay_"))
                    file_id = int(rom.loadArm9Overlays()[overlay_id].fileID)
                    rom.files[file_id] = target
                else:
                    rom.setFileByName(name, target)
            else:
                rom.setFileByName(name, target)
            log.append(f"{rel}: {len(source):,} -> {len(target):,} bytes")

    data = rom.save()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    digest = sha1_bytes(data)
    print("\n".join(log))
    print(f"patched ROM: {output} ({len(data):,} bytes, SHA-1 {digest})")
    if expect_output_sha1 and digest != expect_output_sha1:
        print(
            "note: output SHA-1 differs from the canonical NitroPatcher hash "
            f"({expect_output_sha1}); this is expected for the ndspy repack and "
            "does not affect the patched files."
        )
    return digest


def download_chinese_patch(lang: dict) -> Path:
    patch = lang.get("patch")
    if not patch:
        raise SystemExit(f"language '{lang['id']}' has no downloadable patch")
    release = DOWNLOAD_DIR / "DSLEChsLocalization.v1.0.1.zip"
    if not release.is_file() or sha256_file(release) != patch["release_sha256"]:
        _download(patch["release_url"], release)
    if sha256_file(release) != patch["release_sha256"]:
        raise SystemExit("downloaded Chinese patch release failed SHA-256 verification")

    with zipfile.ZipFile(release) as archive:
        candidates = [
            info for info in archive.infolist()
            if info.filename.lower().endswith(".xzp")
            and "汉化补丁" in info.filename
        ]
        if not candidates:
            candidates = [
                info for info in archive.infolist()
                if info.filename.lower().endswith(".xzp")
            ]
        if not candidates:
            raise SystemExit("release archive contains no .xzp patch")
        data = archive.read(candidates[0])
    xzp = DOWNLOAD_DIR / "DSLEChsLocalization.v1.0.1-zh-Hans.xzp"
    xzp.write_bytes(data)
    if sha256_file(xzp) != patch["patch_sha256"]:
        raise SystemExit("Chinese .xzp failed SHA-256 verification")
    print(f"Chinese patch ready: {xzp} ({len(data):,} bytes)")
    return xzp


def patch_language(lang: dict, *, force: bool = False) -> Path:
    target = rom_path(lang)
    patch = lang.get("patch")
    if not patch:
        raise SystemExit(f"language '{lang['id']}' has no patch")
    if target.is_file() and not force:
        digest = sha1_file(target)
        print(f"already patched: {target} (SHA-1 {digest})")
        return target
    base = base_rom_path(patch)
    if not base.is_file():
        raise SystemExit(f"base ROM not found: {base}")
    xzp = download_chinese_patch(lang)
    digest = apply_xzp(
        base, xzp, target,
        expect_base_sha1=patch["base_sha1"],
        expect_output_sha1=patch.get("canonical_output_sha1"),
    )
    manifest = load_manifest()
    for item in manifest["languages"]:
        if item["id"] == lang["id"]:
            item["sha1"] = digest
            item["rom_size"] = target.stat().st_size
            if item.get("status") == "pending":
                item["status"] = "patched"
    save_manifest(manifest)
    write_language_config(lang, digest, target.stat().st_size)
    return target


# ---------------------------------------------------------------------------
# prepare and bank generation


def write_language_config(lang: dict, digest: str, size: int) -> None:
    path = config_path(lang)
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        text = re.sub(r'(?m)^sha1\s*=.*$', f'sha1 = "{digest}"', text)
        text = re.sub(r'(?m)^rom_size\s*=.*$', f"rom_size = 0x{size:08X}", text)
        text = re.sub(
            r'(?m)^rom\s*=.*$',
            f'rom = "{lang["rom"]}"',
            text,
        )
        path.write_text(text, encoding="utf-8", newline="\n")
        return
    text = f"""# Auto-generated language profile for {lang['name']} ({lang['edition']}).
# Refresh with: python tools/lostevo.py build

[game]
name = "Digimon Story: Lost Evolution ({lang['native_name']})"
id = "BLEJ"
region = "{lang.get('region', 'JPN')}"
revision = 0
status = "language-pack profile"
rom = "{lang['rom']}"
rom_size = 0x{size:08X}
sha1 = "{digest}"

[display]
screen_layout = "single"
supersampling = 1
antialiasing = 0

[system]
startup_mode = "automatic"

[cartridge]
save_type = "eeprom"
save_size = 65536

[arm9]
rom_offset = 0x00004000
entry_pc = 0x02000800
load_address = 0x02000000
size = 0x0015C6B8

[arm7]
rom_offset = 0x000D9C00
entry_pc = 0x02380000
load_address = 0x02380000
size = 0x00026370
"""
    path.write_text(text, encoding="utf-8", newline="\n")


def prepare_language(lang: dict, *, force: bool = False) -> Path:
    rom = rom_path(lang)
    if not rom.is_file():
        if lang.get("patch") and force:
            rom = patch_language(lang, force=False)
        else:
            raise SystemExit(
                f"ROM not found for {lang['id']}: {rom}\n"
                f"put the dump there or run `python tools/lostevo.py patch {lang['id']}`"
            )
    digest = sha1_file(rom)
    expected = lang.get("sha1")
    if expected and digest != expected:
        print(
            f"warning: {lang['id']} ROM SHA-1 is {digest}, manifest says {expected}; "
            "refreshing the manifest/config"
        )
        manifest = load_manifest()
        for item in manifest["languages"]:
            if item["id"] == lang["id"]:
                item["sha1"] = digest
                item["rom_size"] = rom.stat().st_size
        save_manifest(manifest)
        lang["sha1"] = digest
        lang["rom_size"] = rom.stat().st_size

    out = inputs_path(lang)
    if force and out.exists():
        shutil.rmtree(out)
    cmd = [
        sys.executable, ROOT / "tools" / "prepare_lostevo.py",
        "--rom", rom, "--out", out, "--label", lang["edition"],
    ]
    if lang.get("sha1"):
        cmd += ["--expect-sha1", lang["sha1"]]
    run(cmd)
    write_language_config(lang, digest, rom.stat().st_size)
    return out


def ensure_recompiler() -> Path:
    if RECOMPILER.is_file():
        return RECOMPILER
    cmake = find_cmake()
    ninja = find_ninja(cmake)
    env = build_env(cmake)
    run([cmake, "-G", "Ninja", "-S", FRAMEWORK / "recompiler",
         "-B", FRAMEWORK / "recompiler" / "build",
         "-DCMAKE_BUILD_TYPE=Release",
         *compiler_args(cmake)], env=env)
    run([cmake, "--build", FRAMEWORK / "recompiler" / "build"], env=env)
    return RECOMPILER


def _bank_stamp(lang: dict, inputs: Path) -> dict:
    rom_info = inputs / "rom.json"
    digest = ""
    if rom_info.is_file():
        try:
            digest = json.loads(rom_info.read_text(encoding="utf-8")).get("sha1", "")
        except ValueError:
            digest = ""
    return {
        "language": lang["id"],
        "rom_sha1": digest or lang.get("sha1", ""),
        "arm9_sha1": sha1_file(inputs / "arm9.bin") if (inputs / "arm9.bin").is_file() else "",
        "arm7_sha1": sha1_file(inputs / "arm7.bin") if (inputs / "arm7.bin").is_file() else "",
    }


def build_banks(lang: dict, *, force: bool = False) -> Path:
    recompiler = ensure_recompiler()
    inputs = inputs_path(lang)
    if not (inputs / "arm9.bin").is_file():
        inputs = prepare_language(lang)
    out = bank_path(lang)
    out.mkdir(parents=True, exist_ok=True)
    arm9_dispatch = out / "lostevo_arm9_dispatch.c"
    arm7_dispatch = out / "lostevo_arm7_dispatch.c"
    stamp_path = out / "bank.json"
    stamp = _bank_stamp(lang, inputs)
    if not force and arm9_dispatch.is_file() and arm7_dispatch.is_file():
        if not stamp_path.is_file():
            stamp_path.write_text(
                json.dumps(stamp, indent=2) + "\n", encoding="utf-8"
            )
            print(f"banks already present: {out} (stamped)")
            return out
        try:
            old = json.loads(stamp_path.read_text(encoding="utf-8"))
        except ValueError:
            old = {}
        # Banks contain ARM9/ARM7 code only; a changed container layout or a
        # filesystem-only language patch does not require recompilation.
        if old.get("arm9_sha1") == stamp["arm9_sha1"] and \
                old.get("arm7_sha1") == stamp["arm7_sha1"]:
            print(f"banks already present: {out}")
            return out
        print(f"inputs changed; rebuilding banks: {out}")
    log = run_file("build", f"{lang['id']}-banks.log")
    env = build_env(find_cmake())
    run_logged([
        recompiler, "--config", inputs / "arm9.toml",
        "--bin", inputs / "arm9.bin", "--out", out,
        "--bank", "lostevo_arm9", "--shards", "8",
    ], log, env=env)
    run_logged([
        recompiler, "--config", inputs / "arm7.toml",
        "--bin", inputs / "arm7.bin", "--out", out,
        "--bank", "lostevo_arm7", "--shards", "4",
    ], log, env=env)
    stamp_path.write_text(json.dumps(_bank_stamp(lang, inputs), indent=2) + "\n",
                          encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# runner build


def retail_bios_available() -> bool:
    """True when both of the user's own BIOS dumps are in run/bios/ and valid."""
    for name, expected in EXPECTED_BIOS.items():
        source = BIOS_DIR / name
        if not source.is_file():
            return False
        if sha1_file(source) != expected:
            raise SystemExit(
                f"BIOS dump failed SHA-1 verification: {source}\n"
                "remove it to boot with the bundled FreeBIOS instead"
            )
    return True


def bios_source() -> str:
    """'retail' when the user's dumps are present, otherwise 'freebios'."""
    return "retail" if retail_bios_available() else "freebios"


def ensure_bios() -> str:
    source = bios_source()
    if source == "retail":
        target_dir = FRAMEWORK / "bios"
        target_dir.mkdir(parents=True, exist_ok=True)
        for name, expected in EXPECTED_BIOS.items():
            target = target_dir / name
            if target.is_file() and sha1_file(target) == expected:
                continue
            shutil.copyfile(BIOS_DIR / name, target)
    return source


def ensure_bios_banks(source: str) -> None:
    """Recompile the BIOS banks.

    The runner links a bank for the retail-BIOS slot and one for FreeBIOS.
    Without dumps the retail slot is filled from FreeBIOS as well (as the
    other ndsrecomp title ports do), and the runner is started with
    --freebios. A marker file rebuilds the slot when the source changes.
    """
    recompiler = ensure_recompiler()
    generated = FRAMEWORK / "generated"
    generated.mkdir(parents=True, exist_ok=True)
    freebios = FRAMEWORK / "third_party" / "freebios"
    marker = generated / "lostevo-bios-source.txt"
    previous = marker.read_text(encoding="utf-8").strip() if marker.is_file() else "retail"
    if previous != source:
        for bank in ("arm9_bios", "arm7_bios"):
            for suffix in ("", "_dispatch"):
                (generated / f"{bank}{suffix}.c").unlink(missing_ok=True)
    if source == "retail":
        slot9 = (FRAMEWORK / "bios" / "biosnds9.toml", FRAMEWORK / "bios" / "biosnds9.rom")
        slot7 = (FRAMEWORK / "bios" / "biosnds7.toml", FRAMEWORK / "bios" / "biosnds7.rom")
    else:
        slot9 = (FRAMEWORK / "bios" / "freebios9.toml", freebios / "drastic_bios_arm9.bin")
        slot7 = (FRAMEWORK / "bios" / "freebios7.toml", freebios / "drastic_bios_arm7.bin")
    jobs = [
        ("arm9_bios", *slot9),
        ("arm7_bios", *slot7),
        ("freebios_arm9", FRAMEWORK / "bios" / "freebios9.toml",
         freebios / "drastic_bios_arm9.bin"),
        ("freebios_arm7", FRAMEWORK / "bios" / "freebios7.toml",
         freebios / "drastic_bios_arm7.bin"),
    ]
    for bank, config, binary in jobs:
        if (generated / f"{bank}.c").is_file():
            continue
        if not binary.is_file():
            raise SystemExit(f"missing input for {bank}: {binary}")
        run_logged([
            recompiler, "--config", config, "--bin", binary,
            "--out", generated, "--bank", bank,
        ], run_file("build", f"{bank}.log"), env=build_env(find_cmake()))
    marker.write_text(source + "\n", encoding="utf-8")


def runner_bios_args() -> list[str]:
    """Runner flags for the BIOS the banks were built from."""
    return [] if bios_source() == "retail" else ["--freebios"]


def build_runner(*, sdl_backend: str = "SDL3", configure_only: bool = False) -> Path:
    ensure_framework_patches()
    source = ensure_bios()
    print(f"BIOS: {'your own dumps (run/bios)' if source == 'retail' else 'bundled FreeBIOS'}")
    ensure_bios_banks(source)
    manifest = load_manifest()
    available = []
    for lang in manifest["languages"]:
        banks = bank_path(lang)
        if (banks / "lostevo_arm9_dispatch.c").is_file() and (
            banks / "lostevo_arm7_dispatch.c"
        ).is_file():
            available.append((lang, banks))
    if not available:
        raise SystemExit(
            "no generated banks found; run `python tools/lostevo.py build` first"
        )
    cmake = find_cmake()
    ninja = find_ninja(cmake)
    env = build_env(cmake)
    dirs = ";".join(banks.as_posix() for _, banks in available)
    hashes = ";".join(lang["sha1"] for lang, _ in available)
    cmd = [
        cmake, "-G", "Ninja", "-S", FRAMEWORK / "runner", "-B", BUILD_DIR,
        "-DCMAKE_BUILD_TYPE=Release",
        "-DNDS_BOOTSTRAP_FIRMWARE=ON",
        "-UNDS_TITLE_BANK_DIRS", "-UNDS_TITLE_ROM_SHA1S", "-UNDS_RECOMP_UI_ROOT",
        f"-DNDS_TITLE_BANK_DIRS={dirs}",
        f"-DNDS_TITLE_ROM_SHA1S={hashes}",
        f"-DNDS_RECOMP_UI_ROOT={UI_ROOT.as_posix()}",
        f"-DNDS_SDL_BACKEND={sdl_backend}",
        *compiler_args(cmake),
    ]
    run(cmd, env=env)
    if not configure_only:
        run_logged(
            [cmake, "--build", BUILD_DIR, "--target", "nds_runner"],
            run_file("build", "runner.log"), env=env,
        )
    info = {
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "runner": str(RUNNER),
        "build_dir": str(BUILD_DIR),
        "framework": str(FRAMEWORK),
        "recomp_ui": str(UI_ROOT),
        "sdl_backend": sdl_backend,
        "bios": source,
        "languages": [
            {"id": lang["id"], "sha1": lang["sha1"], "banks": str(banks)}
            for lang, banks in available
        ],
    }
    info_path = run_file("build", "runner.json")
    info_path.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    print(f"runner {'configured' if configure_only else 'ready'}: {RUNNER}")
    return RUNNER


# ---------------------------------------------------------------------------
# status / verify / play


def status_rows() -> list[dict]:
    manifest = load_manifest()
    rows = []
    for lang in manifest["languages"]:
        rom = rom_path(lang)
        digest = sha1_file(rom) if rom.is_file() else None
        inputs = inputs_path(lang)
        banks = bank_path(lang)
        config = config_path(lang)
        rows.append({
            "id": lang["id"],
            "name": lang["name"],
            "native_name": lang["native_name"],
            "rom": str(rom),
            "rom_exists": rom.is_file(),
            "sha1_ok": bool(digest and digest == lang.get("sha1")),
            "sha1": digest,
            "config": str(config),
            "config_exists": config.is_file(),
            "inputs": inputs.is_dir(),
            "banks": (banks / "lostevo_arm9_dispatch.c").is_file(),
            "status": lang.get("status", "unknown"),
        })
    return rows


def status_command(args: argparse.Namespace) -> None:
    rows = status_rows()
    if args.json:
        print(json.dumps(rows, indent=2))
        return
    print(f"runner: {RUNNER} ({'present' if RUNNER.is_file() else 'not built'})")
    print(f"framework: {FRAMEWORK}")
    print()
    header = f"{'id':8} {'language':22} {'rom':4} {'sha1':5} {'banks':6} {'config':7} status"
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{row['id']:8} {row['name'][:22]:22} "
            f"{'yes' if row['rom_exists'] else 'no':4} "
            f"{'ok' if row['sha1_ok'] else 'no':5} "
            f"{'yes' if row['banks'] else 'no':6} "
            f"{'yes' if row['config_exists'] else 'no':7} {row['status']}"
        )


def verify_language(lang: dict, frames: int | None = None) -> dict:
    if not RUNNER.is_file():
        raise SystemExit("runner not built; run `python tools/lostevo.py build`")
    rom = rom_path(lang)
    if not rom.is_file():
        raise SystemExit(f"ROM not found: {rom}")
    out = run_dir("verify", lang["id"])
    port = 23000 + zlib.crc32(lang["id"].encode("utf-8")) % 500
    env = dict(os.environ)
    cmake = find_cmake()
    env = build_env(cmake)
    env["NDS_GENERATED_FIRMWARE"] = "on"
    env["NDS_BOOT_MODE"] = "direct"
    if bios_source() == "freebios":
        env["NDS_FREEBIOS"] = "on"
    vblanks = frames or int(lang.get("verify_vblanks", 300))
    cmd = [
        sys.executable, FRAMEWORK / "tools" / "title_smoke.py",
        "--runner", RUNNER, "--bios", FRAMEWORK / "bios",
        "--rom", rom, "--config", config_path(lang),
        "--out", out, "--label", lang["id"],
        "--attract-vblanks", str(vblanks),
        "--checkpoint-every", str(max(100, vblanks // 3)),
        "--fuzz-steps", "0", "--port", str(port),
    ]
    run(cmd, env=env)
    report_file = out / "report.json"
    report = json.loads(report_file.read_text(encoding="utf-8"))
    report["language"] = lang["id"]
    report["vblanks"] = vblanks
    (out / "verification.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return report


def verify_command(args: argparse.Namespace) -> None:
    manifest = load_manifest()
    explicit = bool(args.language)
    languages = [resolve_language(manifest, item) for item in args.language] \
        if args.language else manifest["languages"]
    results = []
    for lang in languages:
        if not rom_path(lang).is_file():
            if explicit:
                results.append({"language": lang["id"], "passed": False,
                                "failures": [f"ROM not found: {rom_path(lang)}"]})
            else:
                print(f"\n=== verify {lang['id']} === skipped: ROM not found")
            continue
        print(f"\n=== verify {lang['id']} ({lang['native_name']}) ===")
        try:
            report = verify_language(lang, args.frames)
            results.append({
                "language": lang["id"],
                "passed": bool(report.get("passed")),
                "frames_non_black": report.get("frames_non_black"),
                "frames_captured": report.get("frames_captured"),
                "failures": report.get("failures", []),
            })
        except SystemExit as exc:
            results.append({"language": lang["id"], "passed": False,
                            "failures": [str(exc)]})
    print("\nverification summary")
    for result in results:
        state = "PASS" if result["passed"] else "FAIL"
        print(f"  {result['language']:10} {state}  {result.get('failures', [])}")
    if not all(result["passed"] for result in results):
        raise SystemExit(1)


def choose_language(manifest: dict, wanted: str | None) -> dict:
    if wanted:
        return resolve_language(manifest, wanted)
    if STATE_FILE.is_file():
        try:
            selected = json.loads(STATE_FILE.read_text(encoding="utf-8")).get("language")
        except (OSError, ValueError):
            selected = None
        if selected:
            return resolve_language(manifest, selected)
    return resolve_language(manifest, manifest.get("default", "en"))


def interactive_language_menu(manifest: dict) -> dict:
    languages = manifest["languages"]
    print("\nDigimon Story: Lost Evolution — choose a language")
    print("-" * 52)
    for index, lang in enumerate(languages, 1):
        rom = rom_path(lang)
        mark = "ready" if rom.is_file() else "ROM missing"
        print(f"  {index}. {lang['native_name']} ({lang['name']}) — {mark}")
    print("  q. quit")
    while True:
        choice = input("> ").strip()
        if choice.lower() in {"q", "quit", "exit"}:
            raise SystemExit(0)
        if choice.isdigit() and 1 <= int(choice) <= len(languages):
            return languages[int(choice) - 1]
        for lang in languages:
            if choice.lower() in {lang["id"].lower(), lang["name"].lower(),
                                  lang["native_name"].lower()}:
                return lang
        print("not a valid choice")


def play_command(args: argparse.Namespace) -> None:
    manifest = load_manifest()
    if not RUNNER.is_file():
        raise SystemExit("runner not built; run `python tools/lostevo.py build` first")
    if args.language:
        lang = resolve_language(manifest, args.language)
    elif sys.stdin.isatty():
        lang = interactive_language_menu(manifest)
    else:
        lang = choose_language(manifest, None)
    rom = rom_path(lang)
    if not rom.is_file():
        raise SystemExit(
            f"ROM missing for {lang['id']}: {rom}\n"
            f"run `python tools/lostevo.py patch {lang['id']}` or place the dump there"
        )
    digest = sha1_file(rom)
    if digest != lang.get("sha1"):
        raise SystemExit(
            f"ROM SHA-1 mismatch for {lang['id']}: got {digest}, "
            f"expected {lang['sha1']}; run `python tools/lostevo.py build`"
        )
    if not config_path(lang).is_file():
        raise SystemExit(f"config missing: {config_path(lang)}")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps({"language": lang["id"], "selected_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")},
                   indent=2) + "\n",
        encoding="utf-8",
    )
    save = (ROOT / lang["save"]).resolve()
    save.parent.mkdir(parents=True, exist_ok=True)
    firmware_state = (ROOT / "saves" / f"firmware-{lang['id']}.bin").resolve()
    savestate_dir = (ROOT / "saves" / f"states-{lang['id']}").resolve()
    savestate_dir.mkdir(parents=True, exist_ok=True)
    cmd: list[str | Path] = [
        RUNNER, (FRAMEWORK / "bios").resolve(),
        "--interactive", "--rom", rom, "--config", config_path(lang),
        "--save-path", save, "--firmware-state-path", firmware_state,
        "--savestate-dir", savestate_dir,
        "--screen-layout", args.layout,
    ]
    if args.firmware:
        if bios_source() != "retail":
            raise SystemExit("--firmware needs your own BIOS dumps in run/bios/")
        cmd += ["--firmware-path", Path(args.firmware).resolve()]
    else:
        cmd += ["--generated-firmware", "--boot", "direct"]
    cmd += runner_bios_args()
    extra = list(args.extra)
    if extra and extra[0] == "--":
        extra = extra[1:]
    cmd += extra
    cmake = find_cmake()
    env = build_env(cmake)
    if args.audio_queue_frames is not None:
        env["NDS_AUDIO_QUEUE_FRAMES"] = str(args.audio_queue_frames)
    else:
        env.setdefault("NDS_AUDIO_QUEUE_FRAMES", "1536")
    if args.audio_start_frames is not None:
        env["NDS_AUDIO_START_FRAMES"] = str(args.audio_start_frames)
    else:
        env.setdefault("NDS_AUDIO_START_FRAMES", "24576")
    if args.audio_fade_frames is not None:
        env["NDS_AUDIO_FADE_FRAMES"] = str(args.audio_fade_frames)
    else:
        env.setdefault("NDS_AUDIO_FADE_FRAMES", "256")
    print(f"\nlanguage: {lang['native_name']} ({lang['id']})")
    print(f"ROM:      {rom}")
    print(f"save:     {save}")
    print()
    if args.dry_run:
        print(" ".join(str(part) for part in cmd))
        return
    run(cmd, cwd=BUILD_DIR, env=env)


def build_command(args: argparse.Namespace) -> None:
    manifest = load_manifest()
    explicit = bool(args.language)
    if not args.no_bootstrap and (
        not (FRAMEWORK / "runner" / "CMakeLists.txt").is_file()
        or not (UI_ROOT / "src" / "common" / "recomp_runtime_ui.c").is_file()
    ):
        print("framework checkout incomplete; bootstrapping pinned sources")
        bootstrap_command(argparse.Namespace(force=False))
    if args.bootstrap:
        bootstrap_command(argparse.Namespace(force=False))
    manifest = load_manifest()
    languages = [resolve_language(manifest, item) for item in args.language] \
        if args.language else manifest["languages"]
    for lang in languages:
        print(f"\n=== {lang['id']} ({lang['native_name']}) ===")
        if lang.get("patch") and not rom_path(lang).is_file():
            print("ROM missing; applying the language patch first")
            patch_language(lang, force=False)
        if not rom_path(lang).is_file():
            if explicit:
                raise SystemExit(f"ROM not found for {lang['id']}: {rom_path(lang)}")
            print(f"skipping {lang['id']}: ROM not found ({rom_path(lang)})")
            continue
        prepare_language(lang, force=args.force)
        build_banks(lang, force=args.force)
    build_runner(sdl_backend=args.sdl_backend, configure_only=args.configure_only)


def patch_command(args: argparse.Namespace) -> None:
    manifest = load_manifest()
    lang = resolve_language(manifest, args.language)
    target = patch_language(lang, force=args.force)
    print(f"language patch ready: {target}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="show ROM/config/bank/runner status")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=status_command)

    bootstrap = sub.add_parser("bootstrap", help="fetch pinned ndsrecomp/recomp-ui")
    bootstrap.add_argument("--force", action="store_true")
    bootstrap.set_defaults(func=bootstrap_command)

    patch = sub.add_parser("patch", help="apply a language patch to a base ROM")
    patch.add_argument("language")
    patch.add_argument("--force", action="store_true")
    patch.set_defaults(func=patch_command)

    build = sub.add_parser("build", help="prepare inputs, banks and the runner")
    build.add_argument("--language", action="append", default=[])
    build.add_argument("--force", action="store_true")
    build.add_argument("--bootstrap", action="store_true",
                       help="refresh the pinned framework checkouts before building")
    build.add_argument("--no-bootstrap", action="store_true",
                       help="fail instead of fetching a missing framework checkout")
    build.add_argument("--sdl-backend", default="SDL3", choices=["SDL3", "SDL2", "NONE"])
    build.add_argument("--configure-only", action="store_true")
    build.set_defaults(func=build_command)

    verify = sub.add_parser("verify", help="boot each language and check screenshots")
    verify.add_argument("--language", action="append", default=[])
    verify.add_argument("--frames", type=int)
    verify.set_defaults(func=verify_command)

    play = sub.add_parser("play", help="launch the runner with a language profile")
    play.add_argument("--language")
    play.add_argument("--layout", default="single",
                      choices=["stacked", "single", "separate"],
                      help="window layout (default: audited single-screen)")
    play.add_argument("--firmware", help="use a retail firmware dump instead of generated firmware")
    play.add_argument("--audio-queue-frames", type=int,
                      help="steady audio queue target (default 1536)")
    play.add_argument("--audio-start-frames", type=int,
                      help="boot audio prebuffer (default 24576)")
    play.add_argument("--audio-fade-frames", type=int,
                      help="fade-in frames after audio starts (default 256)")
    play.add_argument("--dry-run", action="store_true", help="print the runner command only")
    play.add_argument("extra", nargs=argparse.REMAINDER)
    play.set_defaults(func=play_command)

    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
