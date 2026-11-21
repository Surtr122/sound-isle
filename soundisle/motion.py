"""Small, dependency-free BVH reader used by the motion preview.

This is deliberately a *preview* parser, not a production animation importer.
It projects the first 160 key poses into a compact 2D isometric skeleton so
the browser can show what an action file contains without a 3D engine.
"""

from __future__ import annotations

import base64
import bisect
import json
import math
import re
import struct
import zlib
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

MAX_BYTES = 64 * 1024 * 1024
MAX_PREVIEW_FRAMES = 160


class MotionError(Exception):
    """A user-facing BVH parsing problem."""


class _Joint:
    __slots__ = ("name", "parent", "offset", "channels", "is_end")

    def __init__(self, name: str, parent: int, offset: Sequence[float], is_end: bool = False):
        self.name = name
        self.parent = parent
        self.offset = (float(offset[0]), float(offset[1]), float(offset[2]))
        self.channels: List[str] = []
        self.is_end = is_end


def _mat_mul(a, b):
    return (
        (
            a[0][0] * b[0][0] + a[0][1] * b[1][0] + a[0][2] * b[2][0],
            a[0][0] * b[0][1] + a[0][1] * b[1][1] + a[0][2] * b[2][1],
            a[0][0] * b[0][2] + a[0][1] * b[1][2] + a[0][2] * b[2][2],
        ),
        (
            a[1][0] * b[0][0] + a[1][1] * b[1][0] + a[1][2] * b[2][0],
            a[1][0] * b[0][1] + a[1][1] * b[1][1] + a[1][2] * b[2][1],
            a[1][0] * b[0][2] + a[1][1] * b[1][2] + a[1][2] * b[2][2],
        ),
        (
            a[2][0] * b[0][0] + a[2][1] * b[1][0] + a[2][2] * b[2][0],
            a[2][0] * b[0][1] + a[2][1] * b[1][1] + a[2][2] * b[2][1],
            a[2][0] * b[0][2] + a[2][1] * b[1][2] + a[2][2] * b[2][2],
        ),
    )


def _axis_matrix(axis: str, angle: float):
    c, s = math.cos(angle), math.sin(angle)
    if axis == "X":
        return ((1.0, 0.0, 0.0), (0.0, c, -s), (0.0, s, c))
    if axis == "Y":
        return ((c, 0.0, s), (0.0, 1.0, 0.0), (-s, 0.0, c))
    return ((c, -s, 0.0), (s, c, 0.0), (0.0, 0.0, 1.0))


def _apply(matrix, vector):
    x, y, z = vector
    return (
        matrix[0][0] * x + matrix[0][1] * y + matrix[0][2] * z,
        matrix[1][0] * x + matrix[1][1] * y + matrix[1][2] * z,
        matrix[2][0] * x + matrix[2][1] * y + matrix[2][2] * z,
    )


def _parse_hierarchy(tokens: Sequence[str]) -> Tuple[List[_Joint], int]:
    joints: List[_Joint] = []
    i = 1  # skip HIERARCHY

    def expect(value: str) -> None:
        nonlocal i
        if i >= len(tokens) or tokens[i] != value:
            raise MotionError("BVH 层级不完整。")
        i += 1

    def parse_offset() -> Tuple[float, float, float]:
        nonlocal i
        expect("OFFSET")
        values = tuple(float(tokens[i + k]) for k in range(3))
        i += 3
        return values

    def parse_channels(joint: _Joint) -> None:
        nonlocal i
        expect("CHANNELS")
        count = int(tokens[i])
        i += 1
        joint.channels = list(tokens[i : i + count])
        i += count

    def parse_joint(kind: str, parent: int) -> int:
        nonlocal i
        name = tokens[i] if kind == "End" else tokens[i]
        i += 1
        if kind == "End":
            # "End Site": tokens are End, Site. We already consumed End.
            name = "End Site"
            if i < len(tokens) and tokens[i] == "Site":
                i += 1
        expect("{")
        offset = parse_offset()
        joint = _Joint(name, parent, offset, is_end=(kind == "End"))
        index = len(joints)
        joints.append(joint)
        if kind != "End":
            parse_channels(joint)
        else:
            expect("}")
            return index
        while i < len(tokens) and tokens[i] != "}":
            if tokens[i] == "JOINT":
                i += 1
                parse_joint("JOINT", index)
            elif tokens[i] == "End":
                i += 1
                parse_joint("End", index)
            else:
                # Ignore unknown hierarchy words to stay tolerant.
                i += 1
        expect("}")
        return index

    if not tokens or tokens[0] != "HIERARCHY":
        raise MotionError("不是有效的 BVH 文件。")
    expect("ROOT")
    parse_joint("ROOT", -1)
    return joints, i


def _sample_matrix(joint: _Joint, values: Sequence[float], cursor: int) -> Tuple[Tuple, Tuple[float, float, float], int]:
    rotation = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    translation = list(joint.offset)
    for channel in joint.channels:
        value = float(values[cursor])
        cursor += 1
        if channel == "Xposition":
            translation[0] += value
        elif channel == "Yposition":
            translation[1] += value
        elif channel == "Zposition":
            translation[2] += value
        elif channel.endswith("rotation"):
            axis = channel[0].upper()
            if axis in ("X", "Y", "Z"):
                rotation = _mat_mul(rotation, _axis_matrix(axis, math.radians(value)))
    return rotation, (translation[0], translation[1], translation[2]), cursor


