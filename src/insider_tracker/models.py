from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TickerSecurity(Base):
    __tablename__ = "ticker_securities"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    company_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    cik: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    exchange: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    instrument_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    is_public_stock: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    eligibility_status: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    eligibility_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    filings: Mapped[list["InsiderFiling"]] = relationship(back_populates="security")


class InsiderFiling(Base):
    __tablename__ = "insider_filings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sec_filing_url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    openinsider_row_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    filing_datetime: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    trade_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    insider_name: Mapped[str] = mapped_column(String(255), nullable=False)
    insider_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    flag_code: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    trade_type: Mapped[str] = mapped_column(String(64), nullable=False)
    transaction_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)
    quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    shares_owned: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ownership_change_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    ownership_change_text: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    transaction_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    tracking_status: Mapped[str] = mapped_column(String(32), default="new", nullable=False)
    sec_verification_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    sec_verification_details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    security_status: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    raw_payload: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    security_symbol: Mapped[Optional[str]] = mapped_column(ForeignKey("ticker_securities.symbol"), nullable=True)
    security: Mapped[Optional[TickerSecurity]] = relationship(back_populates="filings")
    snapshots: Mapped[list["SnapshotTarget"]] = relationship(back_populates="filing", cascade="all, delete-orphan")


class SnapshotTarget(Base):
    __tablename__ = "snapshot_targets"
    __table_args__ = (UniqueConstraint("filing_id", "label", name="uq_snapshot_label_per_filing"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    filing_id: Mapped[int] = mapped_column(ForeignKey("insider_filings.id"), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(32), nullable=False)
    target_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_attempted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_quote_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    consensus_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    filing: Mapped[InsiderFiling] = relationship(back_populates="snapshots")
    observations: Mapped[list["QuoteObservation"]] = relationship(back_populates="snapshot", cascade="all, delete-orphan")


class QuoteObservation(Base):
    __tablename__ = "quote_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshot_targets.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    quote_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    snapshot: Mapped[SnapshotTarget] = relationship(back_populates="observations")
