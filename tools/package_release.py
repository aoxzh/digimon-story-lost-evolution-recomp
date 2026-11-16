#!/usr/bin/env python3
"""Package a release archive. It never contains game data.

    package_release.py --out dist/x.zip              sources/tooling only
    package_release.py --windows-kit --out dist/x.zip
        the one-click Windows download: sources plus the pinned ndsrecomp /
        recomp-ui framework sources, already patched (run
        `python tools/lostevo.py bootstrap` first), so players need neither
        git nor a framework download. play.bat fetches the compiler kit and
        builds the game from the player's own ROM.

Every file is checked against REFUSALS; a match aborts the run instead of
being silently skipped, so a ROM, BIOS dump, save or generated bank can never
end up in a published archive.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

INCLUDE = [
    "README.md",
    "README.zh-CN.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "VERSION",
    "requirements.txt",
    "play.bat",
    "game.toml",
    "game-ja.toml",
    "game-zh.toml",
    "ndsrecomp.pin",
    "recomp-ui.pin",
    "languages/manifest.json",
    "patches",
    "docs",
    "media",
    "tools",
    "tests",
    "android",
]
FRAMEWORK_DIRS = ["ndsrecomp", "recomp-ui"]

# Never shipped, whatever the source: abort if one of these is selected.
REFUSALS = [
    (r"\.(nds|srl|sav|dsv|state|xzp|apk)$", "game data / saves / built app"),
    (r"(^|/)biosnds[79]\.(rom|bin)$", "BIOS dump"),
    (r"(^|/)firmware[^/]*\.bin$|generated-identity\.bin$", "firmware / identity"),
    (r"(^|/)lostevo_arm[79][^/]*\.(c|h)$", "recompiled game code"),
    (r"(^|/)libmain\.so$", "Android build with game code"),
]
# Build output and local state: skipped quietly.
SKIP_PARTS = {"__pycache__", ".git", ".gradle", ".idea", ".vscode", ".cxx",
              "jniLibs", "generated", "run", "roms", "saves", "kit", "dist",
              "downloads", ".state"}
SKIP_SUFFIXES = {".pyc", ".log", ".tar.gz", ".zip", ".part", ".exe", ".dll", ".obj",
                 ".o", ".a", ".lib", ".pdb"}
# Binary inputs the framework build legitimately needs (FreeBIOS, BSD-2-Clause).
ALLOW = {
    "ndsrecomp/third_party/freebios/drastic_bios_arm9.bin",
    "ndsrecomp/third_party/freebios/drastic_bios_arm7.bin",
}

README_FIRST = """Digimon Story: Lost Evolution Recomp {version} - Windows
==========================================================

A native PC port made by static recompilation. NOT an emulator, and this
download contains NO game data. You need your own ROM dump(s).

1. Unzip this whole folder somewhere you can write to (not Program Files).
2. Put your dump(s) in the roms folder (any file name), or drag them onto
   play.bat. Supported:
     Japanese retail (BLEJ rev 0)           SHA-1 f180146f517712c177d6497125a24f35b0d6102f
     English, Operation Decoded v1.1 AP fix SHA-1 83b4104e654ed2423c0a609802ec6b2843874fd3
   With the Japanese dump, the simplified-Chinese edition is made for you.
3. Double-click play.bat.

The first start downloads a private compiler kit into kit\\ (about 250 MiB,
SHA-256 verified; plus Python if you have none) and builds the game from
your ROM in roughly 5-15 minutes. Later starts are immediate. No BIOS dump
is needed (FreeBIOS is built in).

Controls: arrows = D-pad, Z = A, X = B, S = X, A = Y, Q/W = L/R,
Enter = Start, Backspace = Select, mouse = touch screen,
Shift+F1-F12 = save state, F1-F12 = load state.

Saves: saves\\lostevo-<language>.sav    Build log: run\\build.log
To rebuild: play.bat --rebuild

Windows SmartScreen may warn about scripts from the internet: More info ->
Run anyway. Unofficial fan project; see README.md and THIRD_PARTY_NOTICES.md.
Never share the roms, saves, generated or run folders: they contain the game.
"""


def refusal(rel: str) -> str | None:
    if rel in ALLOW:
        return None
    for pattern, why in REFUSALS:
        if re.search(pattern, rel.lower()):
            return why
    return None


def skipped(rel: str) -> bool:
    if rel in ALLOW:
        return False
    parts = rel.split("/")
    if any(part in SKIP_PARTS or part.startswith("build") for part in parts[:-1]):
        return True
    lower = rel.lower()
    return any(lower.endswith(suffix) for suffix in SKIP_SUFFIXES)


def collect(entries: list[str]) -> list[Path]:
    files: list[Path] = []
    for entry in entries:
        path = ROOT / entry
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(sorted(p for p in path.rglob("*") if p.is_file()))
    return files


def package(output: Path, *, windows_kit: bool) -> tuple[int, str]:
    entries = list(INCLUDE)
    if windows_kit:
        for name in FRAMEWORK_DIRS:
            if not (ROOT / name).is_dir():
                raise SystemExit(f"{name}/ missing; run `python tools/lostevo.py bootstrap` first")
        if not (ROOT / "ndsrecomp" / ".lostevo-patches.json").is_file():
            raise SystemExit("framework patches not recorded; run `python tools/lostevo.py bootstrap`")
        entries += FRAMEWORK_DIRS
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    refused: list[str] = []
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file in collect(entries):
            rel = file.relative_to(ROOT).as_posix()
            if skipped(rel):
                continue
            why = refusal(rel)
            if why:
                refused.append(f"{rel} ({why})")
                continue
            if file.suffix.lower() in (".bat", ".cmd", ".ps1"):
                # cmd.exe misreads labels in LF-only batch files.
                data = file.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
                archive.writestr(rel, data)
            else:
                archive.write(file, rel)
            count += 1
        if windows_kit:
            archive.writestr("README-FIRST.txt",
                             README_FIRST.format(version=version).replace("\n", "\r\n"))
            archive.writestr("roms/PUT-YOUR-ROMS-HERE.txt",
                             "Put your own .nds dumps in this folder (any file name).\r\n")
            count += 2
    if refused:
        output.unlink(missing_ok=True)
        raise SystemExit("refusing to package game data:\n  " + "\n  ".join(refused))
    with zipfile.ZipFile(output) as archive:
        for name in archive.namelist():
            if refusal(name):
                output.unlink(missing_ok=True)
                raise SystemExit(f"archive audit failed on {name}")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_name(output.name + ".sha256").write_text(
        f"{digest}  {output.name}\n", encoding="utf-8")
    return count, digest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path,
                        default=ROOT / "dist" / "lostevo-recomp-sources.zip")
    parser.add_argument("--windows-kit", action="store_true",
                        help="include the patched framework sources and README-FIRST")
    args = parser.parse_args()
    count, digest = package(args.out.resolve(), windows_kit=args.windows_kit)
    print(f"packaged {count} files -> {args.out.resolve()}")
    print(f"sha256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
