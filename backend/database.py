"""
SQLite database schema and helpers using SQLAlchemy Core.

Schema:
  - snapshots: one row per company per refresh cycle
  - company column (MSTR | ASST | …) allows multi-company storage
  - DB migration: adds company column to existing tables automatically
"""
import logging
import os
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Float, Integer, String,
    create_engine, inspect, text
)
from sqlalchemy.orm import DeclarativeBase, Session

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", "/app/data/treasury.db")
DB_URL  = f"sqlite:///{DB_PATH}"

engine = create_engine(DB_URL, connect_args={"check_same_thread": False})


class Base(DeclarativeBase):
    pass


class Snapshot(Base):
    __tablename__ = "snapshots"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    company       = Column(String(10), nullable=False, default="MSTR", index=True)
    captured_at   = Column(DateTime, default=datetime.utcnow, index=True)

    # ── Raw inputs ────────────────────────────────────────────────────────────
    btc_price     = Column(Float)
    btc_amount    = Column(Float)
    debt_usd      = Column(Float)       # total debt, in USD
    preferred_usd = Column(Float)       # preferred stock, in USD
    cash_usd      = Column(Float)       # cash / USD reserve, in USD
    diluted_shares = Column(Float)      # fully diluted shares outstanding
    current_price  = Column(Float)      # market share price

    # ── Calculated ────────────────────────────────────────────────────────────
    implied_price    = Column(Float)
    btc_value_usd    = Column(Float)
    equity_value_usd = Column(Float)
    discount_pct     = Column(Float)
    is_undervalued   = Column(Boolean)
    signal           = Column(String(20))

    # ── Metadata ──────────────────────────────────────────────────────────────
    data_date = Column(String(40))      # date string from source


# ---------------------------------------------------------------------------
#  Lifecycle
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Create tables (if not exist) and run any needed column migrations."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    Base.metadata.create_all(engine)
    _migrate()


def _migrate() -> None:
    """
    Idempotent schema migrations — add columns that may not exist in older DBs.
    """
    inspector = inspect(engine)
    existing_cols = {c["name"] for c in inspector.get_columns("snapshots")}

    with engine.begin() as conn:
        # Add 'company' column to pre-v2 databases
        if "company" not in existing_cols:
            conn.execute(text("ALTER TABLE snapshots ADD COLUMN company TEXT DEFAULT 'MSTR'"))
            conn.execute(text("UPDATE snapshots SET company = 'MSTR' WHERE company IS NULL"))
            logger.info("Migration: added 'company' column to snapshots table.")


# ---------------------------------------------------------------------------
#  Write
# ---------------------------------------------------------------------------

def save_snapshot(data: dict, company: str = "MSTR") -> int:
    """Persist one snapshot row. Returns the new row id."""
    col_keys = set(Snapshot.__table__.columns.keys())
    row_data = {k: v for k, v in data.items() if k in col_keys}
    row_data["company"] = company.upper()

    with Session(engine) as session:
        snap = Snapshot(**row_data)
        session.add(snap)
        session.commit()
        session.refresh(snap)
        return snap.id


# ---------------------------------------------------------------------------
#  Read
# ---------------------------------------------------------------------------

def get_latest_snapshot(company: str = "MSTR") -> dict | None:
    company = company.upper()
    with Session(engine) as session:
        row = (
            session.query(Snapshot)
            .filter(Snapshot.company == company)
            .order_by(Snapshot.captured_at.desc())
            .first()
        )
        return _row_to_dict(row) if row else None


def get_history(company: str = "MSTR", limit: int = 90) -> list[dict]:
    company = company.upper()
    with Session(engine) as session:
        rows = (
            session.query(Snapshot)
            .filter(Snapshot.company == company)
            .order_by(Snapshot.captured_at.desc())
            .limit(limit)
            .all()
        )
        return [_row_to_dict(r) for r in reversed(rows)]


# ---------------------------------------------------------------------------
#  Serialisation
# ---------------------------------------------------------------------------

def _row_to_dict(row: Snapshot) -> dict:
    return {
        "id":              row.id,
        "company":         row.company,
        "captured_at":     row.captured_at.isoformat() if row.captured_at else None,
        "btc_price":       row.btc_price,
        "btc_amount":      row.btc_amount,
        "debt_usd":        row.debt_usd,
        "preferred_usd":   row.preferred_usd,
        "cash_usd":        row.cash_usd,
        "diluted_shares":  row.diluted_shares,
        "current_price":   row.current_price,
        "implied_price":   row.implied_price,
        "btc_value_usd":   row.btc_value_usd,
        "equity_value_usd": row.equity_value_usd,
        "discount_pct":    row.discount_pct,
        "is_undervalued":  row.is_undervalued,
        "signal":          row.signal,
        "data_date":       row.data_date,
    }
