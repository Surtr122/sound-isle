"""Generate a tiny, visibly skinned GLB for the 3D preview demo.

The file is synthetic and contains no third-party assets. It is intentionally
kept outside the application source and can be deleted at any time.
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path


def pad(data: bytes, fill: bytes, size: int = 4) -> bytes:
    extra = (-len(data)) % size
    return data + fill * extra


def main() -> None:
    target = Path(__file__).resolve().parent.parent / ".demo-assets" / "角色" / "蒙皮小人.glb"
    target.parent.mkdir(parents=True, exist_ok=True)

    # A simple 0.7 x 2.0 x 0.4 box, split into lower/upper weights.
    positions = [
        (-0.35, 0.0, -0.2),
        (0.35, 0.0, -0.2),
        (0.35, 0.0, 0.2),
        (-0.35, 0.0, 0.2),
        (-0.35, 2.0, -0.2),
        (0.35, 2.0, -0.2),
        (0.35, 2.0, 0.2),
        (-0.35, 2.0, 0.2),
    ]
    normals = []
    for x, y, z in positions:
        length = math.sqrt(x * x + (y - 1.0) ** 2 + z * z) or 1.0
        normals.append((x / length, (y - 1.0) / length, z / length))
    indices = [
        0, 2, 1, 0, 3, 2,
        4, 5, 6, 4, 6, 7,
        0, 1, 5, 0, 5, 4,
        1, 2, 6, 1, 6, 5,
        2, 3, 7, 2, 7, 6,
        3, 0, 4, 3, 4, 7,
    ]
    joints = [(0, 0, 0, 0)] * 4 + [(1, 0, 0, 0)] * 4
    weights = [(1.0, 0.0, 0.0, 0.0)] * 4 + [(1.0, 0.0, 0.0, 0.0)] * 4

    pos_bytes = b"".join(struct.pack("<3f", *p) for p in positions)
    normal_bytes = b"".join(struct.pack("<3f", *n) for n in normals)
    joint_bytes = b"".join(struct.pack("<4B", *j) for j in joints)
    weight_bytes = b"".join(struct.pack("<4f", *w) for w in weights)
    index_bytes = b"".join(struct.pack("<H", i) for i in indices)
    ibm_bytes = b"".join(
        struct.pack("<16f", *matrix)
        for matrix in (
            (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1),
            (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, -1, 0, 1),
        )
    )
    times = [0.0, 1.0]
    time_bytes = b"".join(struct.pack("<f", t) for t in times)
    angle = math.radians(55.0)
    quats = [(0.0, 0.0, 0.0, 1.0), (math.sin(angle / 2), 0.0, 0.0, math.cos(angle / 2))]
    quat_bytes = b"".join(struct.pack("<4f", *q) for q in quats)

    chunks = []
    offset = 0
    views = []

    def add_view(data: bytes, target: int | None = None) -> int:
        nonlocal offset
        padded = pad(data, b"\x00")
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(data), **({"target": target} if target else {})})
        chunks.append(padded)
        offset += len(padded)
        return len(views) - 1

    pos_view = add_view(pos_bytes, 34962)
    normal_view = add_view(normal_bytes, 34962)
    joint_view = add_view(joint_bytes, 34962)
    weight_view = add_view(weight_bytes, 34962)
    index_view = add_view(index_bytes, 34963)
    ibm_view = add_view(ibm_bytes)
    time_view = add_view(time_bytes)
    quat_view = add_view(quat_bytes)

    binary = b"".join(chunks)
    accessors = [
        {"bufferView": pos_view, "componentType": 5126, "count": 8, "type": "VEC3", "min": [-0.35, 0, -0.2], "max": [0.35, 2, 0.2]},
        {"bufferView": normal_view, "componentType": 5126, "count": 8, "type": "VEC3"},
        {"bufferView": joint_view, "componentType": 5121, "count": 8, "type": "VEC4"},
        {"bufferView": weight_view, "componentType": 5126, "count": 8, "type": "VEC4"},
        {"bufferView": index_view, "componentType": 5123, "count": len(indices), "type": "SCALAR"},
        {"bufferView": ibm_view, "componentType": 5126, "count": 2, "type": "MAT4"},
        {"bufferView": time_view, "componentType": 5126, "count": 2, "type": "SCALAR", "min": [0.0], "max": [1.0]},
        {"bufferView": quat_view, "componentType": 5126, "count": 2, "type": "VEC4"},
    ]
    gltf = {
        "asset": {"version": "2.0", "generator": "Sound & Form synthetic skin demo"},
        "scene": 0,
        "scenes": [{"nodes": [0, 3]}],
        "nodes": [
            {"name": "Armature", "children": [1]},
            {"name": "Hips", "children": [2], "translation": [0, 0, 0]},
            {"name": "Spine", "translation": [0, 1, 0]},
            {"name": "Body", "mesh": 0, "skin": 0},
        ],
        "meshes": [
            {
                "name": "BodyMesh",
                "primitives": [
                    {
                        "attributes": {"POSITION": 0, "NORMAL": 1, "JOINTS_0": 2, "WEIGHTS_0": 3},
                        "indices": 4,
                        "material": 0,
                        "mode": 4,
                    }
                ],
            }
        ],
        "materials": [
            {
                "name": "Clay",
                "pbrMetallicRoughness": {"baseColorFactor": [0.78, 0.36, 0.22, 1], "metallicFactor": 0.0, "roughnessFactor": 0.8},
                "doubleSided": True,
            }
        ],
        "skins": [{"name": "Rig", "joints": [1, 2], "skeleton": 1, "inverseBindMatrices": 5}],
        "animations": [
            {
                "name": "Wave",
                "samplers": [{"input": 6, "output": 7, "interpolation": "LINEAR"}],
                "channels": [{"sampler": 0, "target": {"node": 2, "path": "rotation"}}],
            }
        ],
        "bufferViews": views,
        "buffers": [{"byteLength": len(binary)}],
        "accessors": accessors,
    }
    json_bytes = pad(json.dumps(gltf, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), b" ")
    binary = pad(binary, b"\x00")
    total = 12 + 8 + len(json_bytes) + 8 + len(binary)
    glb = (
        struct.pack("<III", 0x46546C67, 2, total)
        + struct.pack("<II", len(json_bytes), 0x4E4F534A)
        + json_bytes
        + struct.pack("<II", len(binary), 0x004E4942)
        + binary
    )
    target.write_bytes(glb)
    print(f"wrote {target} ({len(glb)} bytes)")


if __name__ == "__main__":
    main()
