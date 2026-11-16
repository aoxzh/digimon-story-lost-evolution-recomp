#!/usr/bin/env python3
"""Deploy the Android runner and its user-supplied files to a device.

The APK never contains game data. This helper installs the debug APK, copies
the ROM/BIOS/config into the app's internal ``files/`` directory through
``/data/local/tmp`` + ``run-as`` (direct external app-dir access returns EACCES
on Android 11+), and can launch the activity and pull the runner log.

Example (Windows, device over wireless ADB):

    python tools/android_deploy.py ^
      --serial <device-serial-or-ip:port> ^
      --language en ^
      --rom "C:\\path\\to\\lostevo.nds" ^
      --bios-dir run\\bios ^
      --apk android\\app\\build\\outputs\\apk\\debug\\app-debug.apk ^
      --launch --log run\\android-run.log --screenshot run\\android.png

Nothing is written back into the repository except the optional log and
screenshot. Use ``--dry-run`` to print the adb commands without touching the
device.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PACKAGE = "io.github.lostevo.recomp"
ACTIVITY = "io.github.lostevo.recomp.SetupActivity"
REMOTE_ROOT = f"/data/data/{PACKAGE}/files"
STAGING = "/data/local/tmp"


def find_adb(explicit: str | None) -> str:
    if explicit:
        return explicit
    found = shutil.which("adb")
    if found:
        return found
    candidates = [
        Path(os.environ.get("ANDROID_HOME", "")) / "platform-tools" / "adb.exe",
        Path(os.environ.get("ANDROID_SDK_ROOT", "")) / "platform-tools" / "adb.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk"
        / "platform-tools" / "adb.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise SystemExit("adb not found; pass --adb or add platform-tools to PATH")


class Deployer:
    def __init__(self, adb: str, serial: str | None, dry_run: bool) -> None:
        self.adb = adb
        self.serial = serial
        self.dry_run = dry_run

    def run(
        self,
        args: list[str],
        *,
        capture: bool = False,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str] | None:
        command = [self.adb]
        if self.serial:
            command += ["-s", self.serial]
        command += args
        print("+", " ".join(command))
        if self.dry_run:
            return None
        result = subprocess.run(
            command,
            text=True,
            capture_output=capture,
            check=False,
        )
        if capture:
            if result.stdout:
                print(result.stdout.rstrip())
            if result.stderr:
                print(result.stderr.rstrip(), file=sys.stderr)
        if check and result.returncode != 0:
            raise SystemExit(f"adb failed ({result.returncode}): {' '.join(args)}")
        return result

    def shell(self, command: str, *, capture: bool = False,
              check: bool = True) -> subprocess.CompletedProcess[str] | None:
        return self.run(["shell", command], capture=capture, check=check)

    def push_and_copy(self, local: Path, remote_name: str) -> None:
        if not local.is_file():
            raise SystemExit(f"missing local file: {local}")
        staged = f"{STAGING}/{remote_name.replace('/', '_')}"
        self.run(["push", str(local), staged])
        self.shell(f"run-as {PACKAGE} cp {staged} files/{remote_name}")
        self.shell(f"rm -f {staged}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", help="path to adb")
    parser.add_argument("--serial", help="device serial (needed with several devices)")
    parser.add_argument("--language", choices=["en", "ja", "zh"], default="en",
                        help="profile to activate after deployment")
    parser.add_argument("--apk", type=Path, help="install this APK before deploying")
    parser.add_argument("--rom", type=Path, required=True, help="your own .nds dump")
    parser.add_argument("--bios-dir", type=Path, default=Path("run/bios"),
                        help="optional directory with your biosnds9.rom/biosnds7.rom; "
                             "without them the app boots on the bundled FreeBIOS")
    parser.add_argument("--config", type=Path,
                        help="title game.toml (defaults to the language profile)")
    parser.add_argument("--launch", action="store_true", help="start the activity")
    parser.add_argument("--wait", type=float, default=8.0,
                        help="seconds to wait after launch before pulling log/screenshot")
    parser.add_argument("--log", type=Path, help="copy files/android-run.log here")
    parser.add_argument("--screenshot", type=Path,
                        help="capture a device screenshot here")
    parser.add_argument("--dry-run", action="store_true",
                        help="print commands without executing them")
    args = parser.parse_args()

    bios9 = args.bios_dir / "biosnds9.rom"
    bios7 = args.bios_dir / "biosnds7.rom"
    config = args.config
    if config is None:
        config = Path("game.toml" if args.language == "en"
                      else f"game-{args.language}.toml")
    for path in (args.rom, config):
        if not path.is_file():
            raise SystemExit(f"missing required file: {path}")
    use_bios = bios9.is_file() and bios7.is_file()

    deployer = Deployer(find_adb(args.adb), args.serial, args.dry_run)

    if args.apk:
        deployer.run(["install", "-r", str(args.apk)])

    deployer.shell(f"run-as {PACKAGE} mkdir -p files/roms files/bios "
                   f"files/config files/saves")
    deployer.push_and_copy(args.rom, f"roms/lostevo-{args.language}.nds")
    if use_bios:
        deployer.push_and_copy(bios9, "bios/biosnds9.rom")
        deployer.push_and_copy(bios7, "bios/biosnds7.rom")
    else:
        print("no BIOS dumps given; the app will boot on FreeBIOS")
    deployer.push_and_copy(config, f"config/{args.language}.toml")
    deployer.shell(
        f"run-as {PACKAGE} sh -c 'echo -n {args.language} > "
        f"files/config/active-language'")

    if args.launch:
        deployer.shell(f"am force-stop {PACKAGE}")
        deployer.shell(f"am start -n {PACKAGE}/{ACTIVITY}")

        if args.launch and (args.log or args.screenshot):
            if args.wait > 0 and not args.dry_run:
                time.sleep(args.wait)

            if args.log:
                args.log.parent.mkdir(parents=True, exist_ok=True)
                result = deployer.shell(
                    f"run-as {PACKAGE} cat files/android-run.log",
                    capture=True, check=False)
                if result is not None and result.stdout:
                    text = result.stdout.replace("\r\n", "\n")
                    args.log.write_text(text, encoding="utf-8", newline="\n")
                    print(f"log -> {args.log}")

        if args.screenshot:
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            remote = f"{STAGING}/lostevo-screen.png"
            deployer.shell(f"screencap -p {remote}")
            deployer.run(["pull", remote, str(args.screenshot)])
            deployer.shell(f"rm -f {remote}")

    print("deploy complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
