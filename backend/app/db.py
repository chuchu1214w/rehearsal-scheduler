from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event, inspect, select
from sqlalchemy.orm import Session, sessionmaker

from .config import ROOT
from .models import SCHEMA_VERSION, Base, Meta


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
            raise SchemaOutdated(_outdated_message(engine, row.value))


def _outdated_message(engine: Engine, found: str) -> str:
    target = engine.url.database or "数据库"
    return (
        f"数据库结构版本不匹配:文件是 {found},程序需要 {SCHEMA_VERSION}。"
        f"开发阶段请删除 {target} 后重新启动(会重新建空库);有真实数据时请先备份再联系开发者迁移。"
    )
