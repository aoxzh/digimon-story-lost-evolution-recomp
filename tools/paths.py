#!/usr/bin/env python3
"""Shared path discovery for the title-local helper tools.

Environment overrides:
  NDSRECOMP_ROOT        ndsrecomp checkout (default ./ndsrecomp)
  RECOMP_UI_ROOT        recomp-ui checkout (default ./recomp-ui)
  LOSTEVO_RUNNER_BUILD  runner build directory (default <framework>/runner/build-lostevo)
  LOSTEVO_RUNNER        explicit runner executable
  LOSTEVO_ROM_DIR       directory holding your ROMs (default ./roms)
"""

from __future__ import annotations

import os
from pathlib import Path

from lostevo import BUILD_DIR, FRAMEWORK, ROOT, UI_ROOT  # noqa: F401

RUNNER = Path(
    os.environ.get(
        "LOSTEVO_RUNNER",
        BUILD_DIR / ("nds_runner.exe" if os.name == "nt" else "nds_runner"),
    )
).resolve()
# The runner's positional BIOS directory. With FreeBIOS (no dumps) the runner
# does not read BIOS files from it; with your own dumps, `lostevo.py build`
# copies them here after checking their SHA-1.
BIOS = FRAMEWORK / "bios"
GAME_TOML = ROOT / "game.toml"
FRAMEWORK_TOOLS = FRAMEWORK / "tools"