def _normalise(points: List[Tuple[float, float, float]]) -> List[Tuple[float, float]]:
    if not points:
        return []
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    cx = (min(xs) + max(xs)) / 2.0
    cy = (min(ys) + max(ys)) / 2.0
    cz = (min(zs) + max(zs)) / 2.0
    span = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs), 1e-6)
    scale = 2.0 / span
    projected: List[Tuple[float, float]] = []
    for x, y, z in points:
        x = (x - cx) * scale
        y = (y - cy) * scale
        z = (z - cz) * scale
        # Isometric-ish, y-up. Normalised to [-1, 1].
        px = (x - z) * 0.8660254
        py = (x + z) * 0.5 - y
        projected.append((px, py))
    max_abs = max(max(abs(x), abs(y)) for x, y in projected) or 1.0
    return [(round(x / max_abs, 4), round(y / max_abs, 4)) for x, y in projected]


def load_bvh(path: Path | str) -> Optional[Dict[str, object]]:
    path = Path(path)
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    if "MOTION" not in text or "HIERARCHY" not in text:
        return None
    try:
        tokens = text.split()
        joints, cursor = _parse_hierarchy(tokens)
        if cursor >= len(tokens) or tokens[cursor] != "MOTION":
            return None
        cursor += 1
        if tokens[cursor] != "Frames:":
            return None
        frame_count = int(tokens[cursor + 1])
        cursor += 2
        if tokens[cursor] != "Frame" or tokens[cursor + 1] != "Time:":
            return None
        frame_time = float(tokens[cursor + 2])
        cursor += 3
        channel_count = sum(len(joint.channels) for joint in joints)
        if frame_count <= 0 or channel_count <= 0:
            return None
        values = [float(item) for item in tokens[cursor : cursor + frame_count * channel_count]]
        if len(values) < frame_count * channel_count:
            return None
    except (ValueError, IndexError, MotionError):
        return None

    channels = [len(joint.channels) for joint in joints]
    step = max(1, math.ceil(frame_count / MAX_PREVIEW_FRAMES))
    sample_indices = list(range(0, frame_count, step))
    if sample_indices[-1] != frame_count - 1:
        sample_indices.append(frame_count - 1)

    frames: List[List[Tuple[float, float]]] = []
    for frame_index in sample_indices:
        offset = frame_index * channel_count
        local_positions: List[Tuple[float, float, float]] = []
        local_rotations: List[Tuple] = []
        pointer = offset
        for joint in joints:
            rotation, translation, pointer = _sample_matrix(joint, values, pointer)
            local_positions.append(translation)
            local_rotations.append(rotation)
        world_positions: List[Tuple[float, float, float]] = []
        world_rotations: List[Tuple] = []
        for index, joint in enumerate(joints):
            local_position = local_positions[index]
            if joint.parent < 0:
                world_position = local_position
                world_rotation = local_rotations[index]
            else:
                parent = joint.parent
                world_position = tuple(
                    world_positions[parent][k] + _apply(world_rotations[parent], local_position)[k]
                    for k in range(3)
                )
                world_rotation = _mat_mul(world_rotations[parent], local_rotations[index])
            world_positions.append(world_position)
            world_rotations.append(world_rotation)
        frames.append(_normalise(world_positions))

    edges = [[joint.parent, index] for index, joint in enumerate(joints) if joint.parent >= 0]
    return {
        "kind": "bvh",
        "format": "BVH",
        "joints": [joint.name for joint in joints],
        "edges": edges,
        "frames": frames,
        "frame_count": frame_count,
        "preview_frames": len(frames),
        "fps": round(1.0 / frame_time, 3) if frame_time > 0 else 0,
        "duration": round(frame_count * frame_time, 3) if frame_time > 0 else 0,
        "sample_step": step,
    }


# ---------------------------------------------------------------------------
# glTF / GLB skeletal animation preview
# ---------------------------------------------------------------------------

_COMPONENT_FORMAT = {
    5120: ("b", 1),
    5121: ("B", 1),
    5122: ("h", 2),
    5123: ("H", 2),
    5125: ("I", 4),
    5126: ("f", 4),
}
_TYPE_COMPONENTS = {
    "SCALAR": 1,
    "VEC2": 2,
    "VEC3": 3,
    "VEC4": 4,
    "MAT2": 4,
    "MAT3": 9,
    "MAT4": 16,
}
_GLB_JSON_CHUNK = 0x4E4F534A
_GLB_BIN_CHUNK = 0x004E4942


