#!/usr/bin/env python3
"""Render and screenshot the window layouts for visual audit.

The headless debug server exports native screen framebuffers, not the composed
window. This tool runs the interactive frontend with a deterministic key
schedule and the frontend's own screenshot hook, so the result is exactly what
a player sees.

  python tools/layout_audit.py --layout stacked
  python tools/layout_audit.py --layout single
  python tools/layout_audit.py --layout single --adaptive top --width 448
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "tools"))

from paths import BIOS, ROOT, RUNNER  # noqa: E402
from lostevo import build_env, find_cmake, rom_path, runner_bios_args, resolve_language, load_manifest  # noqa: E402

RELEASED = 0x0FFF
KEY_BITS = {
    "a": 0, "b": 1, "select": 2, "start": 3, "right": 4, "left": 5,
    "up": 6, "down": 7, "r": 8, "l": 9, "x": 10, "y": 11,
}


def setup_events() -> list[tuple[int, int, str]]:
    events = [
        (1201, 1210, "start"),
        (1501, 1510, "start"),
        (1561, 1570, "a"),
        (1681, 1690, "a"),
        (2101, 2110, "a"),
        (2410, 2419, "start"),   # accept default name
        (2460, 2469, "a"),       # name confirmation dialog
        (2500, 2509, "up"),      # select Yes
        (2560, 2569, "a"),
    ]
    # Advance the opening dialogue; the exact dialogue length varies a little
    # between languages, so mash A through the captured window.
    for frame in range(4800, 9600, 180):
        events.append((frame, frame + 5, "a"))
    return events


def input_spec(events: list[tuple[int, int, str]]) -> str:
    rows: dict[int, int] = {}
    for start, end, key in events:
        rows[start] = 1 << KEY_BITS[key]
        rows[end + 1] = 0
    return ",".join(f"{frame}:{mask}" for frame, mask in sorted(rows.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", default="en")
    parser.add_argument("--config", type=Path, help="override the language config")
    parser.add_argument("--rom", type=Path, help="override the language ROM")
    parser.add_argument("--layout", default="stacked",
                        choices=["stacked", "single", "separate"])
    parser.add_argument("--adaptive", choices=["none", "top"], default="none")
    parser.add_argument("--virtual-controls", choices=["off", "auto", "on"],
                        default="off")
    parser.add_argument("--portrait", action="store_true",
                        help="force the portrait single layout for audit")
    parser.add_argument("--width", type=int, default=448)
    parser.add_argument("--frames", type=int, default=9600)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    lang = resolve_language(load_manifest(), args.language)
    rom = (args.rom.resolve() if args.rom else rom_path(lang))
    config = (args.config or (ROOT / lang["config"])).resolve()
    if not RUNNER.is_file():
        raise SystemExit(f"runner not built: {RUNNER}")
    out = (args.out or ROOT / "run" / "layout-audit" / f"{lang['id']}-{args.layout}").resolve()
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("frame-*.bmp"):
        old.unlink()
    for old in out.glob("frame-*.png"):
        old.unlink()

    env = build_env(find_cmake())
    env["NDS_FRONTEND_MAX_FRAMES"] = str(args.frames)
    env["NDS_FRONTEND_SHOT_DIR"] = str(out)
    env["NDS_FRONTEND_SHOT_AT"] = "2400,4800,9000"
    env["NDS_FRONTEND_INPUT"] = input_spec(setup_events())
    if args.portrait:
        env["NDS_SINGLE_PORTRAIT"] = "1"

    cmd: list[str | Path] = [
        RUNNER, BIOS, "--interactive", "--rom", rom, "--config", config,
        "--generated-firmware", "--boot", "direct", *runner_bios_args(), "--no-save",
        "--screen-layout", args.layout,
        "--virtual-controls", args.virtual_controls,
    ]
    if args.adaptive != "none":
        cmd += ["--adaptive-widescreen", args.adaptive,
                "--widescreen-width", str(args.width)]
    print("> " + " ".join(str(part) for part in cmd))
    with (out / "runner.log").open("wb") as log:
        result = subprocess.run([str(part) for part in cmd],
                                cwd=str(RUNNER.parent), env=env,
                                stdout=log, stderr=subprocess.STDOUT,
                                timeout=max(120, args.frames // 30))
    report = {
        "language": lang["id"],
        "layout": args.layout,
        "adaptive": args.adaptive,
        "width": args.width,
        "virtual_controls": args.virtual_controls,
        "runner_returncode": result.returncode,
        "frames": [],
    }
    for bmp in sorted(out.glob("frame-*.bmp")):
        png = bmp.with_suffix(".png")
        image = Image.open(bmp)
        image.save(png)
        report["frames"].append({
            "frame": int(bmp.stem.split("-")[1]),
            "size": list(image.size),
            "png": str(png),
        })
    (out / "report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    return 0 if report["frames"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
