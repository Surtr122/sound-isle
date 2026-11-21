"""Library scanning, tags, favourites and rename orchestration."""

from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from . import metadata, probe
from .classify import (
    ANIMATION_SUBCATEGORIES,
    ANIMATION_SUBCATEGORY_BY_KEY,
    ASSET_CATEGORY_LIST,
    CATEGORY_LIST,
    SFX_SUBCATEGORIES,
    SFX_SUBCATEGORY_BY_KEY,
    classify_animation_subcategory,
    classify_asset,
    classify_sfx_subcategory,
    classify_track,
    legacy_asset_categories,
    legacy_categories,
)
from .config import library_state_path, read_json, write_json
from .rename import RenameError, apply_plan, build_plan, natural_key, validate_options


AUDIO_EXTENSIONS = {
    ".mp3",
    ".flac",
    ".wav",
    ".m4a",
    ".m4b",
    ".aac",
    ".ogg",
    ".oga",
    ".opus",
    ".aiff",
    ".aif",
}

ASSET_EXTENSIONS = {
    ".blend", ".blend1", ".ma", ".mb", ".max", ".c4d", ".uproject", ".uasset",
    ".umap", ".unity", ".prefab", ".asset", ".zpr", ".ztl", ".spp", ".sbsar",
    ".hip", ".hipnc", ".fcstd", ".nk", ".nuke",
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".tga", ".exr", ".hdr", ".psd",
    ".tif", ".tiff", ".dds", ".ktx", ".ktx2", ".mtl",
    ".bvh", ".anim", ".trk", ".clip",
    ".glb", ".gltf", ".fbx", ".obj", ".dae", ".3ds", ".stl", ".ply", ".usd",
    ".usda", ".usdc", ".usdz", ".abc", ".step", ".stp", ".igs", ".iges",
    ".x3d", ".wrl", ".vrm",
    ".zip", ".7z", ".rar", ".tar", ".gz",
    ".txt", ".md", ".pdf", ".doc", ".docx",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
SUPPORTED_EXTENSIONS = AUDIO_EXTENSIONS | ASSET_EXTENSIONS


def _subcategory_config(category_key: str):
    if category_key == "sfx":
        return SFX_SUBCATEGORIES, SFX_SUBCATEGORY_BY_KEY
    if category_key == "animation":
        return ANIMATION_SUBCATEGORIES, ANIMATION_SUBCATEGORY_BY_KEY
    return None, None


def _subcategory_payload(category_key: str, counts: Dict[str, int]) -> Optional[List[Dict[str, object]]]:
    items, _ = _subcategory_config(category_key)
    if not items:
        return None
    return [
        {
            "key": item["key"],
            "name": item["name"],
            "description": item["description"],
            "count": counts.get(item["key"], 0),
        }
        for item in items
    ]

_SKIP_DIRS = {
    ".git",
    ".svn",
    ".hg",
    "__pycache__",
    "node_modules",
    "@eadir",
    "$recycle.bin",
    "system volume information",
    ".trash",
    ".trashes",
}

_MAX_FILES = 20000
_MAX_TAGS_PER_TRACK = 30
_MAX_CUSTOM_CATEGORIES = 40
_CUSTOM_ACCENTS = (
    "#C65D3B", "#B08A45", "#4D7C67", "#4D7394",
    "#8A6FA8", "#AF6876", "#6F7D86", "#817F73",
)
_CATEGORY_NAME_RE = re.compile(r"^[\w\u3400-\u9fff][\w\u3400-\u9fff ·&+.\-/]{0,23}$")
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class LibraryError(Exception):
    """A user-facing library problem."""


def stable_id(rel_path: str) -> str:
    return hashlib.sha1(rel_path.encode("utf-8", "surrogatepass")).hexdigest()[:16]


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _modified_iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).astimezone().isoformat(timespec="seconds")


def _short_duration(seconds: object) -> str:
    try:
        total = int(round(float(seconds or 0)))
    except (TypeError, ValueError):
        return "未知"
    minutes, second = divmod(max(0, total), 60)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"{hours}:{minutes:02d}:{second:02d}"
    return f"{minutes}:{second:02d}"


def _file_digest(path: Path, size: int) -> str:
    digest = hashlib.sha1()
    digest.update(str(size).encode("ascii"))
    try:
        with path.open("rb") as handle:
            digest.update(handle.read(1024 * 1024))
    except OSError:
        return ""
    return digest.hexdigest()


