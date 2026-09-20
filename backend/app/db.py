from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import sessionmaker

from .config import ROOT
from .models import Base


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
    # M1 用 create_all 建表;首次出现需要改表结构的里程碑(M2)起改用 Alembic 迁移。
    Base.metadata.create_all(engine)
