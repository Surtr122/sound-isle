"""Command line entry point for Sound & Form."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Optional

from . import APP_NAME, APP_NAME_EN, __version__
from .server import create_server


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sound-and-form",
        description=f"{APP_NAME} / {APP_NAME_EN} — 一个安静、好看的本地声音与 3D 资产资料库。",
    )
    parser.add_argument("--library", "-l", help="启动时打开的素材文件夹。")
    parser.add_argument("--port", "-p", type=int, default=8765, help="本地端口（默认 8765，0 表示自动选择）。")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认只监听本机）。")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器。")
    parser.add_argument("--data-dir", help="自定义标签/收藏的保存目录。")
    parser.add_argument("--quiet", action="store_true", help="只输出必要信息。")
    parser.add_argument("--version", action="version", version=f"Sound & Form {__version__}")
    return parser


def main(argv: Optional[list] = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.data_dir:
        os.environ["SOUNDANDFORM_DATA_DIR"] = args.data_dir

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    root = args.library
    if not root:
        root = os.environ.get("SOUNDANDFORM_LIBRARY") or os.environ.get("SOUNDISLE_LIBRARY")

    try:
        server, state = create_server(
            root=root,
            host=args.host,
            port=args.port,
            quiet=args.quiet,
        )
    except OSError as exc:
        print(f"无法启动声形：{exc}", file=sys.stderr)
        if getattr(exc, "errno", None) == 48 or getattr(exc, "winerror", None) == 10048:
            print(f"端口 {args.port} 已被占用，可以用 --port 换一个端口。", file=sys.stderr)
        return 1

    actual_port = server.server_address[1]
    display_host = args.host
    if display_host in ("0.0.0.0", "::"):
        display_host = "127.0.0.1"
    url = f"http://{display_host}:{actual_port}"
    print(f"{APP_NAME} / {APP_NAME_EN}  v{__version__}")
    print(f"本地地址  {url}")
    if state.library:
        for path in state.library.paths:
            print(f"素材文件夹  {path}")
    elif state.error:
        print(f"提示  {state.error}")
    else:
        print("素材文件夹  尚未选择（在页面里打开一个文件夹）")
    print("按 Ctrl+C 停止")

    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
