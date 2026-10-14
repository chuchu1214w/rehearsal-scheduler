from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker

from .config import ROOT
from .models import SCHEMA_VERSION, Base, Meta


# 版本 n → n+1 的迁移。只新增表时 create_all 已建好,登记为空操作即可;改列时在这里写 ALTER。
def _migrate_3_to_4(engine: Engine) -> None:
    """users 增加日历订阅令牌列。"""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(users)"))}
        if "calendar_token" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN calendar_token VARCHAR(64)"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_calendar_token ON users (calendar_token)"))


def _migrate_5_to_6(engine: Engine) -> None:
    """场次增加排练地点列。"""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(rehearsal_sessions)"))}
        if "location" not in cols:
            conn.execute(text("ALTER TABLE rehearsal_sessions ADD COLUMN location VARCHAR(200) NOT NULL DEFAULT ''"))


def _migrate_8_to_9(engine: Engine) -> None:
    """原生推送 token 记住 APNs 环境(生产 / 沙箱)。"""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(native_push_tokens)"))}
        if cols and "env" not in cols:
            conn.execute(text("ALTER TABLE native_push_tokens ADD COLUMN env VARCHAR(12)"))


def _migrate_10_to_11(engine: Engine) -> None:
    """排练表版本增加修改次数(revision)。schedule_operations 表由 create_all 新建。"""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(schedule_versions)"))}
        if "revision" not in cols:
            conn.execute(text("ALTER TABLE schedule_versions ADD COLUMN revision INTEGER NOT NULL DEFAULT 0"))


def _migrate_11_to_12(engine: Engine) -> None:
    """场次增加固定身份 uid(数据库 id 在删除后撤销时会变,SQLite 还会复用刚删掉的 id)。
    早期的修改记录只存了数据库 id;此前没有删除操作,记录引用的场次都还在:按 id 补上 uid 与身份。"""
    import json
    import uuid

    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(rehearsal_sessions)"))}
        if "uid" not in cols:
            conn.execute(text("ALTER TABLE rehearsal_sessions ADD COLUMN uid VARCHAR(32)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_rehearsal_sessions_uid ON rehearsal_sessions (uid)"))
        for (sid,) in conn.execute(text("SELECT id FROM rehearsal_sessions WHERE uid IS NULL")).all():
            conn.execute(text("UPDATE rehearsal_sessions SET uid = :u WHERE id = :i"), {"u": uuid.uuid4().hex, "i": sid})
        tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        if "schedule_operations" not in tables:
            return
        for op_id, raw in conn.execute(text("SELECT id, changes FROM schedule_operations")).all():
            changes = json.loads(raw) if isinstance(raw, str) else (raw or [])
            dirty = False
            for c in changes:
                if "uid" in c or "session_id" not in c:
                    continue
                row = conn.execute(
                    text("SELECT kind, song_id, task_no, uid FROM rehearsal_sessions WHERE id = :i"), {"i": c["session_id"]}
                ).first()
                if row is not None:
                    c.setdefault("key", {"kind": row[0], "song_id": row[1], "task_no": row[2]})
                    c["uid"] = row[3]
                    dirty = True
            if dirty:
                conn.execute(
                    text("UPDATE schedule_operations SET changes = :c WHERE id = :i"),
                    {"c": json.dumps(changes, ensure_ascii=False), "i": op_id},
                )
        # 「场次数 / 时长与方案不符」改为只提醒:清掉各版本里按旧规则保存的这类错误,否则会挡住发布
        for vid, raw in conn.execute(text("SELECT id, validation_errors FROM schedule_versions")).all():
            errors = json.loads(raw) if isinstance(raw, str) else (raw or [])
            kept = [e for e in errors if not (str(e).startswith("V-03 曲目") and "与方案" in str(e))]
            if kept != errors:
                conn.execute(
                    text("UPDATE schedule_versions SET validation_errors = :e WHERE id = :i"),
                    {"e": json.dumps(kept, ensure_ascii=False), "i": vid},
                )


def _migrate_12_to_13(engine: Engine) -> None:
    """AI 运行记录区分类型(无解时的调度员 / 用一句话修改某一版),并记下针对的版本与指令。"""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(advisor_runs)"))}
        if "kind" not in cols:
            conn.execute(text("ALTER TABLE advisor_runs ADD COLUMN kind VARCHAR(16) NOT NULL DEFAULT 'advisor'"))
        if "version_id" not in cols:
            conn.execute(text("ALTER TABLE advisor_runs ADD COLUMN version_id INTEGER"))
        if "instruction" not in cols:
            conn.execute(text("ALTER TABLE advisor_runs ADD COLUMN instruction TEXT NOT NULL DEFAULT ''"))


