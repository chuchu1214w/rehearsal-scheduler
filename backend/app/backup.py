"""SQLite 备份(§10.4):用 sqlite3 的在线备份 API 复制到 backups/ 目录,保留最近 N 天。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from .db import sqlite_path


def backup_sqlite(database_url: str, keep_days: int = 14, backups_dir: Path | None = None) -> Path | None:
    """返回备份文件路径;不是 SQLite 或数据库文件不存在时返回 None。"""
    src_path = sqlite_path(database_url)
    if src_path is None or not src_path.exists():
        return None
    out_dir = backups_dir or src_path.parent / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = out_dir / f"{src_path.stem}-{stamp}.db"
    src = sqlite3.connect(str(src_path))
    try:
        dst = sqlite3.connect(str(out))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    prune(out_dir, src_path.stem, keep_days)
    return out


def prune(out_dir: Path, stem: str, keep_days: int) -> int:
    """删除超过 keep_days 天的备份;keep_days <= 0 时不删。返回删除数。"""
    if keep_days <= 0:
        return 0
    cutoff = datetime.now() - timedelta(days=keep_days)
    removed = 0
    for f in out_dir.glob(f"{stem}-*.db"):
        try:
            stamp = datetime.strptime(f.name[len(stem) + 1 : -3], "%Y%m%d-%H%M%S")
        except ValueError:
            continue
        if stamp < cutoff:
            f.unlink(missing_ok=True)
            removed += 1
    return removed
