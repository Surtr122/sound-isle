"""Build a tiny, self-contained demo library for Form Isle.

Every file here is synthesised from code so the public screenshots never contain
the user's own assets.  The generated directory is ignored by git.
"""

from __future__ import annotations

import json
import math
import shutil
import struct
import zlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / ".demo-assets"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_png(path: Path, size: int, tint: tuple[int, int, int], seed: int) -> None:
    """A small procedural concrete / rust texture, no third-party packages."""
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            n = ((x * 374761393 + y * 668265263 + seed * 1442695040888963407) ^ (x * y * 31)) & 0xFFFFFFFF
            n = (n ^ (n >> 13)) * 1274126177 & 0xFFFFFFFF
            noise = (n & 0xFF) / 255.0
            grid = 1.0 if (x % 64 < 2 or y % 64 < 2) else 0.0
            shade = 0.74 + noise * 0.24 - grid * 0.18
            r = max(0, min(255, int(tint[0] * shade)))
            g = max(0, min(255, int(tint[1] * shade)))
            b = max(0, min(255, int(tint[2] * shade)))
            row.extend((r, g, b))
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 6)

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", raw)
    png += chunk(b"IEND", b"")
    path.write_bytes(png)


def glb_doc(name: str, meshes: int, materials: int, animations: list[str], skins: int = 0) -> bytes:
    # A tiny real skin + rotation track so the motion preview has something to
    # play. The mesh accessor metadata stays synthetic; this file is a demo.
    frame_count = 31
    times = [index / 30.0 for index in range(frame_count)]
    times_bin = struct.pack(f"<{frame_count}f", *times)
    rotations = []
    for index in range(frame_count):
        angle = 0.3 * math.sin(index / frame_count * math.tau)
        rotations.extend((0.0, 0.0, math.sin(angle / 2.0), math.cos(angle / 2.0)))
    rotations_bin = struct.pack(f"<{frame_count * 4}f", *rotations)
    binary = times_bin + rotations_bin
    binary += b"\x00" * ((4 - len(binary) % 4) % 4)
    buffer_views = [
        {"buffer": 0, "byteOffset": 0, "byteLength": len(times_bin)},
        {"buffer": 0, "byteOffset": len(times_bin), "byteLength": len(rotations_bin)},
    ]
    doc = {
        "asset": {"version": "2.0", "generator": "Sound & Form demo assets"},
        "scene": 0,
        "scenes": [{"name": "Demo", "nodes": [0]}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": buffer_views,
        "nodes": [
            {"name": name, "children": [1], "translation": [0.0, 0.0, 0.0]},
            {"name": "Spine", "children": [2, 3], "translation": [0.0, 1.0, 0.0]},
            {"name": "Left Arm", "translation": [-0.7, 0.6, 0.0]},
            {"name": "Right Arm", "translation": [0.7, 0.6, 0.0]},
        ],
        "meshes": [
            {"name": f"Mesh {i + 1}", "primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "material": 0}]}
            for i in range(meshes)
        ],
        "accessors": [
            {"count": 96 + meshes * 32, "type": "VEC3", "componentType": 5126},
            {"count": 144 + meshes * 48, "type": "SCALAR", "componentType": 5123},
            {"bufferView": 0, "count": frame_count, "type": "SCALAR", "componentType": 5126, "min": [0.0], "max": [1.0]},
            {"bufferView": 1, "count": frame_count, "type": "VEC4", "componentType": 5126},
        ],
        "materials": [{"name": f"Material {i + 1}"} for i in range(materials)],
        "animations": [
            {
                "name": label,
                "channels": [{"sampler": 0, "target": {"node": 0, "path": "rotation"}}],
                "samplers": [{"input": 2, "output": 3, "interpolation": "LINEAR"}],
            }
            for label in animations
        ],
        "skins": [{"name": "Rig", "joints": [0, 1, 2, 3]}] if skins else [],
        "textures": [{"source": 0}],
        "images": [{"name": "albedo"}],
    }
    data = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    data += b" " * ((4 - len(data) % 4) % 4)
    total = 12 + 8 + len(data) + 8 + len(binary)
    return (
        b"glTF"
        + struct.pack("<II", 2, total)
        + struct.pack("<II", len(data), 0x4E4F534A)
        + data
        + struct.pack("<II", len(binary), 0x004E4942)
        + binary
    )


def write_obj(path: Path, label: str, scale: float = 1.0) -> None:
    lines = [f"# Form Isle demo: {label}", "o DemoObject"]
    points = []
    for i in range(8):
        x = (1 if i & 1 else -1) * scale
        y = (1 if i & 2 else -1) * scale
        z = (1 if i & 4 else -1) * scale
        points.append((x, y, z))
        lines.append(f"v {x:.4f} {y:.4f} {z:.4f}")
    for i in range(4):
        lines.append(f"vt {(i & 1):.1f} {(i >> 1):.1f}")
    lines.append("vn 0 0 1")
    for i in range(6):
        a, b, c, d = (0, 1, 3, 2) if i == 0 else ((4, 6, 7, 5) if i == 1 else ((0, 4, 5, 1) if i == 2 else ((2, 3, 7, 6) if i == 3 else ((0, 2, 6, 4) if i == 4 else (1, 5, 7, 3)))))
        lines.append(f"f {a + 1}/1/1 {b + 1}/2/1 {c + 1}/3/1 {d + 1}/4/1")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_bvh(path: Path, frames: int, frame_time: float) -> None:
    lines = [
        "HIERARCHY",
        "ROOT Hips",
        "{",
        "  OFFSET 0 0 0",
        "  CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation",
        "  JOINT Spine",
        "  {",
        "    OFFSET 0 18 0",
        "    CHANNELS 3 Zrotation Xrotation Yrotation",
        "    JOINT Head",
        "    {",
        "      OFFSET 0 20 0",
        "      CHANNELS 3 Zrotation Xrotation Yrotation",
        "      End Site",
        "      {",
        "        OFFSET 0 10 0",
        "      }",
        "    }",
        "  }",
        "}",
        "MOTION",
        f"Frames: {frames}",
        f"Frame Time: {frame_time:.6f}",
    ]
    for frame in range(frames):
        phase = frame / max(1, frames - 1)
        lines.append(
            " ".join(
                f"{value:.4f}"
                for value in (
                    0.0,
                    0.0,
                    math.sin(phase * math.tau) * 2.0,
                    math.sin(phase * math.tau) * 6.0,
                    0.0,
                    0.0,
                    0.0,
                    math.sin(phase * math.tau + 0.5) * 18.0,
                    0.0,
                    0.0,
                    math.sin(phase * math.tau + 0.9) * 14.0,
                    0.0,
                )
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_fbx(path: Path) -> None:
    head = b"Kaydara FBX Binary  \x00\x1a\x00" + struct.pack("<I", 7400)
    path.write_bytes(head + b"\x00" * 200)


def main() -> None:
    if DEST.exists():
        shutil.rmtree(DEST)
    ensure_dir(DEST)

    ensure_dir(DEST / "角色")
    (DEST / "角色" / "荒原旅人.glb").write_bytes(
        glb_doc("Wasteland Traveler", meshes=2, materials=3, animations=["Idle", "Walk"], skins=1)
    )
    (DEST / "角色" / "守望者.glb").write_bytes(
        glb_doc("Watchman", meshes=1, materials=2, animations=["Lookout"], skins=1)
    )

    ensure_dir(DEST / "道具")
    write_obj(DEST / "道具" / "信号灯.obj", "Signal Lamp", scale=0.8)

    ensure_dir(DEST / "场景")
    write_fbx(DEST / "场景" / "废弃站台.fbx")

    ensure_dir(DEST / "动作")
    write_bvh(DEST / "动作" / "翻越.bvh", frames=48, frame_time=1 / 24)
    write_bvh(DEST / "动作" / "待机循环.bvh", frames=72, frame_time=1 / 30)

    ensure_dir(DEST / "贴图")
    write_png(DEST / "贴图" / "混凝土_albedo.png", 512, (158, 151, 137), seed=7)
    write_png(DEST / "贴图" / "锈迹_normal.png", 256, (125, 91, 70), seed=19)

    ensure_dir(DEST / "工程")
    (DEST / "工程" / "站台.blend").write_bytes(b"BLENDER-v300" + b"\x00" * 128)

    ensure_dir(DEST / "模型")
    write_obj(DEST / "模型" / "集装箱.obj", "Container", scale=1.4)

    ensure_dir(DEST / "其他")
    with zipfile.ZipFile(DEST / "其他" / "资产清单.zip", "w") as archive:
        archive.writestr("README.txt", "Form Isle demo manifest\n")

    total = sum(path.stat().st_size for path in DEST.rglob("*") if path.is_file())
    print(f"Demo assets written to {DEST}")
    print(f"{len(list(DEST.rglob('*.*')))} files, {total / 1024 / 1024:.2f} MB")


if __name__ == "__main__":
    main()
