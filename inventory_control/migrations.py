from datetime import datetime

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from inventory_control.orm import Base, LocationRecord, SettingRecord


DEFAULT_LOCATIONS = ["Receiving", "Stock", "Shipping Bench", "Scrap"]
SCHEMA_VERSION = "1"


def bootstrap_database(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    with Session(engine, future=True) as session:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        for name in DEFAULT_LOCATIONS:
            exists = session.scalar(select(LocationRecord).where(LocationRecord.name == name))
            if exists is None:
                session.add(LocationRecord(name=name, active=True, created_at=now))
        setting = session.get(SettingRecord, "schema_version")
        if setting is None:
            session.add(SettingRecord(key="schema_version", value=SCHEMA_VERSION))
        session.commit()
