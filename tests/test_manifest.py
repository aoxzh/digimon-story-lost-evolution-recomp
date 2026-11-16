#!/usr/bin/env python3
"""Manifest/config consistency checks that do not need a ROM or framework."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "languages" / "manifest.json"


class ManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_unique_ids_and_required_fields(self) -> None:
        ids = [item["id"] for item in self.manifest["languages"]]
        self.assertEqual(len(ids), len(set(ids)), "language ids must be unique")
        required = {
            "id", "name", "native_name", "edition", "rom", "sha1",
            "rom_size", "config", "bank_dir", "save",
        }
        for item in self.manifest["languages"]:
            self.assertTrue(required <= item.keys(), f"{item.get('id')}: missing fields")
            self.assertRegex(item["sha1"], r"^[0-9a-f]{40}$")
            self.assertGreater(item["rom_size"], 0)
            self.assertFalse(Path(item["rom"]).is_absolute(),
                             f"{item['id']}: ROM path should stay portable")
            self.assertEqual(Path(item["rom"]).parts[0], "roms",
                             f"{item['id']}: ROMs live in the ignored roms/ folder")
            base = item.get("patch", {}).get("base_rom")
            if base:
                self.assertEqual(Path(base).parts[0], "roms")

    def test_default_exists(self) -> None:
        ids = {item["id"] for item in self.manifest["languages"]}
        self.assertIn(self.manifest["default"], ids)

    def test_configs_match_manifest(self) -> None:
        for item in self.manifest["languages"]:
            config = ROOT / item["config"]
            self.assertTrue(config.is_file(), f"missing config: {config}")
            text = config.read_text(encoding="utf-8")
            sha = re.search(r'(?m)^sha1\s*=\s*"([0-9a-f]{40})"', text)
            self.assertIsNotNone(sha, f"{config}: no sha1")
            self.assertEqual(sha.group(1), item["sha1"],
                             f"{config}: sha1 differs from manifest")
            size = re.search(r"(?m)^rom_size\s*=\s*0x([0-9A-Fa-f]+)", text)
            self.assertIsNotNone(size, f"{config}: no rom_size")
            self.assertEqual(int(size.group(1), 16), item["rom_size"],
                             f"{config}: rom_size differs from manifest")

    def test_patch_metadata(self) -> None:
        for item in self.manifest["languages"]:
            patch = item.get("patch")
            if not patch:
                continue
            for key in ("release_url", "release_sha256", "patch_sha256",
                        "base_rom", "base_sha1"):
                self.assertIn(key, patch, f"{item['id']}: patch missing {key}")
            self.assertRegex(patch["release_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(patch["patch_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(patch["base_sha1"], r"^[0-9a-f]{40}$")


class RepositoryHygieneTests(unittest.TestCase):
    def test_no_game_data_or_binaries_tracked_in_android(self) -> None:
        jni = ROOT / "android" / "app" / "src" / "main" / "jniLibs"
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("android/app/src/main/jniLibs/", ignore,
                      "libmain.so contains recompiled game code and must stay ignored")
        for pattern in ("*.nds", "*.sav", "generated/", "roms/", "run/"):
            self.assertIn(pattern, ignore)
        del jni


if __name__ == "__main__":
    unittest.main()
