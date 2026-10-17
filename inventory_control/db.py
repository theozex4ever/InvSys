from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from inventory_control.config import DB_PATH


def create_inventory_engine(db_path: str | Path | None = None) -> Engine:
    if db_path is None:
        path = DB_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{path}"
    elif str(db_path) == ":memory:":
        url = "sqlite:///:memory:"
    else:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{path}"

    engine = create_engine(url, future=True)

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        if url != "sqlite:///:memory:":
            cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()
        # SQLite's lower() folds ASCII only; searches use Python's Unicode case folding.
        dbapi_connection.create_function("py_casefold", 1, _casefold, deterministic=True)

    return engine


def _casefold(value: object) -> str | None:
    return None if value is None else str(value).casefold()


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
