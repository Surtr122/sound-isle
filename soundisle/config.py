"""Application paths and small JSON helpers.

Sound & Form never writes inside the media library. User data (favourites,
tags, the last opened folder) lives in the platform's application-data
directory, or in ``SOUNDANDFORM_DATA_DIR`` when that variable is set.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional


APP_DIR_NAME = "SoundAndForm"


def data_dir() -> Path:
    """Return the per-user data directory, creating it if necessary."""
    override = os.environ.get("SOUNDANDFORM_DATA_DIR") or os.environ.get("SOUNDISLE_DATA_DIR")
    if override:
        path = Path(override).expanduser()
    elif sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        path = Path(base) / APP_DIR_NAME
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        path = Path(base) / "sound-and-form"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return data_dir() / "config.json"


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def write_json(path: Path, data: Dict[str, Any]) -> None:
    _atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else None
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return None


def load_config() -> Dict[str, Any]:
    data = read_json(config_path()) or {}
    recents = data.get("recent_libraries")
    if not isinstance(recents, list):
        recents = []
    clean_recents = []
    for item in recents:
        if isinstance(item, str) and item and item not in clean_recents:
            clean_recents.append(item)
    last = data.get("last_library")
    if not isinstance(last, str):
        last = ""
    sources = data.get("workspace_sources")
    if not isinstance(sources, list):
        sources = []
    clean_sources = []
    for item in sources:
        if isinstance(item, str) and item and item not in clean_sources:
            clean_sources.append(item)
    return {
        "version": 2,
        "last_library": last,
        "recent_libraries": clean_recents[:8],
        "workspace_sources": clean_sources[:24],
    }


def save_config(config: Dict[str, Any]) -> None:
    write_json(config_path(), config)


def remember_library(root: Path) -> None:
    config = load_config()
    value = str(root)
    config["last_library"] = value
    recents = [item for item in config["recent_libraries"] if item != value]
    recents.insert(0, value)
    config["recent_libraries"] = recents[:8]
    save_config(config)


def remember_workspace(paths: list[Path]) -> None:
    """Persist the ordered list of folders in the current workspace."""
    config = load_config()
    values = [str(path) for path in paths]
    config["workspace_sources"] = values
    if values:
        config["last_library"] = values[0]
        recents = [item for item in config["recent_libraries"] if item not in values]
        recents = (values + recents)[:8]
        config["recent_libraries"] = recents
    save_config(config)


def library_key(root: Path) -> str:
    """Stable key for one library, independent of unnecessary path noise."""
    normalised = os.path.normcase(os.path.realpath(str(root)))
    return hashlib.sha1(normalised.encode("utf-8")).hexdigest()[:20]


def library_state_path(root: Path) -> Path:
    folder = data_dir() / "libraries"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / (library_key(root) + ".json")
