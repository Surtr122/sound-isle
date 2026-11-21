"""Safe batch renaming for audio files.

The rename engine is intentionally conservative:

* only the base name changes, the folder and extension stay untouched;
* the whole batch is previewed before anything is written;
* renames run in two phases through unique temporary names so swaps and
  cyclic names cannot destroy a file;
* a failure rolls the batch back as far as the filesystem allows.
"""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


class RenameError(ValueError):
    """A user-facing rename problem."""


_ILLEGAL = '<>:"/\\|?*'
_CONTROL = re.compile(r"[\x00-\x1f]")
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True)
class RenameOptions:
    base: str
    start: int = 1
    digits: int = 2
    separator: str = " "


def natural_key(value: str) -> Tuple:
    """Natural, case-insensitive sort key (track 2 before track 10)."""
    parts = re.split(r"(\d+)", value.casefold())
    return tuple((0, int(part)) if part.isdigit() else (1, part) for part in parts)


def validate_options(base: str, start: int, digits: int, separator: str) -> RenameOptions:
    base = (base or "").strip()
    if not base:
        raise RenameError("请先输入统一名称。")
    bad = sorted({char for char in base if char in _ILLEGAL or char in "\r\n\t"})
    if bad:
        raise RenameError("统一名称不能包含这些字符：" + " ".join(bad))
    base = _CONTROL.sub("", base)
    base = _SPACES.sub(" ", base).strip(" .")
    if not base:
        raise RenameError("统一名称不能只有空格或点。")
    if len(base) > 80:
        raise RenameError("统一名称最多 80 个字符，请缩短一点。")

    try:
        start = int(start)
        digits = int(digits)
    except (TypeError, ValueError):
        raise RenameError("起始编号和位数必须是整数。") from None
    if start < 0 or start > 999999:
        raise RenameError("起始编号需在 0 到 999999 之间。")
    if digits < 1 or digits > 6:
        raise RenameError("编号位数需在 1 到 6 之间。")

    separator = separator or ""
    if len(separator) > 4:
        raise RenameError("分隔符最多 4 个字符。")
    if any(char in _ILLEGAL or char in "\r\n\t" for char in separator):
        raise RenameError("分隔符不能包含斜杠、冒号等文件名字符。")
    return RenameOptions(base=base, start=start, digits=digits, separator=separator)


def build_plan(files: Sequence[Dict[str, str]], options: RenameOptions) -> Dict[str, object]:
    """Create a dry-run plan.

    ``files`` entries need ``id``, ``rel_path``, ``path`` and ``filename``.
    """
    ordered = sorted(files, key=lambda item: natural_key(item["rel_path"]))
    if not ordered:
        raise RenameError("请先选择要重命名的素材。")

    selected_paths = {os.path.normcase(os.path.abspath(item["path"])) for item in ordered}
    target_seen: Dict[str, Dict[str, object]] = {}
    items: List[Dict[str, object]] = []

    for index, item in enumerate(ordered):
        source = os.path.abspath(item["path"])
        old_name = item["filename"]
        suffix = PurePosixPath(old_name).suffix
        number = options.start + index
        new_name = f"{options.base}{options.separator}{number:0{options.digits}d}{suffix}"
        new_rel = str(PurePosixPath(item["rel_path"]).with_name(new_name))
        target = os.path.join(os.path.dirname(source), new_name)
        target_key = os.path.normcase(os.path.abspath(target))
        row: Dict[str, object] = {
            "id": item["id"],
            "old_rel_path": item["rel_path"],
            "new_rel_path": new_rel,
            "old_name": old_name,
            "new_name": new_name,
            "folder": str(PurePosixPath(item["rel_path"]).parent),
            "source": source,
            "target": target,
            "ok": True,
            "error": "",
            "warning": "",
        }

        if not os.path.isfile(source):
            row["ok"] = False
            row["error"] = "源文件已不存在。"
        elif not suffix:
            row["ok"] = False
            row["error"] = "文件缺少扩展名，无法安全重命名。"
        elif len(os.path.basename(target)) > 180:
            row["ok"] = False
            row["error"] = "生成的文件名过长。"

        if target_key in target_seen:
            other = target_seen[target_key]
            row["ok"] = False
            row["error"] = f"与「{other['new_name']}」的目标名称重复。"
            if other.get("ok"):
                other["ok"] = False
                other["error"] = f"与「{new_name}」的目标名称重复。"
        else:
            target_seen[target_key] = row

        if row["ok"] and os.path.exists(target):
            same_file = target_key == os.path.normcase(source)
            if not same_file and target_key not in selected_paths:
                row["ok"] = False
                row["error"] = "目标位置已有同名文件。"
            elif not same_file:
                # Another selected file currently owns this name.  That is
                # fine: phase one vacates every source before phase two.
                pass

        if row["ok"] and len(target) > 250:
            row["warning"] = "路径接近 Windows 长度限制，重命名后可能不易访问。"

        items.append(row)

    conflicts = sum(1 for row in items if not row["ok"])
    return {
        "ok": conflicts == 0,
        "base": options.base,
        "start": options.start,
        "digits": options.digits,
        "separator": options.separator,
        "total": len(items),
        "conflicts": conflicts,
        "items": items,
    }


