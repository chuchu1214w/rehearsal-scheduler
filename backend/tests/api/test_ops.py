"""M7:健康检查与 SQLite 备份。"""

import sqlite3
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.backup import backup_sqlite, prune


def test_health(anon: TestClient):
    r = anon.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["schema_version"] >= 5


def test_backup_and_prune(tmp_path, settings, admin: TestClient):
    out = backup_sqlite(settings.database_url, keep_days=14)
    assert out is not None and out.exists() and out.parent.name == "backups"
    # 备份是完整可打开的数据库,包含管理员账号
    con = sqlite3.connect(str(out))
    assert con.execute("select count(*) from users").fetchone()[0] == 1
    con.close()
    # 造一个 20 天前的旧备份 → 清理掉;新的保留
    stem = out.name.split("-")[0]
    old = out.parent / f"{stem}-{(datetime.now() - timedelta(days=20)).strftime('%Y%m%d-%H%M%S')}.db"
    old.write_bytes(b"x")
    assert prune(out.parent, stem, 14) == 1
    assert not old.exists() and out.exists()
    assert backup_sqlite("postgresql://x/y") is None
