#!/usr/bin/env python3
"""Capture and inspect the runner's native SPU output.

The interactive frontend resamples the DS's 32728.5 Hz stream to the host
device. This tool bypasses the device and captures the pre-resample PCM through
the debug server, so a pop or clipping problem can be attributed to the game /
SPU rather than the host resampler.

  python tools/audio_audit.py --language en --vblanks 6000
  python tools/audio_audit.py --language en --vblanks 9000 --wav
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import subprocess
import sys
import time
import wave
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "tools"))

from paths import BIOS, FRAMEWORK_TOOLS, ROOT, RUNNER  # noqa: E402
from lostevo import build_env, find_cmake, rom_path, runner_bios_args, load_manifest, resolve_language  # noqa: E402

sys.path.insert(0, str(FRAMEWORK_TOOLS))

from title_smoke import DebugClient  # noqa: E402

DS_RATE = 33513982 // 1024  # 32728 Hz


def capture(client: DebugClient, limit: int = 1 << 20) -> tuple[bytes, dict]:
    # Ask beyond the produced position to get the retention window metadata
    # without triggering the "start is no longer retained" check.
    first = client.cmd("audio_samples", start=1 << 62, count=0)
    oldest = int(first.get("oldest", 0))
    produced = int(first.get("produced", 0))
    chunks: list[bytes] = []
    position = oldest
    while position < produced and sum(len(c) for c in chunks) < limit:
        reply = client.cmd("audio_samples", start=position,
                           count=min(4096, produced - position))
        count = int(reply["count"])
        if count <= 0:
            break
        chunks.append(bytes.fromhex(reply["pcm_s16le"]))
        position += count
    return b"".join(chunks), {"oldest": oldest, "produced": produced,
                              "captured_frames": position - oldest}


def analyze(pcm: bytes) -> dict:
    samples = struct.unpack("<%dh" % (len(pcm) // 2), pcm)
    if not samples:
        return {"frames": 0}
    peak = max(abs(s) for s in samples)
    clipped = sum(1 for s in samples if abs(s) >= 32767)
    mean = sum(samples) / len(samples)
    rms = (sum(s * s for s in samples) / len(samples)) ** 0.5
    max_delta = 0
    jumps = 0
    for a, b in zip(samples, samples[1:]):
        delta = abs(b - a)
        max_delta = max(max_delta, delta)
        if delta > 16000:
            jumps += 1
    return {
        "frames": len(samples) // 2,
        "peak": peak,
        "clipped_samples": clipped,
        "mean": round(mean, 2),
        "rms": round(rms, 2),
        "max_inter_sample_delta": max_delta,
        "large_jumps_gt_16000": jumps,
    }


def plot_waveform(pcm: bytes, path: Path, info: dict) -> None:
    samples = struct.unpack("<%dh" % (len(pcm) // 2), pcm)
    if not samples:
        return
    left = samples[0::2]
    width, height = 1200, 360
    image = Image.new("RGB", (width, height), (248, 248, 248))
    draw = ImageDraw.Draw(image)
    draw.line((0, height // 2, width, height // 2), fill=(180, 180, 180))
    step = max(1, len(left) // width)
    for x in range(width):
        chunk = left[x * step:(x + 1) * step]
        if not chunk:
            break
        low = min(chunk)
        high = max(chunk)
        y0 = height // 2 - high * (height // 2) // 32768
        y1 = height // 2 - low * (height // 2) // 32768
        draw.line((x, y0, x, y1), fill=(30, 90, 160))
    draw.rectangle((10, 10, 470, 76), fill=(255, 255, 255))
    draw.text((16, 14),
              f"frames {info.get('frames', 0)}  peak {info.get('peak', 0)}  "
              f"rms {info.get('rms', 0)}",
              fill=(20, 20, 20))
    draw.text((16, 34),
              f"clipped {info.get('clipped_samples', 0)}  "
              f"max delta {info.get('max_inter_sample_delta', 0)}  "
              f"jumps>16k {info.get('large_jumps_gt_16000', 0)}",
              fill=(20, 20, 20))
    draw.text((16, 54), f"rate {info.get('rate', DS_RATE)} Hz  left channel",
              fill=(20, 20, 20))
    image.save(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", default="en")
    parser.add_argument("--vblanks", type=int, default=6000)
    parser.add_argument("--port", type=int, default=24600)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--wav", action="store_true")
    args = parser.parse_args()

    lang = resolve_language(load_manifest(), args.language)
    rom = rom_path(lang)
    config = (ROOT / lang["config"]).resolve()
    if not RUNNER.is_file():
        raise SystemExit(f"runner not built: {RUNNER}")
    out = (args.out or ROOT / "run" / "audio-audit" / lang["id"]).resolve()
    out.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(RUNNER), str(BIOS), "--serve", "--port", str(args.port),
        "--rom", str(rom), "--no-save", "--config", str(config),
        "--generated-firmware", "--boot", "direct", *runner_bios_args(),
    ]
    env = build_env(find_cmake())
    log = (out / f"runner-{args.vblanks}.log").open("wb")
    proc = subprocess.Popen(cmd, cwd=str(RUNNER.parent), stdout=log,
                            stderr=subprocess.STDOUT, env=env)
    report: dict = {"language": lang["id"], "vblanks": args.vblanks}
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
        client.advance_to(args.vblanks)
        pcm, meta = capture(client)
        result = analyze(pcm)
        result.update(meta)
        result["rate"] = DS_RATE
        report["audio"] = result
        if pcm:
            plot_path = out / f"waveform-{args.vblanks}.png"
            plot_waveform(pcm, plot_path, result)
            report["waveform"] = str(plot_path)
        if args.wav and pcm:
            wav_path = out / f"audio-{args.vblanks}.wav"
            with wave.open(str(wav_path), "wb") as wav:
                wav.setnchannels(2)
                wav.setsampwidth(2)
                wav.setframerate(DS_RATE)
                wav.writeframes(pcm)
            report["wav"] = str(wav_path)
        print(json.dumps(report, indent=2))
    except Exception as exc:  # noqa: BLE001 - the failure is the result
        report["error"] = str(exc)
        print(f"FAIL: {exc}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
    (out / f"report-{args.vblanks}.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return 0 if "error" not in report else 1


if __name__ == "__main__":
    raise SystemExit(main())