def apply_plan(plan: Dict[str, object]) -> Dict[str, object]:
    """Execute a previously previewed plan, with rollback on failure."""
    items = plan.get("items")
    if not isinstance(items, list) or not items:
        raise RenameError("没有可执行的更名计划。")
    if not plan.get("ok"):
        raise RenameError("计划中仍有冲突，请先处理。")

    # Phase 1: move every source to a unique temporary name.
    moved: List[Tuple[Dict[str, object], str]] = []
    try:
        for row in items:
            source = str(row["source"])
            target = str(row["target"])
            if source == target:
                continue
            temp = os.path.join(
                os.path.dirname(source),
                f".{os.path.basename(source)}.soundisle-{uuid.uuid4().hex[:10]}.tmp",
            )
            os.rename(source, temp)
            row["_temp"] = temp
            moved.append((row, temp))
    except OSError as exc:
        _rollback_back(moved)
        raise RenameError(f"准备重命名时失败，已尽量还原：{exc}") from None

    # Phase 2: move temporaries to their final names.
    completed: List[Dict[str, object]] = []
    try:
        for row in items:
            source = str(row["source"])
            target = str(row["target"])
            if source == target:
                completed.append(row)
                continue
            temp = str(row["_temp"])
            if os.path.exists(target):
                raise OSError(f"目标文件突然出现：{os.path.basename(target)}")
            os.rename(temp, target)
            completed.append(row)
    except OSError as exc:
        # Best effort: put finished files back and return temporaries to their
        # original names.  We report anything that could not be restored.
        problems: List[str] = []
        for row in completed:
            source = str(row["source"])
            target = str(row["target"])
            if source == target:
                continue
            try:
                if os.path.exists(target):
                    os.rename(target, source)
            except OSError as rollback_exc:
                problems.append(f"{os.path.basename(target)} → {os.path.basename(source)}: {rollback_exc}")
        for row, temp in moved:
            if row in completed:
                continue
            try:
                if os.path.exists(temp):
                    os.rename(temp, str(row["source"]))
            except OSError as rollback_exc:
                problems.append(f"{os.path.basename(temp)} → {os.path.basename(str(row['source']))}: {rollback_exc}")
        message = f"重命名失败，已尽量还原：{exc}"
        if problems:
            message += "；以下文件需手动检查：" + "；".join(problems[:4])
        raise RenameError(message) from None
    finally:
        for row in items:
            row.pop("_temp", None)

    mapping = [
        {
            "id": row["id"],
            "old_rel_path": row["old_rel_path"],
            "new_rel_path": row["new_rel_path"],
            "old_name": row["old_name"],
            "new_name": row["new_name"],
        }
        for row in items
    ]
    return {"renamed": len(mapping), "mapping": mapping}


def _rollback_back(moved: Iterable[Tuple[Dict[str, object], str]]) -> None:
    for row, temp in reversed(list(moved)):
        try:
            if os.path.exists(temp) and not os.path.exists(str(row["source"])):
                os.rename(temp, str(row["source"]))
        except OSError:
            pass
