"""Cheap, dependency-free inspection of common 3D and texture files.

Nothing in here renders a model.  The goal is to give the library useful
facts (mesh/animation counts, image dimensions, BVH bone count) without
turning into a half-finished 3D engine.
"""

from __future__ import annotations

import json
import math
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


MAX_JSON_BYTES = 24 * 1024 * 1024
MAX_TEXT_BYTES = 32 * 1024 * 1024


@dataclass
class AssetProbe:
    format: str = ""
    width: int = 0
    height: int = 0
    stats: Dict[str, Any] = field(default_factory=dict)
    note: str = ""


def _as_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _safe_stats(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Extract the few facts that are meaningful in a library table."""
    meshes = doc.get("meshes") if isinstance(doc.get("meshes"), list) else []
    nodes = doc.get("nodes") if isinstance(doc.get("nodes"), list) else []
    materials = doc.get("materials") if isinstance(doc.get("materials"), list) else []
    animations = doc.get("animations") if isinstance(doc.get("animations"), list) else []
    skins = doc.get("skins") if isinstance(doc.get("skins"), list) else []
    textures = doc.get("textures") if isinstance(doc.get("textures"), list) else []
    images = doc.get("images") if isinstance(doc.get("images"), list) else []
    accessors = doc.get("accessors") if isinstance(doc.get("accessors"), list) else []

    vertices = 0
    faces = 0
    for mesh in meshes:
        if not isinstance(mesh, dict):
            continue
        for primitive in mesh.get("primitives") or []:
            if not isinstance(primitive, dict):
                continue
            attributes = primitive.get("attributes") or {}
            position_index = attributes.get("POSITION")
            position = accessors[position_index] if isinstance(position_index, int) and 0 <= position_index < len(accessors) else None
            if isinstance(position, dict):
                vertices += _as_int(position.get("count"))
            indices_index = primitive.get("indices")
            indices = accessors[indices_index] if isinstance(indices_index, int) and 0 <= indices_index < len(accessors) else None
            if isinstance(indices, dict):
                faces += _as_int(indices.get("count")) // 3
            elif isinstance(position, dict):
                faces += _as_int(position.get("count")) // 3

    bones = 0
    for skin in skins:
        if isinstance(skin, dict):
            joints = skin.get("joints")
            if isinstance(joints, list):
                bones = max(bones, len(joints))

    duration = 0.0
    names: List[str] = []
    for animation in animations:
        if not isinstance(animation, dict):
            continue
        name = str(animation.get("name") or "").strip()
        if name and len(names) < 3:
            names.append(name)
        for channel in animation.get("channels") or []:
            if not isinstance(channel, dict):
                continue
            sampler_index = channel.get("sampler")
            samplers = animation.get("samplers") or []
            if not isinstance(sampler_index, int) or not 0 <= sampler_index < len(samplers):
                continue
            sampler = samplers[sampler_index]
            if not isinstance(sampler, dict):
                continue
            input_index = sampler.get("input")
            accessor = accessors[input_index] if isinstance(input_index, int) and 0 <= input_index < len(accessors) else None
            if not isinstance(accessor, dict):
                continue
            maximum = accessor.get("max")
            if isinstance(maximum, list) and maximum:
                duration = max(duration, _as_float(maximum[0]))

    return {
        "meshes": len(meshes),
        "nodes": len(nodes),
        "materials": len(materials),
        "animations": len(animations),
        "skins": len(skins),
        "textures": len(textures),
        "images": len(images),
        "bones": bones,
        "vertices": vertices,
        "faces": faces,
        "duration": round(duration, 3),
        "animation_names": " · ".join(names),
    }


def _read_glb_json(path: Path) -> Tuple[Optional[Dict[str, Any]], str]:
    try:
        with open(path, "rb") as handle:
            header = handle.read(12)
            if len(header) < 12 or header[:4] != b"glTF":
                return None, "不是有效的 GLB 文件"
            version = struct.unpack_from("<I", header, 4)[0]
            if version not in (1, 2):
                return None, f"不支持的 GLB 版本：{version}"
            total_length = struct.unpack_from("<I", header, 8)[0]
            offset = 12
            while offset + 8 <= total_length:
                handle.seek(offset)
                chunk_header = handle.read(8)
                if len(chunk_header) < 8:
                    break
                chunk_length, chunk_type = struct.unpack("<I4s", chunk_header)
                offset += 8
                if chunk_type == b"JSON":
                    if chunk_length > MAX_JSON_BYTES:
                        return None, "GLB 的 JSON 块过大，已跳过解析"
                    raw = handle.read(chunk_length)
                    try:
                        document = json.loads(raw.decode("utf-8", "replace"))
                    except ValueError:
                        return None, "GLB 的 JSON 块无法解析"
                    return document if isinstance(document, dict) else None, ""
                offset += chunk_length
    except (OSError, struct.error):
        return None, "无法读取 GLB 文件"
    return None, "GLB 中没有找到 JSON 块"


def _read_gltf_json(path: Path) -> Tuple[Optional[Dict[str, Any]], str]:
    try:
        with open(path, "rb") as handle:
            raw = handle.read(MAX_JSON_BYTES + 1)
        if len(raw) > MAX_JSON_BYTES:
            return None, "glTF JSON 过大，已跳过解析"
        document = json.loads(raw.decode("utf-8", "replace"))
        return document if isinstance(document, dict) else None, ""
    except (OSError, UnicodeDecodeError, ValueError):
        return None, "无法解析 glTF JSON"


def _png_size(data: bytes) -> Tuple[int, int]:
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack_from(">II", data, 16)
    return 0, 0


def _jpeg_size(data: bytes) -> Tuple[int, int]:
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return 0, 0
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        if marker in (0xD8, 0xD9):
            continue
        if index + 2 > len(data):
            break
        length = struct.unpack_from(">H", data, index)[0]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            if index + 7 <= len(data):
                height, width = struct.unpack_from(">HH", data, index + 3)
                return width, height
        if length < 2:
            break
        index += length
    return 0, 0


def _webp_size(data: bytes) -> Tuple[int, int]:
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return 0, 0
    kind = data[12:16]
    if kind == b"VP8X":
        width = 1 + int.from_bytes(data[24:27], "little")
        height = 1 + int.from_bytes(data[27:30], "little")
        return width, height
    if kind == b"VP8 " and len(data) >= 30:
        width = int.from_bytes(data[26:28], "little") & 0x3FFF
        height = int.from_bytes(data[28:30], "little") & 0x3FFF
        return width, height
    if kind == b"VP8L" and len(data) >= 25:
        bits = int.from_bytes(data[21:25], "little")
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
        return width, height
    return 0, 0


def _image_size(path: Path) -> Tuple[int, int]:
    try:
        with open(path, "rb") as handle:
            data = handle.read(256 * 1024)
    except OSError:
        return 0, 0
    png_width, png_height = _png_size(data)
    if png_width:
        return png_width, png_height
    jpeg_width, jpeg_height = _jpeg_size(data)
    if jpeg_width:
        return jpeg_width, jpeg_height
    webp_width, webp_height = _webp_size(data)
    if webp_width:
        return webp_width, webp_height
    if len(data) >= 10 and data[:3] == b"GIF":
        return struct.unpack_from("<HH", data, 6)
    if len(data) >= 26 and data[:4] == b"8BPS":
        height, width = struct.unpack_from(">II", data, 14)
        return width, height
    if len(data) >= 18 and data[:4] == b"DDS ":
        height, width = struct.unpack_from("<II", data, 12)
        return width, height
    # Uncompressed TGA: the first byte is usually 0/2/3/10/11, and the
    # dimensions live at bytes 12..16.  Do not trust arbitrary binary files.
    if len(data) >= 18 and data[1] in (0, 1, 2, 3, 9, 10, 11) and data[2] == 0:
        width, height = struct.unpack_from("<HH", data, 12)
        if width and height:
            return width, height
    return 0, 0


def _fbx_version(path: Path) -> str:
    try:
        with open(path, "rb") as handle:
            head = handle.read(64)
    except OSError:
        return ""
    if head.startswith(b"Kaydara FBX Binary") and len(head) >= 27:
        version = struct.unpack_from("<I", head, 23)[0]
        return f"{version // 1000}.{version % 1000}"
    if b"FBX" in head[:32]:
        return "ASCII"
    return ""


def _blender_version(path: Path) -> str:
    try:
        with open(path, "rb") as handle:
            head = handle.read(32)
    except OSError:
        return ""
    match = re.search(rb"BLENDER[-_]v?(\d{3})", head)
    if not match:
        return ""
    value = match.group(1).decode("ascii", "ignore")
    return f"{value[0]}.{value[1:]}"


def _bvh_stats(path: Path) -> Dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError:
        return {}
    text = raw[:MAX_TEXT_BYTES].decode("utf-8", "replace")
    joints = len(re.findall(r"(?im)^\s*(?:JOINT|ROOT)\s+", text))
    frames_match = re.search(r"(?im)^\s*Frames:\s*(\d+)", text)
    frame_time_match = re.search(r"(?im)^\s*Frame\s+Time:\s*([0-9.+\-eE]+)", text)
    frames = _as_int(frames_match.group(1)) if frames_match else 0
    frame_time = _as_float(frame_time_match.group(1)) if frame_time_match else 0.0
    return {
        "bones": joints,
        "frames": frames,
        "duration": round(frames * frame_time, 3),
    }


def _obj_stats(path: Path) -> Dict[str, Any]:
    try:
        with open(path, "rb") as handle:
            raw = handle.read(MAX_TEXT_BYTES)
    except OSError:
        return {}
    vertices = 0
    faces = 0
    objects = 0
    groups = 0
    for line in raw.splitlines():
        if line.startswith(b"v "):
            vertices += 1
        elif line.startswith(b"f "):
            faces += 1
        elif line.startswith(b"o "):
            objects += 1
        elif line.startswith(b"g "):
            groups += 1
    return {
        "vertices": vertices,
        "faces": faces,
        "objects": objects,
        "groups": groups,
    }


def _gltf_summary(stats: Dict[str, Any]) -> str:
    parts: List[str] = []
    if stats.get("meshes"):
        parts.append(f"{stats['meshes']} 网格")
    if stats.get("materials"):
        parts.append(f"{stats['materials']} 材质")
    if stats.get("animations"):
        parts.append(f"{stats['animations']} 动作")
    if stats.get("skins"):
        parts.append(f"{stats['skins']} 蒙皮")
    if stats.get("textures"):
        parts.append(f"{stats['textures']} 贴图")
    return " · ".join(parts)


def summarize(probe: AssetProbe) -> str:
    stats = probe.stats or {}
    parts: List[str] = []
    if probe.width and probe.height:
        parts.append(f"{probe.width}×{probe.height}")
    if probe.format in ("GLB", "GLTF"):
        summary = _gltf_summary(stats)
        if summary:
            parts.append(summary)
        elif stats.get("nodes"):
            parts.append(f"{stats['nodes']} 节点")
    elif probe.format == "OBJ":
        if stats.get("vertices"):
            parts.append(f"{stats['vertices']:,} 顶点")
        if stats.get("faces"):
            parts.append(f"{stats['faces']:,} 面")
    elif probe.format == "BVH":
        if stats.get("bones"):
            parts.append(f"{stats['bones']} 骨骼")
        if stats.get("frames"):
            parts.append(f"{stats['frames']} 帧")
    elif probe.format == "FBX" and stats.get("version"):
        parts.append(f"FBX {stats['version']}")
    elif probe.format in ("BLEND", "BLEND1") and stats.get("version"):
        parts.append(f"Blender {stats['version']}")
    return " · ".join(parts) or probe.note or "等待查看"


def probe_asset(path: Path) -> AssetProbe:
    """Read best-effort metadata; never raise for an awkward asset."""
    suffix = path.suffix.lower()
    fmt = suffix[1:].upper() if suffix else ""
    probe = AssetProbe(format=fmt)
    try:
        if fmt == "GLB":
            document, note = _read_glb_json(path)
            probe.note = note
            if document is not None:
                probe.stats = _safe_stats(document)
        elif fmt == "GLTF":
            document, note = _read_gltf_json(path)
            probe.note = note
            if document is not None:
                probe.stats = _safe_stats(document)
        elif fmt == "BVH":
            probe.stats = _bvh_stats(path)
        elif fmt == "OBJ":
            probe.stats = _obj_stats(path)
        elif fmt == "FBX":
            version = _fbx_version(path)
            if version:
                probe.stats = {"version": version}
        elif fmt in ("BLEND", "BLEND1"):
            version = _blender_version(path)
            if version:
                probe.stats = {"version": version}
        elif fmt in ("PNG", "JPG", "JPEG", "WEBP", "GIF", "PSD", "TGA", "DDS", "TIF", "TIFF"):
            width, height = _image_size(path)
            probe.width, probe.height = width, height
        if not probe.note and suffix in (".glb", ".gltf") and not probe.stats:
            probe.note = "没有读到结构信息"
    except (OSError, ValueError, struct.error):
        probe.note = "文件结构读取失败"
    return probe
