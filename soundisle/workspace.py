"""A workspace made of several independent media folders.

Each folder keeps its own :class:`Library` state (tags, favourites, taxonomy
overrides), while the workspace presents one combined, read-only view.  Track
ids are namespaced with a short source id so two folders may safely contain the
same relative path.
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .library import Library, LibraryError, natural_key


_MAX_SOURCES = 24
_URL_RE = re.compile(r"^(/api/(?:stream|cover|thumb|inspect)/)([^?]+)(\?.*)?$")


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _source_id(path: Path) -> str:
    normalised = os.path.normcase(os.path.realpath(str(path)))
    return hashlib.sha1(normalised.encode("utf-8")).hexdigest()[:10]


class Workspace:
    def __init__(self, roots: Sequence[str | Path]):
        self._lock = threading.RLock()
        self._sources: List[Dict[str, object]] = []
        self._id_map: Dict[str, Tuple[Dict[str, object], str]] = {}
        seen = set()
        for raw in roots:
            try:
                resolved = Path(raw).expanduser().resolve(strict=True)
            except OSError as exc:
                raise LibraryError(f"无法打开文件夹：{exc}") from None
            if not resolved.is_dir():
                raise LibraryError("这个路径不是文件夹。")
            key = os.path.normcase(str(resolved))
            if key in seen:
                continue
            seen.add(key)
            source = self._make_source(resolved)
            self._sources.append(source)
            if len(self._sources) >= _MAX_SOURCES:
                break
        if not self._sources:
            raise LibraryError("请先添加一个素材文件夹。")
        self._rebuild_index()

    # ------------------------------------------------------------------
    # Sources
    # ------------------------------------------------------------------

    @staticmethod
    def _make_source(path: Path) -> Dict[str, object]:
        return {
            "id": _source_id(path),
            "path": path,
            "name": path.name or str(path),
            "library": Library(path),
        }

    def _refresh_names(self) -> None:
        used: Dict[str, int] = {}
        for source in self._sources:
            base = str(source["name"])
            count = used.get(base, 0) + 1
            used[base] = count
            source["display_name"] = base if count == 1 else f"{base} ({count})"

    @property
    def paths(self) -> List[Path]:
        return [Path(source["path"]) for source in self._sources]

    @property
    def root(self) -> Path:
        return Path(self._sources[0]["path"])

    @property
    def name(self) -> str:
        return str(self._sources[0]["display_name"]) if len(self._sources) == 1 else "混合素材库"

    @property
    def sources(self) -> List[Dict[str, object]]:
        return [
            {
                "id": str(source["id"]),
                "name": str(source["display_name"]),
                "path": str(source["path"]),
                "count": int(source.get("count") or 0),
                "exists": Path(str(source["path"])).is_dir(),
            }
            for source in self._sources
        ]

    def add_source(self, path: str | Path) -> None:
        try:
            resolved = Path(path).expanduser().resolve(strict=True)
        except OSError as exc:
            raise LibraryError(f"无法打开文件夹：{exc}") from None
        if not resolved.is_dir():
            raise LibraryError("这个路径不是文件夹。")
        key = os.path.normcase(str(resolved))
        if any(os.path.normcase(str(item["path"])) == key for item in self._sources):
            raise LibraryError("这个文件夹已经在素材库里了。")
        if len(self._sources) >= _MAX_SOURCES:
            raise LibraryError(f"最多只能添加 {_MAX_SOURCES} 个素材文件夹。")
        with self._lock:
            self._sources.append(self._make_source(resolved))
            self._rebuild_index()

    def remove_source(self, source_id: str) -> None:
        if len(self._sources) <= 1:
            raise LibraryError("至少保留一个素材文件夹。")
        with self._lock:
            remaining = [item for item in self._sources if str(item["id"]) != source_id]
            if len(remaining) == len(self._sources):
                raise LibraryError("找不到这个素材文件夹。")
            self._sources = remaining
            self._rebuild_index()

    # ------------------------------------------------------------------
    # Combined snapshot
    # ------------------------------------------------------------------

    def _wrap_track(self, source: Dict[str, object], track: Dict[str, object]) -> Dict[str, object]:
        source_id = str(source["id"])
        source_name = str(source["display_name"])
        old_id = str(track["id"])
        new_id = f"{source_id}-{old_id}"
        item = dict(track)
        item["id"] = new_id
        item["source_id"] = source_id
        item["source_name"] = source_name
        item["source_path"] = str(source["path"])
        rel = str(item.get("rel_path") or "")
        item["source_rel_path"] = rel
        item["rel_path"] = f"{source_name}/{rel}" if rel else source_name
        folder = str(item.get("folder") or "")
        item["folder"] = source_name + (f"/{folder}" if folder else "")
        for key in ("stream_url", "cover_url", "thumb_url", "inspect_url"):
            value = item.get(key)
            if not value:
                continue
            match = _URL_RE.match(str(value))
            if match:
                item[key] = f"{match.group(1)}{new_id}{match.group(3) or ''}"
        return item

    def _sub_snapshots(self) -> List[Tuple[Dict[str, object], Dict[str, object]]]:
        self._refresh_names()
        result = []
        for source in self._sources:
            library = source["library"]
            snapshot = library.snapshot()
            source["count"] = len(snapshot["tracks"])
            result.append((source, snapshot))
        return result

    def _rebuild_index(self) -> None:
        self._refresh_names()
        new_map: Dict[str, Tuple[Dict[str, object], str]] = {}
        for source in self._sources:
            library = source["library"]
            snapshot = library.snapshot()
            source["count"] = len(snapshot["tracks"])
            for track in snapshot["tracks"]:
                new_id = f"{source['id']}-{track['id']}"
                new_map[new_id] = (source, str(track["id"]))

        self._id_map = new_map

    def snapshot(self) -> Dict[str, object]:
        with self._lock:
            source_snapshots = self._sub_snapshots()
            tracks: List[Dict[str, object]] = []
            definitions: List[Dict[str, object]] = []
            seen_categories = set()
            warnings: List[str] = []
            missing: List[Dict[str, object]] = []
            duplicate_groups: List[Dict[str, object]] = []
            for source, snapshot in source_snapshots:
                for item in snapshot.get("missing") or []:
                    missing.append(
                        {
                            **dict(item),
                            "source_id": str(source["id"]),
                            "source_name": str(source["display_name"]),
                            "source_path": str(source["path"]),
                        }
                    )
                for group in snapshot.get("duplicates") or []:
                    duplicate_groups.append(
                        {
                            **dict(group),
                            "tracks": [
                                {
                                    **dict(item),
                                    "id": f"{source['id']}-{item['id']}",
                                    "source_id": str(source["id"]),
                                    "source_name": str(source["display_name"]),
                                }
                                for item in group.get("tracks", [])
                            ],
                        }
                    )
                for category in snapshot.get("categories") or []:
                    key = str(category.get("key") or "")
                    if key and key not in seen_categories:
                        seen_categories.add(key)
                        definitions.append(dict(category))
                for warning in snapshot.get("warnings") or []:
                    warnings.append(f"{source['display_name']}：{warning}")
                for track in snapshot["tracks"]:
                    tracks.append(self._wrap_track(source, track))

            counts: Dict[str, int] = {str(item["key"]): 0 for item in definitions}
            sub_counts: Dict[str, Dict[str, int]] = {}
            for track in tracks:
                for membership in track.get("categories") or [track.get("category") or {}]:
                    key = str((membership or {}).get("key") or "")
                    if key:
                        counts[key] = counts.get(key, 0) + 1
                key = str((track.get("category") or {}).get("key") or "")
                sub = (track.get("category") or {}).get("subcategory") or {}
                if sub and key in ("sfx", "animation"):
                    sub_key = str(sub.get("key") or "")
                    if sub_key:
                        sub_counts.setdefault(key, {})
                        sub_counts[key][sub_key] = sub_counts[key].get(sub_key, 0) + 1

            for category in definitions:
                key = str(category["key"])
                count = counts.get(key, 0)
                category["count"] = count
                category["share"] = round(count / len(tracks) * 100) if tracks else 0
                if key in sub_counts:
                    existing = {
                        str(item["key"]): dict(item)
                        for item in (category.get("subcategories") or [])
                    }
                    for item in (category.get("subcategories") or []):
                        existing[str(item["key"])]["count"] = sub_counts[key].get(str(item["key"]), 0)
                    category["subcategories"] = list(existing.values())

            audio_tracks = [track for track in tracks if track.get("kind") == "audio"]
            asset_tracks = [track for track in tracks if track.get("kind") == "asset"]
            stats_keys = ("favorites", "tagged", "untagged", "total_duration", "total_size", "animations", "models", "textures", "scan_seconds")
            stats = {
                "total": len(tracks),
                "audio": len(audio_tracks),
                "assets": len(asset_tracks),
                "favorites": sum(1 for track in tracks if track.get("favorite")),
                "tagged": sum(1 for track in tracks if track.get("tags")),
                "untagged": sum(1 for track in tracks if not track.get("tags")),
            }
            for key in stats_keys:
                if key in ("favorites", "tagged", "untagged"):
                    continue
                stats[key] = sum(
                    float(snapshot.get("stats", {}).get(key) or 0)
                    for _, snapshot in source_snapshots
                )
            stats["total_duration"] = round(float(stats["total_duration"]), 3)
            stats["total_size"] = int(stats["total_size"])
            stats["scan_seconds"] = round(float(stats["scan_seconds"]), 2)
            stats["sources"] = len(source_snapshots)

            source_map = {str(source["id"]): source for source, _ in source_snapshots}
            self._id_map = {
                str(track["id"]): (
                    source_map[str(track["source_id"])],
                    str(track["id"])[len(str(track["source_id"])) + 1 :],
                )
                for track in tracks
            }

            return {
                "root": str(self.root),
                "name": self.name,
                "scanned_at": max((str(snapshot.get("scanned_at") or "") for _, snapshot in source_snapshots), default="") or _now_iso(),
                "tracks": tracks,
                "categories": definitions,
                "tags": Library._all_tags(tracks),
                "stats": stats,
                "warnings": warnings,
                "missing": missing,
                "duplicates": duplicate_groups,
                "sources": [
                    {
                        "id": str(source["id"]),
                        "name": str(source["display_name"]),
                        "path": str(source["path"]),
                        "count": int(source.get("count") or 0),
                        "exists": Path(str(source["path"])).is_dir(),
                        "missing": sum(
                            1
                            for item in missing
                            if str(item.get("source_id")) == str(source["id"])
                        ),
                    }
                    for source, _ in source_snapshots
                ],
            }

    # ------------------------------------------------------------------
    # Lookup / ID routing
    # ------------------------------------------------------------------

    def _lookup(self, track_id: str) -> Tuple[Dict[str, object], str]:
        pair = self._id_map.get(str(track_id))
        if pair:
            return pair
        self._rebuild_index()
        pair = self._id_map.get(str(track_id))
        if not pair:
            raise LibraryError("选中的素材已不在库中，请刷新后重试。")
        return pair

    def _route(self, ids: Iterable[str]) -> Dict[str, Tuple[Dict[str, object], List[str]]]:
        if isinstance(ids, str):
            ids = [ids]
        groups: Dict[str, Tuple[Dict[str, object], List[str]]] = {}
        for raw_id in ids:
            source, local_id = self._lookup(str(raw_id))
            sid = str(source["id"])
            if sid not in groups:
                groups[sid] = (source, [])
            groups[sid][1].append(local_id)
        return groups

    def get_track(self, track_id: str) -> Optional[Dict[str, object]]:
        try:
            source, local_id = self._lookup(track_id)
        except LibraryError:
            return None
        track = source["library"].get_track(local_id)
        return self._wrap_track(source, track) if track else None

    def stream_path(self, track_id: str) -> Optional[Path]:
        try:
            source, local_id = self._lookup(track_id)
        except LibraryError:
            return None
        return source["library"].stream_path(local_id)

    def asset_path(self, track_id: str) -> Optional[Path]:
        try:
            source, local_id = self._lookup(track_id)
        except LibraryError:
            return None
        return source["library"].asset_path(local_id)

    def thumb_path(self, track_id: str) -> Optional[Path]:
        try:
            source, local_id = self._lookup(track_id)
        except LibraryError:
            return None
        return source["library"].thumb_path(local_id)

    def cover(self, track_id: str):
        try:
            source, local_id = self._lookup(track_id)
        except LibraryError:
            return None
        return source["library"].cover(local_id)

    def inspect(self, track_id: str) -> Optional[Dict[str, object]]:
        try:
            source, local_id = self._lookup(track_id)
        except LibraryError:
            return None
        track = source["library"].inspect(local_id)
        return self._wrap_track(source, track) if track else None

    def motion(self, track_id: str):
        try:
            source, local_id = self._lookup(track_id)
        except LibraryError:
            return None
        return source["library"].motion(local_id)

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def _ensure_category(self, source: Dict[str, object], category: Dict[str, object]) -> None:
        library = source["library"]
        key = str(category.get("key") or "")
        if not key or key in library._category_map():
            return
        library._custom_categories.append(dict(category))
        library._save_state()
        library.scan()

    def add_tags(self, ids: Iterable[str], tags: Iterable[str]) -> Dict[str, object]:
        for _, (source, local_ids) in self._route(ids).items():
            source["library"].add_tags(local_ids, tags)
        return self.snapshot()

    def remove_tag(self, ids: Iterable[str], tag: str) -> Dict[str, object]:
        for _, (source, local_ids) in self._route(ids).items():
            source["library"].remove_tag(local_ids, tag)
        return self.snapshot()

    def set_tags(self, track_id: str, tags: Iterable[str]) -> Dict[str, object]:
        source, local_id = self._lookup(track_id)
        source["library"].set_tags(local_id, tags)
        return self.snapshot()

    def set_favorite(self, ids: Iterable[str], favorite: bool) -> Dict[str, object]:
        for _, (source, local_ids) in self._route(ids).items():
            source["library"].set_favorite(local_ids, favorite)
        return self.snapshot()

    def create_category(
        self, name: object, accent: object = "", parent: object = ""
    ) -> Dict[str, object]:
        if not self._sources:
            raise LibraryError("请先添加一个素材文件夹。")
        primary = self._sources[0]
        category = primary["library"].create_category(name, accent, parent)
        for source in self._sources[1:]:
            self._ensure_category(source, category)
        return dict(category)

    def set_category(self, ids: Iterable[str], category_key: object) -> Dict[str, object]:
        groups = self._route(ids)
        key = str(category_key or "")
        category = None
        if key not in ("", "auto"):
            snapshot = self.snapshot()
            category = next((item for item in snapshot["categories"] if str(item["key"]) == key), None)
            if not category:
                raise LibraryError("找不到这个分类。")
        for _, (source, local_ids) in groups.items():
            if category:
                self._ensure_category(source, category)
            source["library"].set_category(local_ids, key)
        return self.snapshot()

    def set_memberships(self, ids: Iterable[str], category_keys: object) -> Dict[str, object]:
        if not isinstance(category_keys, list):
            raise LibraryError("分类列表格式不正确。")
        groups = self._route(ids)
        available = {str(item["key"]) for item in self.snapshot()["categories"]}
        for key in category_keys:
            if not isinstance(key, str) or key not in available:
                raise LibraryError("找不到这个分类。")
        for _, (source, local_ids) in groups.items():
            source["library"].set_memberships(local_ids, category_keys)
        return self.snapshot()

    def remove_from_category(self, ids: Iterable[str], category_key: object) -> Dict[str, object]:
        for _, (source, local_ids) in self._route(ids).items():
            source["library"].remove_from_category(local_ids, category_key)
        return self.snapshot()

    def set_subcategory(self, ids: Iterable[str], subcategory_key: object) -> Dict[str, object]:
        for _, (source, local_ids) in self._route(ids).items():
            source["library"].set_subcategory(local_ids, subcategory_key)
        return self.snapshot()

    # ------------------------------------------------------------------
    # Rename
    # ------------------------------------------------------------------

    def _ordered_groups(self, ids: Iterable[str]) -> List[Tuple[Dict[str, object], List[str]]]:
        groups = self._route(ids)
        order = {str(source["id"]): index for index, source in enumerate(self._sources)}
        result = []
        for sid, (source, local_ids) in sorted(groups.items(), key=lambda item: order.get(item[0], 999)):
            ordered_ids = sorted(
                local_ids,
                key=lambda local_id: natural_key(str((source["library"].get_track(local_id) or {}).get("rel_path") or "")),
            )
            result.append((source, ordered_ids))
        return result

    def _public_plan_item(self, source: Dict[str, object], item: Dict[str, object]) -> Dict[str, object]:
        row = dict(item)
        row["id"] = f"{source['id']}-{item['id']}"
        if item.get("new_id"):
            row["new_id"] = f"{source['id']}-{item['new_id']}"
        prefix = str(source["display_name"])
        for key in ("old_rel_path", "new_rel_path"):
            if row.get(key):
                row[key] = f"{prefix}/{row[key]}"
        folder = str(row.get("folder") or "").strip("/\\")
        if folder and folder != ".":
            row["folder"] = f"{prefix}/{folder}"
        else:
            row["folder"] = prefix
        return row

    def preview_rename(self, ids: Iterable[str], base: str, start: int, digits: int, separator: str) -> Dict[str, object]:
        groups = self._ordered_groups(ids)
        cursor = start
        combined = None
        items: List[Dict[str, object]] = []
        conflicts = 0
        for source, local_ids in groups:
            plan = source["library"].preview_rename(local_ids, base, cursor, digits, separator)
            combined = combined or {key: plan[key] for key in ("ok", "base", "start", "digits", "separator")}
            combined["ok"] = bool(combined["ok"] and plan["ok"])
            conflicts += int(plan.get("conflicts") or 0)
            for item in plan.get("items") or []:
                items.append(self._public_plan_item(source, item))
            cursor += len(local_ids)
        if combined is None:
            raise LibraryError("请选择素材。")
        combined.update({"total": len(items), "conflicts": conflicts, "items": items})
        return combined

    def rename(self, ids: Iterable[str], base: str, start: int, digits: int, separator: str) -> Dict[str, object]:
        groups = self._ordered_groups(ids)
        cursor = start
        mappings: List[Dict[str, object]] = []
        items: List[Dict[str, object]] = []
        renamed = 0
        for source, local_ids in groups:
            result = source["library"].rename(local_ids, base, cursor, digits, separator)
            if not result.get("ok"):
                return result
            plan = result["plan"]
            for item in plan.get("items") or []:
                items.append(self._public_plan_item(source, item))
            for item in plan.get("mapping") or []:
                row = dict(item)
                for key in ("id", "new_id"):
                    if row.get(key):
                        row[key] = f"{source['id']}-{row[key]}"
                for key in ("old_rel_path", "new_rel_path"):
                    if row.get(key):
                        row[key] = f"{source['display_name']}/{row[key]}"
                mappings.append(row)
            renamed += int(plan.get("renamed") or 0)
            cursor += len(local_ids)
        snapshot = self.snapshot()
        return {
            "ok": True,
            "plan": {
                "ok": True,
                "base": base,
                "start": start,
                "digits": digits,
                "separator": separator,
                "total": len(items),
                "conflicts": 0,
                "items": items,
                "renamed": renamed,
                "mapping": mappings,
            },
        }

    def export_metadata(self) -> Dict[str, object]:
        with self._lock:
            sources = []
            for source in self._sources:
                data = source["library"].export_metadata()
                sources.append(
                    {
                        "source_id": source["id"],
                        "source_name": source["display_name"],
                        "root": str(source["path"]),
                        "tracks": data.get("tracks") or [],
                    }
                )
        return {"version": 1, "sources": sources}

    def import_metadata(self, metadata: object) -> Dict[str, object]:
        if not isinstance(metadata, dict):
            raise LibraryError("导入文件格式不正确。")
        groups = metadata.get("sources")
        if groups is None and isinstance(metadata.get("tracks"), list):
            groups = [{"source_id": "", "tracks": metadata["tracks"]}]
        if not isinstance(groups, list):
            raise LibraryError("导入文件里没有素材资料。")
        by_id = {str(source["id"]): source for source in self._sources}
        imported = 0
        skipped = 0
        touched = False
        for group in groups:
            if not isinstance(group, dict):
                continue
            source = by_id.get(str(group.get("source_id") or ""))
            if source is None:
                skipped += len(group.get("tracks") or [])
                continue
            result = source["library"].import_metadata({"tracks": group.get("tracks") or []})
            imported += int(result.get("imported") or 0)
            skipped += int(result.get("skipped") or 0)
            touched = True
        if not touched:
            raise LibraryError("导入文件没有匹配到当前素材库里的文件夹。")
        return {"imported": imported, "skipped": skipped, "library": self.snapshot()}

    def dismiss_missing(self, source_id: str, rel_paths: Iterable[str]) -> Dict[str, object]:
        for source in self._sources:
            if str(source["id"]) == str(source_id):
                source["library"].dismiss_missing(rel_paths)
                return self.snapshot()
        raise LibraryError("找不到这个素材文件夹。")

    def rescan(self, source_id: str = "") -> Dict[str, object]:
        if source_id:
            source = next((item for item in self._sources if str(item["id"]) == str(source_id)), None)
            if source is None:
                raise LibraryError("找不到这个素材文件夹。")
            source["library"].rescan()
        else:
            for source in self._sources:
                source["library"].rescan()
        return self.snapshot()
