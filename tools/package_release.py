#!/usr/bin/env python3
"""Package the title tooling (never ROMs or generated game code).

The archive contains only source, docs and configs. It is safe to publish; a
user supplies their own ROM; the framework is fetched at build time.
"""

from __future__ import annotations

import argparse
import hashlib
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

FORBIDDEN_SUFFIXES = {".nds", ".sav", ".dsv", ".bin", ".rom", ".xzp", ".zip",
                      ".log"}
FORBIDDEN_PARTS = {"generated", "run", "downloads", ".state", ".venv", ".venv-win",
                   "__pycache__", "build", ".gradle", "jniLibs", ".idea",
                   "local.properties",
                   "SDL3-3.4.18", "sdl-build-android", "sdl-android-prefix",
                   "widemelon-main", "jdk21"}


def package(output: Path) -> tuple[int, str]:
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for entry in INCLUDE:
            path = ROOT / entry
            if path.is_file():
                candidates = [path]
            elif path.is_dir():
                candidates = sorted(p for p in path.rglob("*") if p.is_file())
            else:
                continue
            for file in candidates:
                relative = file.relative_to(ROOT)
                if any(part in FORBIDDEN_PARTS for part in relative.parts):
                    continue
                if file.suffix.lower() in FORBIDDEN_SUFFIXES:
                    continue
                archive.write(file, relative.as_posix())
                count += 1
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    return count, digest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path,
                        default=ROOT / "dist" / "lostevo-recomp-tooling.zip")
    args = parser.parse_args()
    count, digest = package(args.out.resolve())
    print(f"packaged {count} files -> {args.out.resolve()}")
    print(f"sha256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
