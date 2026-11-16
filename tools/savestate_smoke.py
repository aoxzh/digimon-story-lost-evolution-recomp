#!/usr/bin/env python3
"""Headless save-state round-trip check for one language profile.

The runner's slot UI uses F1..F12 (load) / Shift+F1..F12 (save). The debug
server exposes the same core savestate path as `state_save` / `state_load`,
which lets us verify it without a window:

  save at vblank 3000 -> advance -> load -> the vblank/event clocks return to
  the saved point and the state is accepted for this ROM/build identity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "tools"))

from paths import BIOS, FRAMEWORK_TOOLS, ROOT, RUNNER  # noqa: E402
from lostevo import build_env, find_cmake, rom_path, runner_bios_args  # noqa: E402

sys.path.insert(0, str(FRAMEWORK_TOOLS))

from title_smoke import DebugClient  # noqa: E402


def language(language_id: str) -> dict:
    manifest = json.loads((ROOT / "languages" / "manifest.json").read_text(encoding="utf-8"))
    for item in manifest["languages"]:
        if item["id"] == language_id:
            return item
    for item in manifest["languages"]:
        if item["id"].lower().startswith(language_id.lower()):
            return item
    raise SystemExit(f"unknown language: {language_id}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", default="en")
    parser.add_argument("--save-frame", type=int, default=3000)
    parser.add_argument("--advance", type=int, default=500)
    parser.add_argument("--port", type=int, default=24500)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    lang = language(args.language)
    rom = rom_path(lang)
    config = (ROOT / lang["config"]).resolve()
    if not RUNNER.is_file():
        raise SystemExit(f"runner not built: {RUNNER}")
    out = (args.out or ROOT / "run" / "savestate" / lang["id"]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    state = out / f"{lang['id']}.state"
    if state.exists():
        state.unlink()

    cmd = [
        str(RUNNER), str(BIOS), "--serve", "--port", str(args.port),
        "--rom", str(rom), "--no-save", "--config", str(config),
        "--generated-firmware", "--boot", "direct", *runner_bios_args(),
    ]
    env = build_env(find_cmake())
    log = (out / "runner.log").open("wb")
    proc = subprocess.Popen(cmd, cwd=str(RUNNER.parent), stdout=log,
                            stderr=subprocess.STDOUT, env=env)
    report: dict = {"language": lang["id"], "state": str(state)}
    client = None
    try:
        for _ in range(300):
            if proc.poll() is not None:
                raise RuntimeError(f"runner exited early rc={proc.returncode}")
            try:
                client = DebugClient(args.port, timeout=120)
                break
            except OSError:
                time.sleep(0.2)
        if client is None:
            raise RuntimeError("debug server never came up")
        client.cmd("reset")
        client.cmd("keys", mask=0x0FFF)
        client.advance_to(args.save_frame)
        before = client.cmd("event_counts")
        report["save_counts"] = before
        client.shot(out / "before-save.png")
        before_region = hashlib.sha1(
            json.dumps(client.cmd("read_region", region="mainram"),
                       sort_keys=True).encode("utf-8")
        ).hexdigest()
        report["before_mainram_sha1"] = before_region
        client.cmd("state_save", path=str(state))
        report["state_bytes"] = state.stat().st_size
        client.advance(args.advance)
        report["advanced_counts"] = client.cmd("event_counts")
        client.cmd("state_load", path=str(state))
        report["restored_counts"] = client.cmd("event_counts")
        after_region = hashlib.sha1(
            json.dumps(client.cmd("read_region", region="mainram"),
                       sort_keys=True).encode("utf-8")
        ).hexdigest()
        report["after_mainram_sha1"] = after_region
        client.shot(out / "after-load.png")
        report["passed"] = (
            report["state_bytes"] > 0
            and before_region == after_region
            and (out / "before-save.png").read_bytes()
            == (out / "after-load.png").read_bytes()
        )
    except Exception as exc:  # noqa: BLE001 - the failure is the result
        report["passed"] = False
        report["error"] = str(exc)
        print(f"FAIL: {exc}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()

    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n",
                                     encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"{lang['id']} savestate: {'PASS' if report.get('passed') else 'FAIL'}")
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
