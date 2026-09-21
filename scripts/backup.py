#!/usr/bin/env python3
"""手动备份 SQLite 数据库到 <data 目录>/backups/,并清理超过 N 天的旧备份。

用法:
    python scripts/backup.py            # 用 DATABASE_URL(默认 data/app.db)
    python scripts/backup.py --keep 30  # 保留 30 天
服务本身也会每天自动做一次同样的备份(BACKUP_KEEP_DAYS,默认 14;0 = 关闭)。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.backup import backup_sqlite  # noqa: E402
from app.config import Settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", type=int, default=14, help="保留天数")
    args = parser.parse_args()
    settings = Settings.from_env()
    out = backup_sqlite(settings.database_url, keep_days=args.keep)
    if out is None:
        print("不是 SQLite 数据库或文件不存在,未备份")
        return 1
    print(f"已备份到 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
