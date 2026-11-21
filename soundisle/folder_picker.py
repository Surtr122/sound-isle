"""Tiny OS bridges: choosing a folder and revealing files."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


_PICK_SCRIPT = r"""
import sys
try:
    import tkinter as tk
    from tkinter import filedialog
except Exception as exc:
    print("TK_ERROR:" + str(exc), file=sys.stderr)
    raise SystemExit(2)
root = tk.Tk()
root.withdraw()
try:
    root.attributes("-topmost", True)
except Exception:
    pass
initial = sys.argv[2] if len(sys.argv) > 2 else ""
path = filedialog.askdirectory(title=sys.argv[1] if len(sys.argv) > 1 else "选择文件夹",
                               initialdir=initial or None, mustexist=True)
root.destroy()
print(path or "")
"""


@dataclass
class FolderChoice:
    path: Optional[str] = None
    cancelled: bool = False
    error: str = ""


def pick_folder(title: str = "选择音乐文件夹", initial_dir: str = "") -> FolderChoice:
    """Open a native folder dialog in a child process.

    Running Tk in a child keeps the HTTP server thread free of GUI toolkit
    rules and makes cancellation/failure easy to report.
    """
    command = [sys.executable, "-c", _PICK_SCRIPT, title, initial_dir]
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired:
        return FolderChoice(error="文件夹选择窗口超时了，请重试。")
    except OSError as exc:
        return FolderChoice(error=f"无法打开文件夹选择窗口：{exc}")

    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()
        message = detail[-1] if detail else "系统没有可用的文件夹选择窗口。"
        if message.startswith("TK_ERROR:"):
            message = "当前 Python 没有 Tk 图形界面，请直接输入文件夹路径。"
        return FolderChoice(error=message)

    selected = ""
    for line in reversed((completed.stdout or "").splitlines()):
        if line.strip():
            selected = line.strip()
            break
    if not selected:
        return FolderChoice(cancelled=True)
    path = Path(selected)
    if not path.is_dir():
        return FolderChoice(error="选择的路径不是一个文件夹。")
    return FolderChoice(path=str(path))


def reveal(path: str, select_file: bool = False) -> None:
    """Reveal a file/folder in the platform file manager (best effort)."""
    target = str(Path(path))
    try:
        if sys.platform == "win32":
            if select_file and os.path.isfile(target):
                subprocess.Popen(["explorer", "/select,", target])
            else:
                os.startfile(target)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            args = ["open", "-R", target] if select_file else ["open", target]
            subprocess.Popen(args)
        else:
            folder = os.path.dirname(target) if select_file else target
            subprocess.Popen(["xdg-open", folder])
    except OSError:
        pass