def _m4_identity():
    return [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _m4_mul(a, b):
    return [
        [sum(a[row][k] * b[k][col] for k in range(4)) for col in range(4)]
        for row in range(4)
    ]


def _m4_from_gltf(values: Sequence[float]):
    # glTF stores matrices column-major.
    return [[float(values[col * 4 + row]) for col in range(4)] for row in range(4)]


def _quat_matrix(quaternion: Sequence[float]):
    x, y, z, w = (float(quaternion[i]) for i in range(4))
    length = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / length, y / length, z / length, w / length
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    xw, yw, zw = x * w, y * w, z * w
    return [
        [1.0 - 2.0 * (yy + zz), 2.0 * (xy - zw), 2.0 * (xz + yw), 0.0],
        [2.0 * (xy + zw), 1.0 - 2.0 * (xx + zz), 2.0 * (yz - xw), 0.0],
        [2.0 * (xz - yw), 2.0 * (yz + xw), 1.0 - 2.0 * (xx + yy), 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _m4_trs(translation, rotation, scale):
    matrix = _quat_matrix(rotation)
    scale = (float(scale[0]), float(scale[1]), float(scale[2]))
    for row in range(3):
        for col in range(3):
            matrix[row][col] *= scale[col]
    matrix[0][3] = float(translation[0])
    matrix[1][3] = float(translation[1])
    matrix[2][3] = float(translation[2])
    return matrix


def _gltf_buffer(path: Path, uri: str) -> bytes:
    if uri.startswith("data:"):
        try:
            _, encoded = uri.split(",", 1)
            return base64.b64decode(encoded)
        except (ValueError, TypeError):
            return b""
    base = path.parent.resolve()
    candidate = (base / uri).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return b""
    try:
        return candidate.read_bytes()
    except OSError:
        return b""


def _read_gltf_container(path: Path):
    """Return (document, buffers, format) or (None, [], '')."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None, [], ""
    if len(raw) > MAX_BYTES:
        return None, [], ""
    if raw[:4] == b"glTF":
        try:
            version, total = struct.unpack_from("<II", raw, 4)
            if version != 2 or total > len(raw):
                return None, [], ""
            offset = 12
            document = None
            binary = b""
            while offset + 8 <= total:
                chunk_length, chunk_type = struct.unpack_from("<II", raw, offset)
                offset += 8
                chunk = raw[offset : offset + chunk_length]
                offset += chunk_length
                if chunk_type == _GLB_JSON_CHUNK and document is None:
                    if chunk_length > 24 * 1024 * 1024:
                        return None, [], ""
                    document = json.loads(chunk.decode("utf-8", "replace"))
                elif chunk_type == _GLB_BIN_CHUNK:
                    binary = chunk
            if not isinstance(document, dict):
                return None, [], ""
            buffers: List[bytes] = []
            for index, item in enumerate(document.get("buffers") or []):
                uri = item.get("uri") if isinstance(item, dict) else None
                if not uri and index == 0:
                    buffers.append(binary)
                elif isinstance(uri, str):
                    buffers.append(_gltf_buffer(path, uri))
                else:
                    buffers.append(b"")
            return document, buffers, "GLB"
        except (ValueError, struct.error, UnicodeDecodeError):
            return None, [], ""
    try:
        document = json.loads(raw.decode("utf-8", "replace"))
    except (UnicodeDecodeError, ValueError):
        return None, [], ""
    if not isinstance(document, dict):
        return None, [], ""
    buffers = []
    for item in document.get("buffers") or []:
        uri = item.get("uri") if isinstance(item, dict) else None
        buffers.append(_gltf_buffer(path, uri) if isinstance(uri, str) else b"")
    return document, buffers, "GLTF"


def _gltf_accessor(document, buffers, index: int):
    accessors = document.get("accessors") or []
    views = document.get("bufferViews") or []
    if not isinstance(index, int) or index < 0 or index >= len(accessors):
        return []
    accessor = accessors[index]
    view_index = accessor.get("bufferView")
    if not isinstance(view_index, int) or view_index < 0 or view_index >= len(views):
        return []
    view = views[view_index]
    buffer_index = view.get("buffer")
    if not isinstance(buffer_index, int) or buffer_index < 0 or buffer_index >= len(buffers):
        return []
    data = buffers[buffer_index]
    component = accessor.get("componentType")
    kind = accessor.get("type")
    if component not in _COMPONENT_FORMAT or kind not in _TYPE_COMPONENTS:
        return []
    fmt, size = _COMPONENT_FORMAT[component]
    components = _TYPE_COMPONENTS[kind]
    count = int(accessor.get("count") or 0)
    start = int(view.get("byteOffset") or 0) + int(accessor.get("byteOffset") or 0)
    stride = int(view.get("byteStride") or (size * components))
    if count <= 0 or stride < size * components:
        return []
    if start < 0 or start + stride * (count - 1) + size * components > len(data):
        return []
    unpack = struct.Struct("<" + fmt * components).unpack_from
    values = []
    for i in range(count):
        item = unpack(data, start + stride * i)
        values.append(item[0] if components == 1 else item)
    return values


def _quat_slerp(a: Sequence[float], b: Sequence[float], t: float):
    ax, ay, az, aw = (float(a[i]) for i in range(4))
    bx, by, bz, bw = (float(b[i]) for i in range(4))
    dot = ax * bx + ay * by + az * bz + aw * bw
    if dot < 0.0:
        bx, by, bz, bw = -bx, -by, -bz, -bw
        dot = -dot
    if dot > 0.9995:
        values = [ax + (bx - ax) * t, ay + (by - ay) * t, az + (bz - az) * t, aw + (bw - aw) * t]
    else:
        theta = math.acos(max(-1.0, min(1.0, dot)))
        sin_theta = math.sin(theta)
        if sin_theta < 1e-8:
            return a
        wa = math.sin((1.0 - t) * theta) / sin_theta
        wb = math.sin(t * theta) / sin_theta
        values = [ax * wa + bx * wb, ay * wa + by * wb, az * wa + bz * wb, aw * wa + bw * wb]
    length = math.sqrt(sum(value * value for value in values)) or 1.0
    return tuple(value / length for value in values)


def _channel_value(channel, time_value: float):
    times = channel["times"]
    values = channel["values"]
    if not times or not values:
        return None
    if time_value <= times[0]:
        return values[0]
    if time_value >= times[-1]:
        return values[-1]
    index = bisect.bisect_right(times, time_value) - 1
    span = times[index + 1] - times[index]
    alpha = 0.0 if span <= 1e-9 else (time_value - times[index]) / span
    if channel.get("interpolation") == "STEP":
        alpha = 0.0
    left, right = values[index], values[index + 1]
    if channel["path"] == "rotation":
        return _quat_slerp(left, right, alpha)
    return tuple(float(left[i]) + (float(right[i]) - float(left[i])) * alpha for i in range(len(left)))


def _gltf_animation_channels(document, buffers, animation) -> List[Dict[str, object]]:
    samplers = animation.get("samplers") or []
    result: List[Dict[str, object]] = []
    for channel in animation.get("channels") or []:
        target = channel.get("target") or {}
        node = target.get("node")
        path = target.get("path")
        sampler_index = channel.get("sampler")
        if not isinstance(node, int) or path not in ("translation", "rotation", "scale"):
            continue
        if not isinstance(sampler_index, int) or sampler_index < 0 or sampler_index >= len(samplers):
            continue
        sampler = samplers[sampler_index]
        times = _gltf_accessor(document, buffers, sampler.get("input"))
        values = _gltf_accessor(document, buffers, sampler.get("output"))
        if not times or not values:
            continue
        if sampler.get("interpolation") == "CUBICSPLINE":
            values = values[1::3]
        pairs = sorted((float(t), value) for t, value in zip(times, values) if isinstance(t, (int, float)))
        if len(pairs) < 1:
            continue
        clean_times = [pair[0] for pair in pairs]
        clean_values = [pair[1] for pair in pairs]
        if path == "rotation":
            clean_values = [tuple(value) for value in clean_values if len(value) == 4]
            clean_times = clean_times[: len(clean_values)]
        if not clean_values:
            continue
        result.append(
            {
                "node": node,
                "path": path,
                "times": clean_times,
                "values": clean_values,
                "interpolation": sampler.get("interpolation") or "LINEAR",
            }
        )
    return result


def _normalise_sequence(frames: List[List[Tuple[float, float, float]]]) -> List[List[Tuple[float, float]]]:
    points = [point for frame in frames for point in frame]
    if not points:
        return []
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    cx = (min(xs) + max(xs)) / 2.0
    cy = (min(ys) + max(ys)) / 2.0
    cz = (min(zs) + max(zs)) / 2.0
    span = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs), 1e-6)
    scale = 2.0 / span
    projected = []
    for frame in frames:
        row = []
        for x, y, z in frame:
            x = (x - cx) * scale
            y = (y - cy) * scale
            z = (z - cz) * scale
            row.append(((x - z) * 0.8660254, (x + z) * 0.5 - y))
        projected.append(row)
    max_abs = max(max(abs(x), abs(y)) for row in projected for x, y in row) or 1.0
    return [[(round(x / max_abs, 4), round(y / max_abs, 4)) for x, y in row] for row in projected]


def load_gltf(path: Path | str) -> Optional[Dict[str, object]]:
    """Parse a skin + animation from a GLB or self-contained glTF.

    Only node/skin animation is evaluated.  Meshes, morph targets and IK are
    deliberately out of scope: this is a structure preview, not a renderer.
    """
    path = Path(path)
    document, buffers, fmt = _read_gltf_container(path)
    if not document:
        return None
    animations = document.get("animations") or []
    nodes = document.get("nodes") or []
    if not animations or not nodes:
        return None
    animation = next((item for item in animations if item.get("channels")), None)
    if not isinstance(animation, dict):
        return None
    channels = _gltf_animation_channels(document, buffers, animation)
    if not channels:
        return None
    times = max((channel["times"] for channel in channels), key=len)
    if not times:
        return None
    duration = max(0.0, times[-1] - times[0])
    frame_count = len(times)
    step = max(1, math.ceil(frame_count / MAX_PREVIEW_FRAMES))
    sample_indices = list(range(0, frame_count, step))
    if sample_indices[-1] != frame_count - 1:
        sample_indices.append(frame_count - 1)

    parent = [-1] * len(nodes)
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        for child in node.get("children") or []:
            if isinstance(child, int) and 0 <= child < len(nodes):
                parent[child] = index

    skin = (document.get("skins") or [None])[0]
    if isinstance(skin, dict) and isinstance(skin.get("joints"), list):
        joint_nodes = [index for index in skin["joints"] if isinstance(index, int) and 0 <= index < len(nodes)]
    else:
        animated = {int(channel["node"]) for channel in channels}
        expanded = set(animated)
        for index in animated:
            cursor = parent[index]
            while cursor >= 0:
                expanded.add(cursor)
                cursor = parent[cursor]
        joint_nodes = sorted(expanded)
    joint_nodes = list(dict.fromkeys(joint_nodes))
    if len(joint_nodes) < 2:
        return None
    joint_index = {node: index for index, node in enumerate(joint_nodes)}

    base_local = []
    for node in nodes:
        if not isinstance(node, dict):
            base_local.append(_m4_identity())
            continue
        if isinstance(node.get("matrix"), list) and len(node["matrix"]) == 16:
            base_local.append(_m4_from_gltf(node["matrix"]))
        else:
            base_local.append(
                _m4_trs(
                    node.get("translation") or (0.0, 0.0, 0.0),
                    node.get("rotation") or (0.0, 0.0, 0.0, 1.0),
                    node.get("scale") or (1.0, 1.0, 1.0),
                )
            )

    by_node: Dict[int, List[Dict[str, object]]] = {}
    for channel in channels:
        by_node.setdefault(int(channel["node"]), []).append(channel)

    raw_frames: List[List[Tuple[float, float, float]]] = []
    for sample_index in sample_indices:
        time_value = times[sample_index] - times[0]
        local = [list(matrix) for matrix in base_local]
        for node_index, node_channels in by_node.items():
            if node_index >= len(local):
                continue
            node = nodes[node_index] if isinstance(nodes[node_index], dict) else {}
            translation = list(node.get("translation") or (0.0, 0.0, 0.0))
            rotation = tuple(node.get("rotation") or (0.0, 0.0, 0.0, 1.0))
            scale = list(node.get("scale") or (1.0, 1.0, 1.0))
            for channel in node_channels:
                value = _channel_value(channel, time_value)
                if value is None:
                    continue
                if channel["path"] == "translation":
                    translation = list(value)
                elif channel["path"] == "rotation":
                    rotation = tuple(value)
                else:
                    scale = list(value)
            local[node_index] = _m4_trs(translation, rotation, scale)

        world_cache: Dict[int, list] = {}

        def world_matrix(index: int):
            if index in world_cache:
                return world_cache[index]
            node_parent = parent[index]
            if node_parent < 0:
                result = local[index]
            else:
                result = _m4_mul(world_matrix(node_parent), local[index])
            world_cache[index] = result
            return result

        frame = []
        for node_index in joint_nodes:
            matrix = world_matrix(node_index)
            frame.append((matrix[0][3], matrix[1][3], matrix[2][3]))
        raw_frames.append(frame)

    edges = []
    for node_index in joint_nodes:
        ancestor = parent[node_index]
        while ancestor >= 0 and ancestor not in joint_index:
            ancestor = parent[ancestor]
        if ancestor in joint_index:
            edges.append([joint_index[ancestor], joint_index[node_index]])

    frames = _normalise_sequence(raw_frames)
    if not frames:
        return None
    return {
        "kind": "gltf",
        "format": fmt,
        "joints": [str((nodes[index] or {}).get("name") or f"Node {index}") for index in joint_nodes],
        "edges": edges,
        "frames": frames,
        "frame_count": frame_count,
        "preview_frames": len(frames),
        "fps": round((frame_count - 1) / duration, 3) if duration > 0 else 0,
        "duration": round(duration, 3),
        "sample_step": step,
        "animation_name": str(animation.get("name") or ""),
        "animation_names": [str(item.get("name") or f"动作 {index + 1}") for index, item in enumerate(animations)],
    }


# ---------------------------------------------------------------------------
# FBX skeletal animation preview
# ---------------------------------------------------------------------------

_FBX_MAGIC = b"Kaydara FBX Binary  \x00\x1a\x00"
_FBX_TICKS_PER_SECOND = 46186158000.0


class _FbxNode:
    __slots__ = ("name", "props", "children")

    def __init__(self, name: str, props: List[object], children: List["_FbxNode"]):
        self.name = name
        self.props = props
        self.children = children


def _fbx_read_array(raw: bytes, offset: int, fmt: str, size: int):
    if offset + 12 > len(raw):
        raise ValueError("truncated FBX array")
    count, encoding, compressed = struct.unpack_from("<III", raw, offset)
    offset += 12
    if count > 20_000_000:
        raise ValueError("FBX array too large")
    length = count * size
    if encoding == 1:
        if compressed <= 0 or offset + compressed > len(raw):
            raise ValueError("truncated FBX compressed array")
        data = zlib.decompress(raw[offset : offset + compressed])
        offset += compressed
        if len(data) < length:
            raise ValueError("short FBX array")
        data = data[:length]
    else:
        if offset + length > len(raw):
            raise ValueError("truncated FBX array")
        data = raw[offset : offset + length]
        offset += length
    if count == 0:
        return [], offset
    return list(struct.unpack_from("<" + fmt * count, data, 0)), offset


def _fbx_read_property(raw: bytes, offset: int):
    if offset >= len(raw):
        raise ValueError("truncated FBX property")
    kind = chr(raw[offset])
    offset += 1
    if kind == "Y":
        return struct.unpack_from("<h", raw, offset)[0], offset + 2
    if kind == "C":
        return bool(raw[offset]), offset + 1
    if kind == "I":
        return struct.unpack_from("<i", raw, offset)[0], offset + 4
    if kind == "F":
        return struct.unpack_from("<f", raw, offset)[0], offset + 4
    if kind == "D":
        return struct.unpack_from("<d", raw, offset)[0], offset + 8
    if kind == "L":
        return struct.unpack_from("<q", raw, offset)[0], offset + 8
    if kind in ("S", "R"):
        length = struct.unpack_from("<I", raw, offset)[0]
        offset += 4
        if offset + length > len(raw):
            raise ValueError("truncated FBX string")
        data = raw[offset : offset + length]
        offset += length
        if kind == "R":
            return data, offset
        return data.decode("utf-8", "replace"), offset
    if kind in ("f", "d", "l", "i", "b"):
        fmt, size = {
            "f": ("f", 4),
            "d": ("d", 8),
            "l": ("q", 8),
            "i": ("i", 4),
            "b": ("B", 1),
        }[kind]
        return _fbx_read_array(raw, offset, fmt, size)
    raise ValueError(f"unsupported FBX property type {kind}")


def _fbx_read_node(raw: bytes, offset: int, wide: bool):
    header = 25 if wide else 13
    if offset + header > len(raw):
        return None, offset
    if wide:
        end, prop_count, prop_len = struct.unpack_from("<QQQ", raw, offset)
        offset += 24
    else:
        end, prop_count, prop_len = struct.unpack_from("<III", raw, offset)
        offset += 12
    name_len = raw[offset]
    offset += 1
    if end == 0 and prop_count == 0 and prop_len == 0 and name_len == 0:
        return None, offset
    if end <= offset or end > len(raw) or name_len == 0 or name_len > 255:
        raise ValueError("invalid FBX node")
    name = raw[offset : offset + name_len].decode("utf-8", "replace")
    offset += name_len
    props: List[object] = []
    for _ in range(min(int(prop_count), 100_000)):
        value, offset = _fbx_read_property(raw, offset)
        props.append(value)
    children: List[_FbxNode] = []
    while offset < end:
        child, offset = _fbx_read_node(raw, offset, wide)
        if child is None:
            break
        children.append(child)
    return _FbxNode(name, props, children), end


def _fbx_ascii_value(token: str) -> object:
    token = token.strip()
    if token.startswith('"'):
        try:
            return json.loads(token)
        except ValueError:
            return token.strip('"')
    try:
        return int(token)
    except ValueError:
        try:
            return float(token)
        except ValueError:
            return token


def _fbx_ascii_header(line: str) -> Tuple[str, List[object]]:
    name, _, rest = line.partition(":")
    props = [
        _fbx_ascii_value(token)
        for token in re.findall(r'"(?:\\.|[^"\\])*"|[^,\s{}]+', rest)
    ]
    return name.strip(), props


def _fbx_ascii_document(text: str) -> Optional[List[_FbxNode]]:
    """Parse the line-oriented ASCII flavour of FBX 7.x.

    Autodesk's ASCII writer is much simpler than the binary format; a small
    node tree parser is enough for the model/curve nodes we need.  Array
    properties (``KeyTime: *21 { a: ... }``) become one flat property list.
    """
    lines: List[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(";"):
            continue
        # Comments after values are common; keep quoted semicolons intact.
        in_quote = False
        escaped = False
        cut = len(line)
        for index, char in enumerate(line):
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_quote = not in_quote
            elif char == ";" and not in_quote:
                cut = index
                break
        line = line[:cut].strip()
        if line:
            lines.append(line)

    def parse_block(index: int) -> Tuple[List[_FbxNode], int]:
        nodes: List[_FbxNode] = []
        while index < len(lines):
            line = lines[index]
            index += 1
            if line == "}":
                return nodes, index
            if line.endswith("{"):
                name, props = _fbx_ascii_header(line[:-1].strip())
                children, index = parse_block(index)
                if props and isinstance(props[0], str) and props[0].startswith("*"):
                    values: List[object] = []
                    for child in children:
                        values.extend(child.props)
                    nodes.append(_FbxNode(name, values, []))
                else:
                    nodes.append(_FbxNode(name, props, children))
                continue
            if line.startswith("}"):
                return nodes, index
            name, props = _fbx_ascii_header(line)
            nodes.append(_FbxNode(name, props, []))
        return nodes, index

    try:
        nodes, _ = parse_block(0)
        return nodes or None
    except (ValueError, IndexError):
        return None


def _fbx_document(path: Path) -> Optional[List[_FbxNode]]:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if not raw.startswith(_FBX_MAGIC):
        head = raw[:512].lstrip()
        if head.startswith(b";") or head.startswith(b"FBXHeaderExtension"):
            try:
                return _fbx_ascii_document(raw.decode("utf-8-sig", "replace"))
            except (UnicodeDecodeError, ValueError):
                return None
        return None
    if len(raw) < 27:
        return None
    if len(raw) > MAX_BYTES:
        return None
    version = struct.unpack_from("<I", raw, 23)[0]
    wide = version >= 7500
    offset = 27
    nodes: List[_FbxNode] = []
    try:
        while offset < len(raw):
            node, offset = _fbx_read_node(raw, offset, wide)
            if node is None:
                break
            nodes.append(node)
    except (ValueError, struct.error, IndexError):
        return None
    return nodes


def _fbx_child(node: Optional[_FbxNode], name: str) -> Optional[_FbxNode]:
    if not node:
        return None
    for child in node.children:
        if child.name == name:
            return child
    return None


def _fbx_props(node: _FbxNode) -> Dict[str, Tuple[float, float, float]]:
    result: Dict[str, Tuple[float, float, float]] = {}
    properties = _fbx_child(node, "Properties70")
    if not properties:
        return result
    for item in properties.children:
        if item.name != "P" or len(item.props) < 7:
            continue
        name = str(item.props[0])
        values = [value for value in item.props[4:] if isinstance(value, (int, float))]
        if len(values) >= 3:
            result[name] = (float(values[-3]), float(values[-2]), float(values[-1]))
    return result


def _fbx_rotation_matrix(rx: float, ry: float, rz: float):
    return _mat_mul(
        _axis_matrix("Z", math.radians(rz)),
        _mat_mul(_axis_matrix("Y", math.radians(ry)), _axis_matrix("X", math.radians(rx))),
    )


def _fbx_curve(curve: _FbxNode) -> Optional[Dict[str, object]]:
    times_node = _fbx_child(curve, "KeyTime")
    values_node = _fbx_child(curve, "KeyValueFloat") or _fbx_child(curve, "KeyValueDouble")
    if not times_node or not values_node:
        return None
    def numbers(properties) -> List[float]:
        result: List[float] = []
        for value in properties:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                result.append(float(value))
            elif isinstance(value, (list, tuple)):
                result.extend(float(item) for item in value if isinstance(item, (int, float)))
        return result

    times = [value / _FBX_TICKS_PER_SECOND for value in numbers(times_node.props)]
    values = numbers(values_node.props)
    count = min(len(times), len(values))
    if count <= 0:
        return None
    pairs = sorted(zip(times[:count], values[:count]))
    return {
        "times": [pair[0] for pair in pairs],
        "values": [pair[1] for pair in pairs],
    }


def _fbx_channel_value(channel: Dict[str, object], time_value: float) -> Optional[float]:
    times = channel["times"]
    values = channel["values"]
    if not times:
        return None
    if time_value <= times[0]:
        return float(values[0])
    if time_value >= times[-1]:
        return float(values[-1])
    index = bisect.bisect_right(times, time_value) - 1
    span = times[index + 1] - times[index]
    ratio = 0.0 if span <= 1e-9 else (time_value - times[index]) / span
    return float(values[index]) + (float(values[index + 1]) - float(values[index])) * ratio


def load_fbx(path: Path | str) -> Optional[Dict[str, object]]:
    """Read a binary FBX skeleton and its first animation take.

    FBX is a large format; this intentionally only extracts the bone models,
    their local rest transforms and the ``Lcl Translation/Rotation/Scaling``
    animation curves.  Skinning, constraints, IK and morph targets are ignored.
    """
    path = Path(path)
    document = _fbx_document(path)
    if not document:
        return None
    objects_node = next((node for node in document if node.name == "Objects"), None)
    connections_node = next((node for node in document if node.name == "Connections"), None)
    if not objects_node or not connections_node:
        return None

    objects: Dict[int, _FbxNode] = {}
    object_meta: Dict[int, Dict[str, str]] = {}
    for node in objects_node.children:
        if not node.props or not isinstance(node.props[0], int):
            continue
        object_id = int(node.props[0])
        name = str(node.props[1]) if len(node.props) > 1 else ""
        class_name = str(node.props[2]) if len(node.props) > 2 else ""
        if not class_name:
            class_name = node.name
        objects[object_id] = node
        object_meta[object_id] = {"name": name, "class": class_name}

    connections: List[Tuple[str, int, int, str]] = []
    for node in connections_node.children:
        if node.name != "C" or len(node.props) < 3:
            continue
        kind = str(node.props[0])
        child = node.props[1]
        parent = node.props[2]
        prop = str(node.props[3]) if len(node.props) > 3 else ""
        if isinstance(child, int) and isinstance(parent, int):
            connections.append((kind, child, parent, prop))

    bone_ids = [
        object_id
        for object_id, meta in object_meta.items()
        if objects[object_id].name == "Model" and meta["class"] in ("LimbNode", "Root")
    ]
    if len(bone_ids) < 2:
        bone_ids = [
            object_id
            for object_id, meta in object_meta.items()
            if objects[object_id].name == "Model" and meta["class"] == "LimbNode"
        ]
    if len(bone_ids) < 2:
        return None

    connections_by_child: Dict[int, Tuple[int, str]] = {}
    for kind, child, parent, prop in connections:
        if kind == "OO" and child in bone_ids and parent in bone_ids:
            connections_by_child.setdefault(child, (parent, prop))

    def depth(object_id: int, seen: Optional[set] = None) -> int:
        seen = seen or set()
        if object_id in seen:
            return 0
        seen.add(object_id)
        parent_pair = connections_by_child.get(object_id)
        return 0 if not parent_pair else 1 + depth(parent_pair[0], seen)

    ordered = sorted(bone_ids, key=lambda object_id: (depth(object_id), object_meta[object_id]["name"]))
    bone_index = {object_id: index for index, object_id in enumerate(ordered)}
    joints = [object_meta[object_id]["name"].split("::")[-1] for object_id in ordered]
    parents = []
    for object_id in ordered:
        parent_pair = connections_by_child.get(object_id)
        parents.append(bone_index.get(parent_pair[0], -1) if parent_pair else -1)

    rest_translation = []
    rest_rotation = []
    rest_scale = []
    rest_euler_rotation = []
    pre_rotation = []
    post_rotation = []
    for object_id in ordered:
        props = _fbx_props(objects[object_id])
        rest_translation.append(props.get("Lcl Translation", (0.0, 0.0, 0.0)))
        rotation = props.get("Lcl Rotation", (0.0, 0.0, 0.0))
        pre = props.get("PreRotation", (0.0, 0.0, 0.0))
        post = props.get("PostRotation", (0.0, 0.0, 0.0))
        pre_matrix = _fbx_rotation_matrix(*pre)
        post_matrix = _fbx_rotation_matrix(*post)
        rest_euler_rotation.append(tuple(float(value) for value in rotation))
        pre_rotation.append(pre_matrix)
        post_rotation.append(post_matrix)
        rest_rotation.append(
            _mat_mul(pre_matrix, _mat_mul(_fbx_rotation_matrix(*rotation), post_matrix))
        )
        rest_scale.append(props.get("Lcl Scaling", (1.0, 1.0, 1.0)))

    curve_nodes = {
        object_id: node
        for object_id, node in objects.items()
        if object_meta[object_id]["class"] == "AnimationCurveNode"
    }
    model_for_curve_node: Dict[int, Tuple[int, str]] = {}
    for kind, child, parent, prop in connections:
        if kind == "OP" and child in curve_nodes and parent in bone_index:
            model_for_curve_node[child] = (parent, prop)

    channels: Dict[int, Dict[str, Dict[str, Dict[str, object]]]] = {}
    for child, (model_id, prop) in model_for_curve_node.items():
        if prop not in ("Lcl Translation", "Lcl Rotation", "Lcl Scaling"):
            continue
        for kind, curve_id, parent, axis_prop in connections:
            if kind != "OP" or parent != child or curve_id not in objects:
                continue
            if object_meta[curve_id]["class"] != "AnimationCurve":
                continue
            axis = axis_prop.split("|")[-1].upper()
            if axis not in ("X", "Y", "Z"):
                continue
            data = _fbx_curve(objects[curve_id])
            if data:
                channels.setdefault(model_id, {}).setdefault(prop, {})[axis] = data

    stacks = [
        object_meta[object_id]["name"].split("::")[-1]
        for object_id in objects
        if object_meta[object_id]["class"] == "AnimationStack"
    ]
    all_times = [
        time
        for model_channels in channels.values()
        for prop_channels in model_channels.values()
        for channel in prop_channels.values()
        for time in channel["times"]
    ]
    if not all_times:
        return None
    start_time = min(all_times)
    end_time = max(all_times)
    duration = max(0.0, end_time - start_time)
    fps = 30.0
    frame_count = max(2, int(round(duration * fps)) + 1)
    step = max(1, math.ceil(frame_count / MAX_PREVIEW_FRAMES))
    sample_indices = list(range(0, frame_count, step))
    if sample_indices[-1] != frame_count - 1:
        sample_indices.append(frame_count - 1)

    raw_frames: List[List[Tuple[float, float, float]]] = []
    for sample_index in sample_indices:
        time_value = start_time + (sample_index / fps if fps else 0.0)
        local_positions = []
        local_rotations = []
        local_scales = []
        for model_id in ordered:
            bone = bone_index[model_id]
            translation = list(rest_translation[bone])
            rotation = rest_rotation[bone]
            scale = list(rest_scale[bone])
            euler_rotation = list(rest_euler_rotation[bone])
            props = channels.get(model_id, {})
            rotation_animated = False
            for prop, axes in props.items():
                values = {}
                for axis, channel in axes.items():
                    value = _fbx_channel_value(channel, time_value)
                    if value is not None:
                        values[axis] = value
                if not values:
                    continue
                if prop == "Lcl Translation":
                    for axis, value in values.items():
                        translation["XYZ".index(axis)] = value
                elif prop == "Lcl Scaling":
                    for axis, value in values.items():
                        scale["XYZ".index(axis)] = value
                elif prop == "Lcl Rotation":
                    for axis, value in values.items():
                        euler_rotation["XYZ".index(axis)] = value
                    rotation_animated = True
            if rotation_animated:
                rotation = _mat_mul(
                    pre_rotation[bone],
                    _mat_mul(_fbx_rotation_matrix(*euler_rotation), post_rotation[bone]),
                )
            local_positions.append(tuple(translation))
            local_rotations.append(rotation)
            local_scales.append(tuple(scale))

        world_positions: List[Tuple[float, float, float]] = []
        world_rotations: List[Tuple] = []
        world_scales: List[Tuple[float, float, float]] = []
        for index, parent in enumerate(parents):
            local_position = local_positions[index]
            if parent < 0:
                world_positions.append(local_position)
                world_rotations.append(local_rotations[index])
                world_scales.append(local_scales[index])
                continue
            parent_scale = world_scales[parent]
            scaled = (
                local_position[0] * parent_scale[0],
                local_position[1] * parent_scale[1],
                local_position[2] * parent_scale[2],
            )
            rotated = _apply(world_rotations[parent], scaled)
            world_positions.append(
                (
                    world_positions[parent][0] + rotated[0],
                    world_positions[parent][1] + rotated[1],
                    world_positions[parent][2] + rotated[2],
                )
            )
            world_rotations.append(_mat_mul(world_rotations[parent], local_rotations[index]))
            world_scales.append(
                (
                    world_scales[parent][0] * local_scales[index][0],
                    world_scales[parent][1] * local_scales[index][1],
                    world_scales[parent][2] * local_scales[index][2],
                )
            )
        raw_frames.append(world_positions)

    frames = _normalise_sequence(raw_frames)
    if not frames:
        return None
    return {
        "kind": "fbx",
        "format": "FBX",
        "joints": joints,
        "edges": [[parent, index] for index, parent in enumerate(parents) if parent >= 0],
        "frames": frames,
        "frame_count": frame_count,
        "preview_frames": len(frames),
        "fps": fps,
        "duration": round(duration, 3),
        "sample_step": step,
        "animation_name": stacks[0] if stacks else "",
        "animation_names": stacks,
    }


def load_motion(path: Path | str) -> Optional[Dict[str, object]]:
    suffix = Path(path).suffix.casefold()
    if suffix == ".bvh":
        return load_bvh(path)
    if suffix in (".glb", ".gltf"):
        return load_gltf(path)
    if suffix == ".fbx":
        return load_fbx(path)
    return None


def motion_info(path: Path | str) -> Optional[Dict[str, object]]:
    """Return a short, cached-friendly description for motion files."""
    suffix = Path(path).suffix.casefold()
    data = load_motion(path) if suffix in (".bvh", ".glb", ".gltf", ".fbx") else None
    if not data:
        return None
    keys = ("kind", "format", "frame_count", "fps", "duration", "animation_name")
    return {key: data[key] for key in keys if key in data}