def _duplicate_groups(tracks: Sequence[Dict[str, object]]) -> List[Dict[str, object]]:
    by_size: Dict[int, List[Dict[str, object]]] = {}
    for track in tracks:
        try:
            size = int(track.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        if size <= 0:
            continue
        by_size.setdefault(size, []).append(track)

    groups: List[Dict[str, object]] = []
    for size, candidates in by_size.items():
        if len(candidates) < 2 or len(candidates) > 200:
            continue
        buckets: Dict[str, List[Dict[str, object]]] = {}
        for track in candidates:
            digest = _file_digest(Path(str(track.get("_path", ""))), size)
            if digest:
                buckets.setdefault(digest, []).append(track)
        for digest, items in buckets.items():
            if len(items) < 2:
                continue
            groups.append(
                {
                    "digest": digest[:16],
                    "size": size,
                    "tracks": [
                        {
                            "id": item["id"],
                            "title": item.get("title") or item.get("filename"),
                            "rel_path": item.get("rel_path"),
                            "kind": item.get("kind"),
                        }
                        for item in items
                    ],
                }
            )
    groups.sort(key=lambda item: (-int(item["size"]), str(item["digest"])))
    return groups


def _clean_tag(value: object) -> str:
    if not isinstance(value, str):
        return ""
    value = value.replace("\x00", " ").strip()
    value = value.lstrip("#").strip()
    value = " ".join(value.split())
    if len(value) > 24:
        value = value[:24].rstrip()
    return value


def _clean_tags(values: object) -> List[str]:
    if not isinstance(values, (list, tuple, set)):
        return []
    result: List[str] = []
    seen: Set[str] = set()
    for value in values:
        tag = _clean_tag(value)
        key = tag.casefold()
        if tag and key not in seen:
            seen.add(key)
            result.append(tag)
        if len(result) >= _MAX_TAGS_PER_TRACK:
            break
    return result


def _read_meta_safe(path: Path) -> metadata.AudioMeta:
    try:
        return metadata.read_audio(path, want_cover=False)
    except Exception:
        return metadata.AudioMeta()


def _read_asset_safe(path: Path) -> probe.AssetProbe:
    try:
        return probe.probe_asset(path)
    except Exception:
        return probe.AssetProbe(format=path.suffix.lstrip(".").upper(), note="无法解析结构")


def _kind_for(suffix: str) -> Optional[str]:
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    if suffix in ASSET_EXTENSIONS:
        return "asset"
    return None


def _clean_category_name(value: object) -> str:
    if not isinstance(value, str):
        return ""
    name = " ".join(value.replace("\x00", " ").split()).strip()
    if len(name) > 24:
        name = name[:24].rstrip()
    return name


def _clean_category_key(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


class Library:
    def __init__(self, root: Path | str):
        raw_root = Path(root).expanduser()
        try:
            resolved = raw_root.resolve(strict=True)
        except OSError as exc:
            raise LibraryError(f"无法打开文件夹：{exc}") from None
        if not resolved.is_dir():
            raise LibraryError("这个路径不是文件夹。")
        self.root = resolved
        self._lock = threading.RLock()
        self._state_path = library_state_path(self.root)
        self._tags: Dict[str, List[str]] = {}
        self._favorites: Set[str] = set()
        self._custom_categories: List[Dict[str, object]] = []
        self._category_overrides: Dict[str, str] = {}
        self._subcategory_overrides: Dict[str, str] = {}
        self._extra_memberships: Dict[str, List[str]] = {}
        self._known_paths: Set[str] = set()
        self._load_state()
        self.tracks: List[Dict[str, object]] = []
        self._by_id: Dict[str, Dict[str, object]] = {}
        self.categories: List[Dict[str, object]] = legacy_categories()
        self.stats: Dict[str, object] = {}
        self.warnings: List[str] = []
        self.scanned_at = ""
        self.missing: List[Dict[str, object]] = []
        self.duplicates: List[Dict[str, object]] = []
        self.scan()

    # ------------------------------------------------------------------
    # Categories
    # ------------------------------------------------------------------

    def _category_defs(self) -> List[Dict[str, object]]:
        defs: List[Dict[str, object]] = legacy_categories() + legacy_asset_categories()
        known = {str(item["key"]): item for item in defs}
        for item in self._custom_categories:
            category = dict(item)
            category["custom"] = True
            parent_key = str(category.get("parent", "") or "")
            parent = known.get(parent_key)
            category["domain"] = str(parent.get("domain", "audio")) if parent else "custom"
            category.setdefault("icon", "folder")
            if parent:
                category.setdefault("description", f"「{parent['name']}」下的小类")
                category.setdefault("hint", "自定义小类")
            else:
                category.setdefault("description", "你自己创建的分类")
                category.setdefault("hint", "自定义分类")
            defs.append(category)
            known[str(category["key"])] = category
        return defs

    def _category_map(self) -> Dict[str, Dict[str, object]]:
        return {str(item["key"]): item for item in self._category_defs()}

    @staticmethod
    def _category_payload(
        category: Dict[str, object],
        reason: str,
        confidence: float,
        overridden: bool = False,
    ) -> Dict[str, object]:
        return {
            "key": category["key"],
            "name": category["name"],
            "description": category.get("description", ""),
            "hint": category.get("hint", ""),
            "accent": category.get("accent", "#817F73"),
            "icon": category.get("icon", "dots"),
            "domain": category.get("domain", "audio"),
            "parent": str(category.get("parent", "")),
            "custom": bool(category.get("custom")),
            "reason": reason,
            "confidence": round(confidence, 2),
            "overridden": overridden,
        }

    def _resolve_category(
        self,
        track: Dict[str, object],
        category_map: Dict[str, Dict[str, object]],
    ) -> Dict[str, object]:
        rel = str(track["rel_path"])
        key = str((track.get("category") or {}).get("key") or "")

        def apply_subcategory(category_key: str) -> None:
            _, mapping = _subcategory_config(category_key)
            if not mapping:
                track.pop("subcategory", None)
                return
            current = (track.get("category") or {}).get("subcategory") or {}
            default = current.get("key") or (track.get("_subcategory_default") or {}).get("key") or "other"
            sub_key = self._subcategory_overrides.get(rel, str(default))
            if sub_key not in mapping:
                sub_key = "other"
            sub = mapping.get(sub_key, mapping["other"])
            track["subcategory"] = {"key": sub["key"], "name": sub["name"]}

        apply_subcategory(key)

        def attach_memberships(primary: Dict[str, object]) -> Dict[str, object]:
            memberships = [primary]
            seen = {str(primary.get("key") or "")}
            for extra_key in self._extra_memberships.get(rel, []):
                if extra_key in seen or extra_key not in category_map:
                    continue
                extra = self._category_payload(
                    category_map[extra_key],
                    f"你也把它放进了「{category_map[extra_key]['name']}」",
                    1.0,
                    True,
                )
                extra.pop("subcategory", None)
                memberships.append(extra)
                seen.add(extra_key)
            # A custom subcategory always brings its parent drawer with it.
            for item in list(memberships):
                parent_key = str(item.get("parent", "") or "")
                if not parent_key or parent_key in seen or parent_key not in category_map:
                    continue
                parent = self._category_payload(
                    category_map[parent_key],
                    f"它属于「{category_map[parent_key]['name']}」下的小类",
                    1.0,
                    True,
                )
                parent.pop("subcategory", None)
                memberships.append(parent)
                seen.add(parent_key)
            track["categories"] = memberships
            return primary

        override = self._category_overrides.get(rel)
        if override and override in category_map:
            category = category_map[override]
            result = self._category_payload(category, f"你把它改到了「{category['name']}」", 1.0, True)
            apply_subcategory(str(category["key"]))
            if track.get("subcategory"):
                result["subcategory"] = track["subcategory"]
            else:
                result.pop("subcategory", None)
            return attach_memberships(result)

        category = dict(track.get("category") or {})
        apply_subcategory(key)
        if track.get("subcategory"):
            category["subcategory"] = track["subcategory"]
        category.setdefault("domain", "audio")
        category.setdefault("custom", False)
        category.setdefault("overridden", False)
        return attach_memberships(category)

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def scan(self) -> None:
        if not self.root.is_dir():
            raise LibraryError("文件夹已不存在，可能被移动或断开了。")
        started = time.time()
        paths: List[Tuple[Path, str, int, float, str]] = []
        warnings: List[str] = []

        def _walk_error(error: OSError) -> None:
            warnings.append(f"无法读取：{getattr(error, 'filename', '') or error}")

        for current, dirnames, filenames in os.walk(str(self.root), followlinks=False, onerror=_walk_error):
            dirnames[:] = sorted(
                (name for name in dirnames if name.casefold() not in _SKIP_DIRS and not name.startswith(".")),
                key=natural_key,
            )
            for filename in sorted(filenames, key=natural_key):
                if filename.startswith("."):
                    continue
                path = Path(current) / filename
                suffix = path.suffix.casefold()
                kind = _kind_for(suffix)
                if kind is None:
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    warnings.append(f"无法读取文件：{filename}")
                    continue
                rel = os.path.relpath(path, self.root).replace(os.sep, "/")
                paths.append((path, rel, stat.st_size, stat.st_mtime, kind))
                if len(paths) >= _MAX_FILES:
                    warnings.append(f"文件超过 {_MAX_FILES} 个，本次只读取前 {_MAX_FILES} 个。")
                    break
            if len(paths) >= _MAX_FILES:
                break

        if paths:
            workers = min(8, max(1, len(paths)))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                loaded = list(
                    pool.map(
                        lambda item: _read_meta_safe(item[0]) if item[4] == "audio" else _read_asset_safe(item[0]),
                        paths,
                    )
                )
        else:
            loaded = []

        tracks: List[Dict[str, object]] = []
        category_map = self._category_map()
        for (path, rel, size, modified, kind), info in zip(paths, loaded):
            track_id = stable_id(rel)
            tags = _clean_tags(self._tags.get(rel, []))
            folder = str(PurePosixPath(rel).parent)
            if folder == ".":
                folder = ""
            suffix = path.suffix.casefold()
            common = {
                "id": track_id,
                "kind": kind,
                "filename": path.name,
                "rel_path": rel,
                "folder": folder,
                "format": path.suffix.lstrip(".").upper(),
                "size": size,
                "modified": _modified_iso(modified),
                "favorite": rel in self._favorites,
                "tags": tags,
                "stream_url": "",
                "cover_url": "",
                "thumb_url": "",
                "inspect_url": "",
                "summary": "",
                "stats": {},
                "note": "",
                "_path": str(path),
            }
            if kind == "audio":
                meta = info
                guessed_title, guessed_artist = metadata.guess_from_filename(path.name)
                title = metadata._clean(meta.title) or guessed_title or path.stem
                artist = metadata._clean(meta.artist) or guessed_artist
                track = {
                    **common,
                    "title": title,
                    "artist": artist,
                    "album": metadata._clean(meta.album),
                    "genre": metadata._clean(meta.genre),
                    "year": metadata._clean(meta.year),
                    "track_number": metadata._clean(meta.track),
                    "duration": meta.duration,
                    "bitrate": meta.bitrate,
                    "sample_rate": meta.sample_rate,
                    "channels": meta.channels,
                    "has_cover": bool(meta.has_cover),
                    "category": classify_track(rel, meta),
                    "stream_url": f"/api/stream/{track_id}",
                    "cover_url": f"/api/cover/{track_id}?v={int(modified)}" if meta.has_cover else "",
                    "summary": f"{path.suffix.lstrip('.').upper()} · {_short_duration(meta.duration)}",
                    "_subcategory_default": classify_sfx_subcategory(rel, meta),
                }
            else:
                asset = info
                stats = dict(asset.stats)
                if asset.width or asset.height:
                    stats["width"] = asset.width
                    stats["height"] = asset.height
                is_image = suffix in IMAGE_EXTENSIONS
                track = {
                    **common,
                    "title": path.stem,
                    "artist": "",
                    "album": "",
                    "genre": "",
                    "year": "",
                    "track_number": "",
                    "duration": 0,
                    "bitrate": 0,
                    "sample_rate": 0,
                    "channels": 0,
                    "has_cover": False,
                    "category": classify_asset(rel, asset),
                    "_subcategory_default": classify_animation_subcategory(rel, asset),
                    "format": asset.format or path.suffix.lstrip(".").upper(),
                    "thumb_url": f"/api/thumb/{track_id}?v={int(modified)}" if is_image else "",
                    "inspect_url": f"/api/inspect/{track_id}",
                    "summary": probe.summarize(asset),
                    "stats": stats,
                    "note": asset.note,
                }
                if asset.note and len(warnings) < 20:
                    warnings.append(f"{rel}：{asset.note}")
            track["category"] = self._resolve_category(track, category_map)
            tracks.append(track)

        tracks.sort(key=lambda item: natural_key(str(item["rel_path"])))
        all_categories = self._category_defs()
        counts: Dict[str, int] = {str(category["key"]): 0 for category in all_categories}
        for track in tracks:
            memberships = track.get("categories") or [track["category"]]
            for membership in memberships:
                category_key = str(membership.get("key") or "")
                if category_key:
                    counts[category_key] = counts.get(category_key, 0) + 1

        sub_counts: Dict[str, Dict[str, int]] = {
            key: {item["key"]: 0 for item in items}
            for key, (items, _) in (
                ("sfx", _subcategory_config("sfx")),
                ("animation", _subcategory_config("animation")),
            )
            if items
        }
        for track in tracks:
            category_key = str(track["category"]["key"])
            if category_key in sub_counts and track.get("subcategory"):
                sub_key = str(track["subcategory"]["key"])
                sub_counts[category_key][sub_key] = sub_counts[category_key].get(sub_key, 0) + 1

        for category in all_categories:
            count = counts.get(str(category["key"]), 0)
            category["count"] = count
            category["share"] = round(count / len(tracks) * 100) if tracks else 0
            subcategories = _subcategory_payload(str(category["key"]), sub_counts.get(str(category["key"]), {}))
            if subcategories:
                category["subcategories"] = subcategories

        audio_tracks = [track for track in tracks if track["kind"] == "audio"]
        asset_tracks = [track for track in tracks if track["kind"] == "asset"]
        total_duration = sum(float(track["duration"] or 0) for track in audio_tracks)
        favorites = sum(1 for track in tracks if track["favorite"])
        tagged = sum(1 for track in tracks if track["tags"])
        animations = 0
        models = 0
        textures = 0
        for track in asset_tracks:
            key = str(track["category"]["key"])
            stats = track.get("stats") or {}
            if key == "animation":
                animations += max(1, int(stats.get("animations") or 0))
            elif key == "texture":
                textures += 1
            elif key in ("model", "character", "prop", "scene"):
                models += 1
        stats = {
            "total": len(tracks),
            "audio": len(audio_tracks),
            "assets": len(asset_tracks),
            "favorites": favorites,
            "tagged": tagged,
            "untagged": len(tracks) - tagged,
            "total_duration": round(total_duration, 3),
            "total_size": sum(int(track["size"]) for track in tracks),
            "animations": animations,
            "models": models,
            "textures": textures,
            "scan_seconds": round(time.time() - started, 2),
        }

        current_paths = {str(track["rel_path"]) for track in tracks}
        known = set(self._known_paths) | current_paths
        missing: List[Dict[str, object]] = []
        for rel in sorted(known - current_paths, key=natural_key):
            folder = str(PurePosixPath(rel).parent)
            missing.append(
                {
                    "rel_path": rel,
                    "filename": PurePosixPath(rel).name,
                    "folder": "" if folder == "." else folder,
                }
            )
        duplicates = _duplicate_groups(tracks)

        with self._lock:
            self.tracks = tracks
            self._by_id = {str(track["id"]): track for track in tracks}
            self.categories = all_categories
            self.stats = stats
            self.warnings = warnings
            self.scanned_at = _now_iso()
            self._known_paths = known
            self.missing = missing
            self.duplicates = duplicates
            self._save_state()

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> None:
        data = read_json(self._state_path) or {}
        tags: Dict[str, List[str]] = {}
        raw_tags = data.get("tags")
        if isinstance(raw_tags, dict):
            for key, values in raw_tags.items():
                if not isinstance(key, str):
                    continue
                cleaned = _clean_tags(values)
                if cleaned:
                    tags[key] = cleaned
        favorites: Set[str] = set()
        raw_favorites = data.get("favorites")
        if isinstance(raw_favorites, list):
            for item in raw_favorites:
                if isinstance(item, str) and item:
                    favorites.add(item)
        self._tags = tags
        self._favorites = favorites

        custom: List[Dict[str, object]] = []
        raw_custom = data.get("custom_categories")
        if isinstance(raw_custom, list):
            seen: Set[str] = set()
            for item in raw_custom:
                if not isinstance(item, dict):
                    continue
                key = _clean_category_key(item.get("key"))
                name = _clean_category_name(item.get("name"))
                if not key.startswith("custom:") or key in seen or not name:
                    continue
                accent = str(item.get("accent") or "")
                if not _HEX_RE.match(accent):
                    accent = _CUSTOM_ACCENTS[len(custom) % len(_CUSTOM_ACCENTS)]
                seen.add(key)
                custom.append(
                    {
                        "key": key,
                        "name": name,
                        "description": "你自己创建的分类",
                        "hint": "自定义分类",
                        "accent": accent,
                        "icon": "folder",
                        "domain": "custom",
                        "custom": True,
                    }
                )
                if len(custom) >= _MAX_CUSTOM_CATEGORIES:
                    break
        self._custom_categories = custom

        overrides: Dict[str, str] = {}
        raw_overrides = data.get("category_overrides")
        if isinstance(raw_overrides, dict):
            for rel, key in raw_overrides.items():
                if isinstance(rel, str) and isinstance(key, str) and key:
                    overrides[rel] = key
        self._category_overrides = overrides

        sub_overrides: Dict[str, str] = {}
        raw_sub = data.get("subcategory_overrides")
        if isinstance(raw_sub, dict):
            for rel, key in raw_sub.items():
                if isinstance(rel, str) and (key in SFX_SUBCATEGORY_BY_KEY or key in ANIMATION_SUBCATEGORY_BY_KEY):
                    sub_overrides[rel] = str(key)
        self._subcategory_overrides = sub_overrides

        memberships: Dict[str, List[str]] = {}
        raw_memberships = data.get("memberships")
        if isinstance(raw_memberships, dict):
            for rel, keys in raw_memberships.items():
                if not isinstance(rel, str) or not isinstance(keys, list):
                    continue
                cleaned = []
                for key in keys:
                    if isinstance(key, str) and key and key not in cleaned:
                        cleaned.append(key)
                if cleaned:
                    memberships[rel] = cleaned[:16]
        self._extra_memberships = memberships

        known: Set[str] = set()
        raw_known = data.get("known_paths")
        if isinstance(raw_known, list):
            for rel in raw_known:
                if isinstance(rel, str) and rel:
                    known.add(rel.replace("\\", "/"))
        self._known_paths = known

    def _save_state(self) -> None:
        payload = {
            "version": 2,
            "root": str(self.root),
            "updated_at": _now_iso(),
            "tags": {key: value for key, value in sorted(self._tags.items()) if value},
            "favorites": sorted(self._favorites),
            "custom_categories": [dict(item) for item in self._custom_categories],
            "category_overrides": {key: value for key, value in sorted(self._category_overrides.items()) if value},
            "subcategory_overrides": {key: value for key, value in sorted(self._subcategory_overrides.items()) if value},
            "memberships": {key: value for key, value in sorted(self._extra_memberships.items()) if value},
            "known_paths": sorted(self._known_paths),
        }
        try:
            write_json(self._state_path, payload)
        except OSError as exc:
            raise LibraryError(f"无法保存标签和收藏：{exc}") from None

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> Dict[str, object]:
        with self._lock:
            tracks = [self._public_track(track) for track in self.tracks]
            categories = [dict(category) for category in self.categories]
            stats = dict(self.stats)
            warnings = list(self.warnings)
            scanned_at = self.scanned_at
            missing = [dict(item) for item in self.missing]
            duplicates = [
                {**group, "tracks": [dict(item) for item in group.get("tracks", [])]}
                for group in self.duplicates
            ]
        return {
            "root": str(self.root),
            "name": self.root.name or str(self.root),
            "scanned_at": scanned_at,
            "tracks": tracks,
            "categories": categories,
            "tags": self._all_tags(tracks),
            "stats": stats,
            "warnings": warnings,
            "missing": missing,
            "duplicates": duplicates,
        }

    @staticmethod
    def _public_track(track: Dict[str, object]) -> Dict[str, object]:
        return {key: value for key, value in track.items() if not key.startswith("_")}

    @staticmethod
    def _all_tags(tracks: Sequence[Dict[str, object]]) -> List[Dict[str, object]]:
        counts: Dict[str, int] = {}
        labels: Dict[str, str] = {}
        for track in tracks:
            for tag in track.get("tags", []):
                key = str(tag).casefold()
                counts[key] = counts.get(key, 0) + 1
                labels.setdefault(key, str(tag))
        values = [
            {"name": labels[key], "count": counts[key]}
            for key in counts
        ]
        values.sort(key=lambda item: (-int(item["count"]), natural_key(str(item["name"]))))
        return values

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def _tracks_for_ids(self, ids: Iterable[str]) -> List[Dict[str, object]]:
        if isinstance(ids, str):
            ids = [ids]
        if not isinstance(ids, (list, tuple, set)):
            raise LibraryError("请选择素材。")
        result: List[Dict[str, object]] = []
        seen: Set[str] = set()
        missing = 0
        with self._lock:
            for raw_id in ids:
                track_id = str(raw_id)
                if track_id in seen:
                    continue
                seen.add(track_id)
                track = self._by_id.get(track_id)
                if track is None:
                    missing += 1
                    continue
                result.append(track)
        if not result:
            raise LibraryError("选中的素材已不在库中，请刷新后重试。")
        if missing:
            raise LibraryError(f"有 {missing} 项素材已不在库中，请刷新后重试。")
        return result

    def get_track(self, track_id: str) -> Optional[Dict[str, object]]:
        with self._lock:
            track = self._by_id.get(track_id)
            return dict(track) if track else None

    def stream_path(self, track_id: str) -> Optional[Path]:
        track = self.get_track(track_id)
        if not track or track.get("kind") != "audio":
            return None
        path = Path(str(track["_path"]))
        try:
            if path.resolve().is_file():
                return path
        except OSError:
            return None
        return None

    def asset_path(self, track_id: str) -> Optional[Path]:
        track = self.get_track(track_id)
        if not track or track.get("kind") != "asset":
            return None
        path = Path(str(track["_path"]))
        try:
            if path.resolve().is_file():
                return path
        except OSError:
            return None
        return None

    def thumb_path(self, track_id: str) -> Optional[Path]:
        track = self.get_track(track_id)
        if not track or track.get("kind") != "asset":
            return None
        if Path(str(track["filename"])).suffix.casefold() not in IMAGE_EXTENSIONS:
            return None
        path = Path(str(track["_path"]))
        try:
            if path.resolve().is_file():
                return path
        except OSError:
            return None
        return None

    def inspect(self, track_id: str) -> Optional[Dict[str, object]]:
        track = self.get_track(track_id)
        if not track:
            return None
        public = self._public_track(track)
        public["absolute_path"] = str(track.get("_path") or "")
        return public

    def motion(self, track_id: str) -> Optional[Dict[str, object]]:
        """Return a compact skeleton preview for BVH, GLB or glTF actions."""
        track = self.get_track(track_id)
        if not track or track.get("kind") != "asset":
            return None
        suffix = Path(str(track.get("filename") or "")).suffix.casefold()
        if suffix not in (".bvh", ".glb", ".gltf", ".fbx"):
            return None
        from .motion import load_motion

        return load_motion(Path(str(track.get("_path") or "")))

    # ------------------------------------------------------------------
    # User taxonomy
    # ------------------------------------------------------------------

    def create_category(
        self, name: object, accent: object = "", parent: object = ""
    ) -> Dict[str, object]:
        cleaned = _clean_category_name(name)
        if not cleaned or not _CATEGORY_NAME_RE.match(cleaned):
            raise LibraryError("分类名称需要 1–24 个字，不能包含特殊符号。")
        parent_key = str(parent or "").strip()
        with self._lock:
            definitions = self._category_defs()
            by_key = {str(item["key"]): item for item in definitions}
            if parent_key:
                parent_item = by_key.get(parent_key)
                if not parent_item:
                    raise LibraryError("找不到要归属的大类。")
                if str(parent_item.get("parent", "")):
                    raise LibraryError("小类只能放在大类下，不能再嵌套。")
            existing_names = {str(item["name"]).casefold() for item in definitions}
            if cleaned.casefold() in existing_names:
                raise LibraryError(f"分类「{cleaned}」已经存在。")
            if len(self._custom_categories) >= _MAX_CUSTOM_CATEGORIES:
                raise LibraryError(f"最多只能创建 {_MAX_CUSTOM_CATEGORIES} 个自定义分类。")
            color = str(accent or "").strip()
            if not _HEX_RE.match(color):
                color = _CUSTOM_ACCENTS[len(self._custom_categories) % len(_CUSTOM_ACCENTS)]
            category = {
                "key": "custom:" + hashlib.sha1(f"{parent_key}|{cleaned}".encode("utf-8")).hexdigest()[:10],
                "name": cleaned,
                "description": "你自己创建的分类",
                "hint": "自定义分类",
                "accent": color,
                "icon": "folder",
                "domain": "custom",
                "custom": True,
                "parent": parent_key,
            }
            self._custom_categories.append(category)
            self._save_state()
            self.scan()
            return dict(category)

    def set_category(self, ids: Iterable[str], category_key: object) -> Dict[str, object]:
        raw_key = _clean_category_key(category_key)
        tracks = self._tracks_for_ids(ids)
        if raw_key not in ("", "auto"):
            if raw_key not in self._category_map():
                raise LibraryError("找不到这个分类。")
        with self._lock:
            for track in tracks:
                rel = str(track["rel_path"])
                if raw_key in ("", "auto"):
                    self._category_overrides.pop(rel, None)
                    self._extra_memberships.pop(rel, None)
                else:
                    self._category_overrides[rel] = raw_key
                    self._extra_memberships.pop(rel, None)
            self._save_state()
            self.scan()
        return self.snapshot()

    def set_memberships(self, ids: Iterable[str], category_keys: object) -> Dict[str, object]:
        if not isinstance(category_keys, list):
            raise LibraryError("分类列表格式不正确。")
        cleaned: List[str] = []
        for key in category_keys:
            if isinstance(key, str) and key and key not in cleaned:
                cleaned.append(key)
        if len(cleaned) > 8:
            raise LibraryError("一件素材最多放进 8 个分类。")
        tracks = self._tracks_for_ids(ids)
        category_map = self._category_map()
        for key in cleaned:
            if key not in category_map:
                raise LibraryError("找不到这个分类。")
        if not tracks:
            raise LibraryError("先选择要整理的素材。")
        with self._lock:
            for track in tracks:
                rel = str(track["rel_path"])
                if not cleaned:
                    self._category_overrides.pop(rel, None)
                    self._extra_memberships.pop(rel, None)
                    continue
                self._category_overrides[rel] = cleaned[0]
                self._extra_memberships[rel] = cleaned[1:]
            self._save_state()
            self.scan()
        return self.snapshot()

    def remove_from_category(self, ids: Iterable[str], category_key: object) -> Dict[str, object]:
        raw_key = _clean_category_key(category_key)
        tracks = self._tracks_for_ids(ids)
        if not raw_key:
            raise LibraryError("缺少要移出的分类。")
        if not tracks:
            raise LibraryError("先选择要整理的素材。")
        with self._lock:
            for track in tracks:
                rel = str(track["rel_path"])
                primary = str((track.get("category") or {}).get("key") or "")
                extras = [key for key in self._extra_memberships.get(rel, []) if key != raw_key]
                if primary == raw_key:
                    if extras:
                        self._category_overrides[rel] = extras.pop(0)
                    else:
                        self._category_overrides[rel] = "other" if track.get("kind") == "audio" else "asset_other"
                        self._subcategory_overrides.pop(rel, None)
                if extras:
                    self._extra_memberships[rel] = extras
                else:
                    self._extra_memberships.pop(rel, None)
            self._save_state()
            self.scan()
        return self.snapshot()

    def set_subcategory(self, ids: Iterable[str], subcategory_key: object) -> Dict[str, object]:
        raw_key = _clean_category_key(subcategory_key)
        tracks = self._tracks_for_ids(ids)
        if raw_key not in ("", "auto") and raw_key not in SFX_SUBCATEGORY_BY_KEY and raw_key not in ANIMATION_SUBCATEGORY_BY_KEY:
            raise LibraryError("找不到这个细类。")
        for track in tracks:
            category_key = str((track.get("category") or {}).get("key") or "")
            _, mapping = _subcategory_config(category_key)
            if not mapping:
                raise LibraryError("细类只能设置在「音效」或「骨骼动作」素材上。")
            if raw_key not in ("", "auto") and raw_key not in mapping:
                raise LibraryError(f"「{mapping['other']['name']}」不适用这个细类。")
        with self._lock:
            for track in tracks:
                rel = str(track["rel_path"])
                if raw_key in ("", "auto"):
                    self._subcategory_overrides.pop(rel, None)
                else:
                    self._subcategory_overrides[rel] = raw_key
            self._save_state()
            self.scan()
        return self.snapshot()

    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------

    def add_tags(self, ids: Iterable[str], tags: Iterable[str]) -> Dict[str, object]:
        cleaned = _clean_tags(list(tags))
        if not cleaned:
            raise LibraryError("请输入至少一个标签。")
        tracks = self._tracks_for_ids(ids)
        with self._lock:
            for track in tracks:
                rel = str(track["rel_path"])
                existing = self._tags.get(rel, [])
                merged = _clean_tags(list(existing) + cleaned)
                self._tags[rel] = merged
            self._save_state()
            self.scan()
        return self.snapshot()

    def remove_tag(self, ids: Iterable[str], tag: str) -> Dict[str, object]:
        cleaned = _clean_tag(tag)
        if not cleaned:
            raise LibraryError("请选择要移除的标签。")
        key = cleaned.casefold()
        tracks = self._tracks_for_ids(ids)
        with self._lock:
            for track in tracks:
                rel = str(track["rel_path"])
                if rel in self._tags:
                    remaining = [item for item in self._tags[rel] if item.casefold() != key]
                    if remaining:
                        self._tags[rel] = remaining
                    else:
                        self._tags.pop(rel, None)
            self._save_state()
            self.scan()
        return self.snapshot()

    def set_tags(self, track_id: str, tags: Iterable[str]) -> Dict[str, object]:
        cleaned = _clean_tags(list(tags))
        track = self._tracks_for_ids([track_id])[0]
        rel = str(track["rel_path"])
        with self._lock:
            if cleaned:
                self._tags[rel] = cleaned
            else:
                self._tags.pop(rel, None)
            self._save_state()
            self.scan()
        return self.snapshot()

    # ------------------------------------------------------------------
    # Favourites
    # ------------------------------------------------------------------

    def set_favorite(self, ids: Iterable[str], favorite: bool) -> Dict[str, object]:
        tracks = self._tracks_for_ids(ids)
        with self._lock:
            for track in tracks:
                rel = str(track["rel_path"])
                if favorite:
                    self._favorites.add(rel)
                else:
                    self._favorites.discard(rel)
            self._save_state()
            self.scan()
        return self.snapshot()

    # ------------------------------------------------------------------
    # Rename
    # ------------------------------------------------------------------

    def _rename_files(self, ids: Iterable[str]) -> List[Dict[str, str]]:
        tracks = self._tracks_for_ids(ids)
        files: List[Dict[str, str]] = []
        for track in tracks:
            path = Path(str(track["_path"]))
            files.append(
                {
                    "id": str(track["id"]),
                    "rel_path": str(track["rel_path"]),
                    "path": str(path),
                    "filename": str(track["filename"]),
                }
            )
        return files

    @staticmethod
    def _public_plan(plan: Dict[str, object]) -> Dict[str, object]:
        public = {key: value for key, value in plan.items() if key != "items"}
        public["items"] = [
            {key: value for key, value in row.items() if key not in ("source", "target")}
            for row in plan.get("items", [])
        ]
        return public

    def preview_rename(
        self,
        ids: Iterable[str],
        base: str,
        start: int,
        digits: int,
        separator: str,
    ) -> Dict[str, object]:
        options = validate_options(base, start, digits, separator)
        files = self._rename_files(ids)
        return self._public_plan(build_plan(files, options))

    def rename(
        self,
        ids: Iterable[str],
        base: str,
        start: int,
        digits: int,
        separator: str,
    ) -> Dict[str, object]:
        options = validate_options(base, start, digits, separator)
        files = self._rename_files(ids)
        plan = build_plan(files, options)
        if not plan["ok"]:
            result = self._public_plan(plan)
            result["error"] = "计划中仍有冲突，请先处理。"
            return {"ok": False, "plan": result}

        try:
            outcome = apply_plan(plan)
        except RenameError as exc:
            raise LibraryError(str(exc)) from None

        mapping = outcome["mapping"]
        old_to_new = {str(item["old_rel_path"]): str(item["new_rel_path"]) for item in mapping}
        old_paths = set(old_to_new)
        with self._lock:
            new_tags: Dict[str, List[str]] = {}
            for rel, tags in self._tags.items():
                if rel not in old_paths:
                    new_tags[rel] = tags
            for old_rel, tags in self._tags.items():
                if old_rel in old_to_new:
                    target = old_to_new[old_rel]
                    if tags:
                        new_tags[target] = _clean_tags(list(new_tags.get(target, [])) + list(tags))
            self._tags = new_tags

            new_favorites: Set[str] = {rel for rel in self._favorites if rel not in old_paths}
            for old_rel in self._favorites:
                if old_rel in old_to_new:
                    new_favorites.add(old_to_new[old_rel])
            self._favorites = new_favorites

            new_overrides = {rel: key for rel, key in self._category_overrides.items() if rel not in old_paths}
            for old_rel, key in self._category_overrides.items():
                if old_rel in old_to_new:
                    new_overrides[old_to_new[old_rel]] = key
            self._category_overrides = new_overrides

            new_sub_overrides = {rel: key for rel, key in self._subcategory_overrides.items() if rel not in old_paths}
            for old_rel, key in self._subcategory_overrides.items():
                if old_rel in old_to_new:
                    new_sub_overrides[old_to_new[old_rel]] = key
            self._subcategory_overrides = new_sub_overrides

            new_memberships = {rel: keys for rel, keys in self._extra_memberships.items() if rel not in old_paths}
            for old_rel, keys in self._extra_memberships.items():
                if old_rel in old_to_new:
                    new_memberships[old_to_new[old_rel]] = keys
            self._extra_memberships = new_memberships

            state_warning = ""
            try:
                self._save_state()
            except LibraryError as exc:
                state_warning = str(exc)
            self.scan()

        by_rel = {str(track["rel_path"]): str(track["id"]) for track in self.tracks}
        for item in mapping:
            item["new_id"] = by_rel.get(str(item["new_rel_path"]), "")
        result = self._public_plan(plan)
        result["renamed"] = len(mapping)
        result["mapping"] = mapping
        if state_warning:
            result["warning"] = state_warning
        return {"ok": True, "plan": result}

    # ------------------------------------------------------------------
    # Helpers used by the HTTP layer
    # ------------------------------------------------------------------

    def cover(self, track_id: str) -> Optional[Tuple[str, bytes]]:
        track = self.get_track(track_id)
        if not track or not track.get("has_cover"):
            return None
        path = Path(str(track["_path"]))
        try:
            mime, data = metadata.read_cover(path)
        except Exception:
            return None
        if not data:
            return None
        return mime, data

    def export_metadata(self) -> Dict[str, object]:
        """Export tags, favorites and taxonomy without touching the media files."""
        with self._lock:
            entries: List[Dict[str, object]] = []
            for track in self.tracks:
                rel = str(track.get("rel_path") or "")
                if not rel:
                    continue
                category = track.get("category") or {}
                entries.append(
                    {
                        "rel_path": rel,
                        "filename": track.get("filename") or PurePosixPath(rel).name,
                        "kind": track.get("kind") or "audio",
                        "tags": list(track.get("tags") or []),
                        "favorite": bool(track.get("favorite")),
                        "categories": [
                            str(item.get("key"))
                            for item in (track.get("categories") or [])
                            if item.get("key")
                        ],
                        "subcategory": (category.get("subcategory") or {}).get("key") or "",
                    }
                )
        return {"version": 1, "root": str(self.root), "tracks": entries}

    def import_metadata(self, metadata: object) -> Dict[str, object]:
        """Import metadata by relative path; never writes to the source files."""
        if not isinstance(metadata, dict):
            raise LibraryError("导入文件格式不正确。")
        entries = metadata.get("tracks")
        if not isinstance(entries, list):
            raise LibraryError("导入文件里没有素材资料。")
        by_rel = {str(track.get("rel_path") or ""): track for track in self.tracks}
        category_map = self._category_map()
        imported = 0
        skipped = 0
        for entry in entries:
            if not isinstance(entry, dict):
                skipped += 1
                continue
            rel = str(entry.get("rel_path") or "").replace("\\", "/")
            track = by_rel.get(rel)
            if not track:
                skipped += 1
                continue
            keys = [
                str(key)
                for key in (entry.get("categories") or [])
                if isinstance(key, str) and key in category_map
            ][:8]
            with self._lock:
                self._tags[rel] = _clean_tags(list(entry.get("tags") or []))
                if bool(entry.get("favorite")):
                    self._favorites.add(rel)
                else:
                    self._favorites.discard(rel)
                if keys:
                    self._category_overrides[rel] = keys[0]
                    self._extra_memberships[rel] = keys[1:]
                subcategory = str(entry.get("subcategory") or "")
                if keys and subcategory:
                    _, mapping = _subcategory_config(keys[0])
                    if mapping and subcategory in mapping:
                        self._subcategory_overrides[rel] = subcategory
                    else:
                        self._subcategory_overrides.pop(rel, None)
                else:
                    self._subcategory_overrides.pop(rel, None)
            imported += 1
        with self._lock:
            self._save_state()
            self.scan()
        return {"imported": imported, "skipped": skipped, "library": self.snapshot()}

    def dismiss_missing(self, rel_paths: Iterable[str]) -> Dict[str, object]:
        values = {str(item).replace("\\", "/") for item in rel_paths if str(item).strip()}
        with self._lock:
            self._known_paths = {rel for rel in self._known_paths if rel not in values}
            self.missing = [item for item in self.missing if item.get("rel_path") not in values]
            self._save_state()
        return self.snapshot()

    def rescan(self) -> Dict[str, object]:
        with self._lock:
            self.scan()
        return self.snapshot()
