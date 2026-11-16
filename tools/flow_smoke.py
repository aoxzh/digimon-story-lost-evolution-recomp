#!/usr/bin/env python3
"""Drive a fixed button schedule through the runner debug server.

This is the title-local flow probe: it advances to exact vblank targets, holds
keys over frame ranges, takes screenshots and reports any halt. The built-in
schedules reproduce the documented English setup path (title -> New game ->
name entry) and can be extended for gameplay bring-up.

Examples:
  python tools/flow_smoke.py --language en --schedule name-entry
  python tools/flow_smoke.py --language en --schedule new-game --out run/flow/en
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "tools"))

from paths import (  # noqa: E402
    BIOS,
    FRAMEWORK_TOOLS,
    GAME_TOML,
    ROOT,
    RUNNER,
)
from lostevo import build_env, find_cmake, rom_path, runner_bios_args  # noqa: E402

sys.path.insert(0, str(FRAMEWORK_TOOLS))

from title_smoke import DebugClient  # noqa: E402

KEY_BITS = {
    "a": 0,
    "b": 1,
    "select": 2,
    "start": 3,
    "right": 4,
    "left": 5,
    "up": 6,
    "down": 7,
    "r": 8,
    "l": 9,
    "x": 10,
    "y": 11,
}
RELEASED = 0x0FFF

SCHEDULES = {
    # Reproduces the bring-up route: A at 1561 accepts New, A at 1681 clears the
    # Wi-Fi notice, A at 2101 chooses Boy; frame 2400 is player-name entry.
    "name-entry": {
        "events": [
            (1201, 1210, "start"),
            (1501, 1510, "start"),
            (1561, 1570, "a"),
            (1681, 1690, "a"),
            (2101, 2110, "a"),
        ],
        "checkpoints": [1200, 1600, 2200, 2400],
    },
    # Tries the keyboard's Start shortcut to accept the default name.
    "name-start": {
        "events": [
            (1201, 1210, "start"),
            (1501, 1510, "start"),
            (1561, 1570, "a"),
            (1681, 1690, "a"),
            (2101, 2110, "a"),
            (2410, 2420, "start"),
            (2460, 2470, "a"),
        ],
        "checkpoints": [2400, 2500, 2800, 3200, 3600],
    },
    # Accepts the default name and confirms the "Is your name Shuu?" dialog.
    "new-game": {
        "events": [
            (1201, 1210, "start"),
            (1501, 1510, "start"),
            (1561, 1570, "a"),
            (1681, 1690, "a"),
            (2101, 2110, "a"),
            (2410, 2420, "start"),
            (2460, 2470, "a"),
            (2500, 2510, "up"),
            (2560, 2570, "a"),
        ],
        "checkpoints": [2400, 2600, 3000, 3600, 4200, 4800],
    },
    # Tries the keyboard's cancel path with the default name.
    "name-confirm": {
        "events": [
            (1201, 1210, "start"),
            (1501, 1510, "start"),
            (1561, 1570, "a"),
            (1681, 1690, "a"),
            (2101, 2110, "a"),
            (2410, 2420, "b"),
            (2460, 2470, "start"),
            (2500, 2510, "a"),
            (2560, 2570, "a"),
        ],
        "checkpoints": [2400, 2500, 2700, 3000, 3400],
    },
    # Continues the setup flow: tap the on-screen Enter button with the
    # default name (Shuu), then advance through the opening.
    "enter-game": {
        "events": [
            (1201, 1210, "start"),
            (1501, 1510, "start"),
            (1561, 1570, "a"),
            (1681, 1690, "a"),
            (2101, 2110, "a"),
        ],
        "touches": [(2410, 195, 181)],
        "checkpoints": [2400, 2600, 3000, 3600, 4200],
    },
}


def manifest_language(language: str) -> dict:
    manifest = json.loads((ROOT / "languages" / "manifest.json").read_text(encoding="utf-8"))
    languages = {item["id"]: item for item in manifest["languages"]}
    if language in languages:
        return languages[language]
    for key, item in languages.items():
        if key.lower().startswith(language.lower()):
            return item
    raise SystemExit(f"unknown language: {language}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", default="en")
    parser.add_argument("--config", type=Path, help="override the language config")
    parser.add_argument("--rom", type=Path, help="override the language ROM")
    parser.add_argument("--schedule", default="name-entry", choices=sorted(SCHEDULES))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--port", type=int, default=24000)
    parser.add_argument("--tier3", action="store_true")
    parser.add_argument("--runner-arg", action="append", default=[])
    parser.add_argument("--mash-a", help="hold A repeatedly between START:END:STEP frames")
    parser.add_argument("--checkpoint", action="append", type=int, default=[],
                        help="extra checkpoint frame (repeatable)")
    args = parser.parse_args()

    lang = manifest_language(args.language)
    rom = (args.rom.resolve() if args.rom else rom_path(lang))
    config = (args.config or (ROOT / lang["config"])).resolve()
    if not rom.is_file():
        raise SystemExit(f"ROM not found: {rom}")
    if not RUNNER.is_file():
        raise SystemExit(f"runner not built: {RUNNER}")
    out = (args.out or (ROOT / "run" / "flow" / f"{lang['id']}-{args.schedule}")).resolve()
    out.mkdir(parents=True, exist_ok=True)
    schedule = SCHEDULES[args.schedule]

    cmd = [
        str(RUNNER), str(BIOS), "--serve", "--port", str(args.port),
        "--rom", str(rom), "--no-save", "--config", str(config),
        "--generated-firmware", "--boot", "direct", *runner_bios_args(),
    ]
    if args.tier3:
        cmd.append("--force-tier3")
    cmd += args.runner_arg

    env = dict(os.environ)
    env["PATH"] = os.pathsep.join(
        [str(Path(RUNNER).parent), env.get("PATH", "")]
    )
    env = build_env(find_cmake())
    log = (out / "runner.log").open("wb")
    proc = subprocess.Popen(
        cmd, cwd=str(RUNNER.parent), stdout=log, stderr=subprocess.STDOUT, env=env
    )
    report: dict = {
        "language": lang["id"],
        "schedule": args.schedule,
        "rom": str(rom),
        "checkpoints": [],
        "failures": [],
    }
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
        client.cmd("keys", mask=RELEASED)
        for start, end, key in schedule["events"]:
            client.advance_to(start)
            client.cmd("keys", mask=RELEASED & ~(1 << KEY_BITS[key]))
            client.advance_to(end)
            client.cmd("keys", mask=RELEASED)
            print(f"  {key:<8} {start:>5}..{end:<5} ok")
        for frame, x, y in schedule.get("touches", []):
            client.advance_to(frame)
            client.cmd("touch", x=x, y=y, down=True)
            client.advance(12)
            client.cmd("touch", x=0, y=0, down=False)
            client.advance(4)
            print(f"  touch    {frame:>5} ({x},{y}) ok")
        if args.mash_a:
            start, end, step = (int(part) for part in args.mash_a.split(":"))
            for frame in range(start, end, step):
                client.advance_to(frame)
                client.cmd("keys", mask=RELEASED & ~(1 << KEY_BITS["a"]))
                client.advance(6)
                client.cmd("keys", mask=RELEASED)
                print(f"  mash-a   {frame:>5} ok")
        checkpoints = sorted(set(list(schedule["checkpoints"]) + list(args.checkpoint)))
        for checkpoint in checkpoints:
            if client.vblank() > checkpoint:
                print(f"  checkpoint {checkpoint:>5} skipped (already past)")
                continue
            client.advance_to(checkpoint)
            shot = out / f"frame-{checkpoint:06d}.png"
            luminance = client.shot(shot)
            counts = client.cmd("event_counts")
            row = {
                "frame": checkpoint,
                "vblank": client.vblank(),
                "luminance": luminance,
                "insn9": counts.get("insn9"),
                "insn7": counts.get("insn7"),
                "gpu3d": client.cmd("gx_state"),
                "shot": str(shot),
            }
            report["checkpoints"].append(row)
            print(
                f"  checkpoint {checkpoint:>5} vblank {row['vblank']:>5} "
                f"luminance {luminance:6.1f}"
            )
        report["final_vblank"] = client.vblank()
        report["dispatch_stats"] = client.cmd("dispatch_stats")
    except Exception as exc:  # noqa: BLE001 - the failure is the result
        report["failures"].append(str(exc))
        print(f"  FAILURE: {exc}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()

    report["passed"] = not report["failures"]
    (out / "report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\n{lang['id']} {args.schedule}: {'PASS' if report['passed'] else 'FAIL'}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
