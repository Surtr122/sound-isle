"""Create a small, copyright-free demo library for screenshots.

This script is intentionally simple: it writes quiet sine tones as WAV files.
It is not part of the application and its output is ignored by git.
"""

from __future__ import annotations

import math
import shutil
import struct
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / ".demo-library"
ASSETS = ROOT.parent / ".demo-assets"

TRACKS = [
    ("岛屿来信 - 晨雾.wav", 65.0, 220.0),
    ("岛屿来信 - 潮汐.wav", 72.0, 247.0),
    ("钢琴 - 海面.wav", 48.0, 196.0),
    ("岛屿电台 EP01.wav", 55.0, 174.0),
    ("第01章 出发.wav", 60.0, 262.0),
    ("课程 01 入门.wav", 50.0, 294.0),
    ("海浪 01.wav", 3.0, 330.0),
    ("风声 02.wav", 4.0, 392.0),
    ("脚步 01.wav", 2.0, 146.0),
    ("叹息 01.wav", 2.5, 174.0),
    ("攻击 01.wav", 1.2, 523.0),
    ("录音 001.wav", 40.0, 440.0),
]
RATE = 8000


def write_tone(path: Path, seconds: float, frequency: float) -> None:
    frames = int(seconds * RATE)
    fade = min(int(RATE * 1.5), frames // 3)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        data = bytearray()
        for index in range(frames):
            envelope = min(1.0, index / fade if fade else 1.0, (frames - index) / fade if fade else 1.0)
            value = math.sin(2 * math.pi * frequency * index / RATE) * 0.10 * envelope
            data += struct.pack("<h", int(value * 32767))
        handle.writeframes(bytes(data))


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    for name, seconds, frequency in TRACKS:
        path = ROOT / name
        if path.exists():
            continue
        write_tone(path, seconds, frequency)
        print(f"created {path.name}  {seconds:.0f}s")
    if ASSETS.is_dir():
        shutil.copytree(ASSETS, ROOT / "3D", dirs_exist_ok=True)
        print(f"copied 3D demo assets from {ASSETS.name}")
    print(f"demo library: {ROOT}")


if __name__ == "__main__":
    main()
