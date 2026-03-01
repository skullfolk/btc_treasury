"""
SQLite database schema and helpers using SQLAlchemy.
"""
import os
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, Float, String, DateTime, Boolean
)
from sqlalchemy.orm import DeclarativeBase, Session

DB_PATH = os.environ.get("DB_PATH", "/app/data/treasury.db")
DB_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DB_URL, connect_args={"check_same_thread": False})


class Base(DeclarativeBase):
    pass


class Snapshot(Base):
    __tablename__ = "snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    captured_at = Column(DateTime, default=datetime.utcnow, index=True)

    # Raw inputs
    btc_price = Column(Float)
    btc_amount = Column(Float)
    debt_usd = Column(Float)          # in USD
    preferred_usd = Column(Float)     # in USD
    cash_usd = Column(Float)          # in USD
    diluted_shares = Column(Float)
    current_price = Column(Float)     # MSTR share price

    # Calculated
    implied_price = Column(Float)
    btc_value_usd = Column(Float)
    equity_value_usd = Column(Float)
    discount_pct = Column(Float)
    is_undervalued = Column(Boolean)
    signal = Column(String(20))

    # Metadata
    data_date = Column(String(20))    # date string of the strategy.com data


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    Base.metadata.create_all(engine)


def save_snapshot(data: dict) -> int:
    with Session(engine) as session:
        snap = Snapshot(**{
            k: v for k, v in data.items()
            if k in Snapshot.__table__.columns.keys()
        })
        session.add(snap)
        session.commit()
        session.refresh(snap)
        return snap.id


def get_latest_snapshot() -> dict | None:
    with Session(engine) as session:
        row = (
            session.query(Snapshot)
            .order_by(Snapshot.captured_at.desc())
            .first()
        )
        if row is None:
            return None
        return _row_to_dict(row)


def get_history(limit: int = 90) -> list[dict]:
    with Session(engine) as session:
        rows = (
            session.query(Snapshot)
            .order_by(Snapshot.captured_at.desc())
            .limit(limit)
            .all()
        )
        return [_row_to_dict(r) for r in reversed(rows)]


def _row_to_dict(row: Snapshot) -> dict:
    return {
        "id": row.id,
        "captured_at": row.captured_at.isoformat() if row.captured_at else None,
        "btc_price": row.btc_price,
        "btc_amount": row.btc_amount,
        "debt_usd": row.debt_usd,
        "preferred_usd": row.preferred_usd,
        "cash_usd": row.cash_usd,
        "diluted_shares": row.diluted_shares,
        "current_price": row.current_price,
        "implied_price": row.implied_price,
        "btc_value_usd": row.btc_value_usd,
        "equity_value_usd": row.equity_value_usd,
        "discount_pct": row.discount_pct,
        "is_undervalued": row.is_undervalued,
        "signal": row.signal,
        "data_date": row.data_date,
    }
