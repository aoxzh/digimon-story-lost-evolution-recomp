#!/usr/bin/env python3
"""Release packaging and one-click kit checks (no ROM or network needed)."""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import package_release  # noqa: E402
import setup_kit  # noqa: E402


class PackagerTests(unittest.TestCase):
    def test_refuses_game_data(self) -> None:
        for rel in (
            "roms/game.nds",
            "saves/lostevo-en.sav",
            "run/bios/biosnds9.rom",
            "ndsrecomp/bios/biosnds7.rom",
            "ndsrecomp/bios/generated-identity.bin",
            "generated/recomp/lostevo_arm9.c",
            "android/app/src/main/jniLibs/arm64-v8a/libmain.so",
            "android/app/build/outputs/apk/debug/app-debug.apk",
        ):
            self.assertIsNotNone(package_release.refusal(rel), rel)

    def test_allows_framework_sources(self) -> None:
        for rel in (
            "ndsrecomp/bios/biosnds9.toml",
            "ndsrecomp/third_party/freebios/drastic_bios_arm9.bin",
            "ndsrecomp/runner/src/main.cpp",
            "tools/lostevo.py",
        ):
            self.assertIsNone(package_release.refusal(rel), rel)
            self.assertFalse(package_release.skipped(rel), rel)

    def test_skips_build_output(self) -> None:
        for rel in ("ndsrecomp/runner/build-lostevo/nds_runner.exe",
                    "ndsrecomp/recompiler/build/CMakeCache.txt",
                    "kit/cmake/bin/cmake.exe", "run/build.log"):
            self.assertTrue(package_release.skipped(rel), rel)

    def test_readme_first_hashes_match_manifest(self) -> None:
        manifest = json.loads((ROOT / "languages/manifest.json").read_text(encoding="utf-8"))
        for lang in manifest["languages"]:
            if not lang.get("patch"):
                self.assertIn(lang["sha1"], package_release.README_FIRST, lang["id"])


class KitTests(unittest.TestCase):
    def test_components_are_pinned(self) -> None:
        names = set()
        for component in setup_kit.COMPONENTS:
            self.assertRegex(component.sha256, r"^[0-9a-f]{64}$", component.name)
            self.assertTrue(component.url.startswith("https://"), component.name)
            self.assertNotIn(component.target, names)
            names.add(component.target)

    def test_play_bat_calls_setup_kit(self) -> None:
        text = (ROOT / "play.bat").read_text(encoding="utf-8")
        self.assertIn(r"tools\setup_kit.py", text)
        self.assertTrue(re.search(r"bootstrap_python\.ps1", text))


if __name__ == "__main__":
    unittest.main()