def _migrate_13_to_14(engine: Engine) -> None:
    """管理员确认后带着冲突发布:记下当时的冲突、说明、操作人。"""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(schedule_versions)"))}
        if "forced_publish" not in cols:
            conn.execute(text("ALTER TABLE schedule_versions ADD COLUMN forced_publish JSON"))


MIGRATIONS: dict[int, Callable[[Engine], None]] = {
    2: lambda engine: None,  # 2 → 3:新增 solve_jobs / schedule_versions / rehearsal_sessions
    3: _migrate_3_to_4,  # 3 → 4:users.calendar_token
    4: lambda engine: None,  # 4 → 5:新增 notifications(create_all 已建)
    5: _migrate_5_to_6,  # 5 → 6:rehearsal_sessions.location
    6: lambda engine: None,  # 6 → 7:新增 push_subscriptions(create_all 已建)
    7: lambda engine: None,  # 7 → 8:新增 native_push_tokens(create_all 已建)
    8: _migrate_8_to_9,  # 8 → 9:native_push_tokens.env
    9: lambda engine: None,  # 9 → 10:新增 advisor_runs(create_all 已建)
    10: _migrate_10_to_11,  # 10 → 11:schedule_versions.revision;新增 schedule_operations
    11: _migrate_11_to_12,  # 11 → 12:场次固定身份 uid;早期修改记录补上;清掉旧规则下的「场数不符」错误
    12: _migrate_12_to_13,  # 12 → 13:AI 运行记录类型(调度员 / 一句话修改)
    13: _migrate_13_to_14,  # 13 → 14:带冲突发布的记录
}


class SchemaOutdated(RuntimeError):
    pass


def resolve_sqlite_url(url: str) -> str:
    """相对路径的 SQLite 文件(如 sqlite:///data/app.db)一律相对于仓库根目录,与启动目录无关。"""
    if not url.startswith("sqlite:///"):
        return url
    path = url.removeprefix("sqlite:///")
    if not path or path == ":memory:":
        return url
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    return f"sqlite:///{p}"


def sqlite_path(url: str) -> Path | None:
    """SQLite 数据库文件的绝对路径;不是文件型 SQLite 时返回 None。"""
    url = resolve_sqlite_url(url)
    if not url.startswith("sqlite:///"):
        return None
    path = url.removeprefix("sqlite:///")
    if not path or path == ":memory:":
        return None
    return Path(path)


def make_engine(url: str) -> Engine:
    kwargs: dict = {}
    url = resolve_sqlite_url(url)
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        path = url.removeprefix("sqlite:///")
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    """建表并核对结构版本。

    开发阶段用 create_all;结构变化时 SCHEMA_VERSION +1,旧库会被拒绝启动并提示删除重建。
    有真实数据后改用 Alembic 迁移。
    """
    existing = inspect(engine).get_table_names()
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        row = db.scalar(select(Meta).where(Meta.key == "schema_version"))
        if row is None:
            # 全新库,或旧到还没有 meta 表的库
            if existing and "meta" not in existing:
                raise SchemaOutdated(_outdated_message(engine, "未知(早于版本 1)"))
            db.add(Meta(key="schema_version", value=str(SCHEMA_VERSION)))
            db.commit()
        elif row.value != str(SCHEMA_VERSION):
            found = int(row.value)
            if found > SCHEMA_VERSION:
                raise SchemaOutdated(_outdated_message(engine, row.value))
            while found < SCHEMA_VERSION:
                migrate = MIGRATIONS.get(found)
                if migrate is None:
                    raise SchemaOutdated(_outdated_message(engine, row.value))
                migrate(engine)
                found += 1
            row.value = str(SCHEMA_VERSION)
            db.commit()


def _outdated_message(engine: Engine, found: str) -> str:
    target = engine.url.database or "数据库"
    return (
        f"数据库结构版本不匹配:文件是 {found},程序需要 {SCHEMA_VERSION}。"
        f"开发阶段请删除 {target} 后重新启动(会重新建空库);有真实数据时请先备份再联系开发者迁移。"
    )
