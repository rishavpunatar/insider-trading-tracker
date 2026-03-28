from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import logging
import threading
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from insider_tracker.config import Settings
from insider_tracker.models import InsiderFiling, QuoteObservation, SnapshotTarget, utcnow
from insider_tracker.services.market_calendar import MarketCalendarService
from insider_tracker.services.openinsider import OpenInsiderClient, OpenInsiderRow
from insider_tracker.services.quotes import (
    FinancialModelingPrepProvider,
    QuoteSample,
    TwelveDataProvider,
    classify_snapshot,
)
from insider_tracker.services.reference_data import SecurityReferenceService
from insider_tracker.services.sec import SecClient


logger = logging.getLogger(__name__)
UTC = timezone.utc
TERMINAL_SNAPSHOT_STATES = {"confirmed", "disputed", "failed", "skipped"}
ACTIVE_SNAPSHOT_STATES = {"pending", "waiting_for_fresh_quote", "pending_secondary"}


@dataclass
class DiscoveryResult:
    seen_rows: int
    new_filings: int
    filtered_filings: int
    verification_errors: int


@dataclass
class SnapshotRunResult:
    processed: int
    confirmed: int
    disputed: int
    pending: int
    failed: int


class TrackerService:
    def __init__(self, settings: Settings, session_factory) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.openinsider_client = OpenInsiderClient(user_agent=settings.http_user_agent)
        self.sec_client = SecClient(user_agent=settings.http_user_agent)
        self.calendar_service = MarketCalendarService()
        self.reference_service = SecurityReferenceService(
            cache_dir=settings.cache_dir,
            user_agent=settings.http_user_agent,
            twelvedata_api_key=settings.twelvedata_api_key,
        )
        self.primary_quote_provider = TwelveDataProvider(api_key=settings.twelvedata_api_key)
        self.secondary_quote_provider = FinancialModelingPrepProvider(api_key=settings.fmp_api_key)

    def run_discovery_cycle(self) -> DiscoveryResult:
        rows = self.openinsider_client.fetch_latest_rows(max_rows=self.settings.max_discovery_rows)
        result = DiscoveryResult(seen_rows=len(rows), new_filings=0, filtered_filings=0, verification_errors=0)
        now = utcnow()

        with self.session_factory() as session:
            for row in rows:
                if self._filing_exists(session, row.openinsider_row_key):
                    continue

                security = self.reference_service.ensure_security(session, row.symbol, row.company_name)
                verification = self.sec_client.verify_filing(row)
                filing = self._create_filing(session, row, security, verification.to_json(), verification.status, now)

                if not security.is_public_stock:
                    filing.tracking_status = "filtered_out"
                    result.filtered_filings += 1
                else:
                    filing.tracking_status = "tracking"
                    self._create_snapshot_targets(session, filing, now)

                if verification.status == "error":
                    result.verification_errors += 1

                session.add(filing)
                result.new_filings += 1

            session.commit()

        return result

    def process_due_snapshots(self) -> SnapshotRunResult:
        now = utcnow()
        result = SnapshotRunResult(processed=0, confirmed=0, disputed=0, pending=0, failed=0)

        with self.session_factory() as session:
            due_snapshots = session.scalars(
                select(SnapshotTarget)
                .options(selectinload(SnapshotTarget.filing), selectinload(SnapshotTarget.observations))
                .where(
                    SnapshotTarget.status.in_(ACTIVE_SNAPSHOT_STATES),
                    SnapshotTarget.target_at <= now,
                )
                .order_by(SnapshotTarget.target_at.asc())
                .limit(25)
            ).all()

            for snapshot in due_snapshots:
                result.processed += 1
                primary = self.primary_quote_provider.fetch_quote(snapshot.filing.symbol)
                secondary = self.secondary_quote_provider.fetch_quote(snapshot.filing.symbol)
                self._store_observation(session, snapshot, primary)
                self._store_observation(session, snapshot, secondary)

                snapshot.attempts += 1
                snapshot.last_attempted_at = now
                target_at = _ensure_aware(snapshot.target_at)
                status, consensus, effective_at, note = classify_snapshot(
                    primary,
                    secondary,
                    target_at,
                    self.settings.quote_dispute_threshold_pct,
                )

                if status in {"waiting_for_fresh_quote", "pending_secondary"} and now - target_at > timedelta(hours=24):
                    status = "failed"
                    note = "Snapshot timed out before both fresh quotes were available"

                snapshot.status = status
                snapshot.notes = note
                if effective_at is not None:
                    snapshot.effective_quote_at = effective_at
                if consensus is not None:
                    snapshot.consensus_price = consensus
                if status in TERMINAL_SNAPSHOT_STATES:
                    snapshot.completed_at = now

                if status == "confirmed":
                    result.confirmed += 1
                elif status == "disputed":
                    result.disputed += 1
                elif status == "failed":
                    result.failed += 1
                else:
                    result.pending += 1

                self._update_filing_completion(session, snapshot.filing)

            session.commit()

        return result

    def get_dashboard_data(self) -> dict[str, Any]:
        with self.session_factory() as session:
            filings = session.scalars(
                select(InsiderFiling)
                .options(
                    selectinload(InsiderFiling.snapshots).selectinload(SnapshotTarget.observations),
                    selectinload(InsiderFiling.security),
                )
                .order_by(InsiderFiling.first_seen_at.desc())
                .limit(50)
            ).all()

            summary = {
                "tracked_filings": session.scalar(
                    select(func.count()).select_from(InsiderFiling).where(InsiderFiling.tracking_status == "tracking")
                )
                or 0,
                "completed_filings": session.scalar(
                    select(func.count()).select_from(InsiderFiling).where(InsiderFiling.tracking_status == "completed")
                )
                or 0,
                "filtered_filings": session.scalar(
                    select(func.count()).select_from(InsiderFiling).where(InsiderFiling.tracking_status == "filtered_out")
                )
                or 0,
                "pending_snapshots": session.scalar(
                    select(func.count()).select_from(SnapshotTarget).where(SnapshotTarget.status.in_(ACTIVE_SNAPSHOT_STATES))
                )
                or 0,
                "disputed_snapshots": session.scalar(
                    select(func.count()).select_from(SnapshotTarget).where(SnapshotTarget.status == "disputed")
                )
                or 0,
            }

            return {
                "summary": summary,
                "filings": [self.serialize_filing(filing) for filing in filings],
            }

    def get_filing_detail(self, filing_id: int) -> dict[str, Any] | None:
        with self.session_factory() as session:
            filing = session.scalar(
                select(InsiderFiling)
                .options(
                    selectinload(InsiderFiling.snapshots).selectinload(SnapshotTarget.observations),
                    selectinload(InsiderFiling.security),
                )
                .where(InsiderFiling.id == filing_id)
            )
            if filing is None:
                return None
            return self.serialize_filing(filing, include_observations=True)

    def list_filings(self) -> list[dict[str, Any]]:
        return self.get_dashboard_data()["filings"]

    def _filing_exists(self, session: Session, row_key: str) -> bool:
        existing = session.scalar(select(InsiderFiling.id).where(InsiderFiling.openinsider_row_key == row_key))
        return existing is not None

    def _create_filing(
        self,
        session: Session,
        row: OpenInsiderRow,
        security,
        verification_details: str,
        verification_status: str,
        first_seen_at: datetime,
    ) -> InsiderFiling:
        filing = InsiderFiling(
            sec_filing_url=row.sec_filing_url,
            openinsider_row_key=row.openinsider_row_key,
            filing_datetime=row.filing_datetime,
            trade_date=row.trade_date,
            symbol=row.symbol,
            company_name=row.company_name,
            insider_name=row.insider_name,
            insider_title=row.insider_title,
            flag_code=row.flag_code,
            trade_type=row.trade_type,
            transaction_price=row.transaction_price,
            quantity=row.quantity,
            shares_owned=row.shares_owned,
            ownership_change_pct=row.ownership_change_pct,
            ownership_change_text=row.ownership_change_text,
            transaction_value=row.transaction_value,
            first_seen_at=first_seen_at,
            sec_verification_status=verification_status,
            sec_verification_details=verification_details,
            security_status=security.eligibility_status,
            raw_payload=row.to_json(),
            security_symbol=security.symbol,
        )
        session.add(filing)
        session.flush()
        return filing

    def _create_snapshot_targets(self, session: Session, filing: InsiderFiling, first_seen_at: datetime) -> None:
        for entry in self.calendar_service.build_snapshot_targets(first_seen_at):
            session.add(
                SnapshotTarget(
                    filing_id=filing.id,
                    label=entry.label,
                    target_at=entry.target_at,
                    status="pending",
                )
            )

    def _store_observation(self, session: Session, snapshot: SnapshotTarget, sample: QuoteSample) -> None:
        session.add(
            QuoteObservation(
                snapshot_id=snapshot.id,
                provider=sample.provider,
                status=sample.status,
                fetched_at=sample.fetched_at,
                quote_timestamp=sample.quote_timestamp,
                price=sample.price,
                error_message=sample.error,
                raw_payload=sample.to_json(),
            )
        )

    def _update_filing_completion(self, session: Session, filing: InsiderFiling) -> None:
        statuses = {snapshot.status for snapshot in filing.snapshots}
        if statuses and statuses.issubset(TERMINAL_SNAPSHOT_STATES):
            filing.tracking_status = "completed"
        session.add(filing)

    def serialize_filing(self, filing: InsiderFiling, include_observations: bool = False) -> dict[str, Any]:
        detail = json.loads(filing.sec_verification_details or "{}")
        snapshots = []
        for snapshot in sorted(filing.snapshots, key=lambda item: item.target_at):
            snapshot_payload = {
                "id": snapshot.id,
                "label": snapshot.label,
                "target_at": _iso(snapshot.target_at),
                "status": snapshot.status,
                "attempts": snapshot.attempts,
                "consensus_price": _decimal(snapshot.consensus_price),
                "effective_quote_at": _iso(snapshot.effective_quote_at),
                "notes": snapshot.notes,
            }
            if include_observations:
                snapshot_payload["observations"] = [
                    {
                        "provider": obs.provider,
                        "status": obs.status,
                        "fetched_at": _iso(obs.fetched_at),
                        "quote_timestamp": _iso(obs.quote_timestamp),
                        "price": _decimal(obs.price),
                        "error_message": obs.error_message,
                    }
                    for obs in sorted(snapshot.observations, key=lambda item: item.fetched_at, reverse=True)
                ]
            snapshots.append(snapshot_payload)

        latest_snapshot = max(filing.snapshots, key=lambda item: item.target_at, default=None)
        payload = {
            "id": filing.id,
            "symbol": filing.symbol,
            "company_name": filing.company_name,
            "insider_name": filing.insider_name,
            "insider_title": filing.insider_title,
            "trade_type": filing.trade_type,
            "transaction_price": _decimal(filing.transaction_price),
            "transaction_value": _decimal(filing.transaction_value),
            "quantity": filing.quantity,
            "trade_date": filing.trade_date.isoformat() if filing.trade_date else None,
            "filing_datetime": _iso(filing.filing_datetime),
            "first_seen_at": _iso(filing.first_seen_at),
            "tracking_status": filing.tracking_status,
            "security_status": filing.security_status,
            "sec_verification_status": filing.sec_verification_status,
            "sec_verification_details": detail,
            "sec_filing_url": filing.sec_filing_url,
            "latest_snapshot_status": latest_snapshot.status if latest_snapshot else None,
            "snapshots": snapshots,
        }

        if filing.security is not None:
            payload["security"] = {
                "exchange": filing.security.exchange,
                "instrument_type": filing.security.instrument_type,
                "eligibility_status": filing.security.eligibility_status,
                "eligibility_reason": filing.security.eligibility_reason,
            }
        else:
            payload["security"] = None

        return payload


class TrackerRuntime:
    def __init__(self, service: TrackerService) -> None:
        self.service = service
        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        if self._threads:
            return
        self._stop_event.clear()
        self._threads = [
            threading.Thread(
                target=self._run_loop,
                args=("discovery", self.service.settings.openinsider_poll_seconds, self.service.run_discovery_cycle),
                daemon=True,
            ),
            threading.Thread(
                target=self._run_loop,
                args=("snapshot-dispatcher", self.service.settings.due_snapshot_poll_seconds, self.service.process_due_snapshots),
                daemon=True,
            ),
        ]
        for thread in self._threads:
            thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        for thread in self._threads:
            thread.join(timeout=2)
        self._threads = []

    def _run_loop(self, name: str, interval_seconds: int, fn) -> None:
        while not self._stop_event.is_set():
            try:
                result = fn()
                logger.info("%s cycle completed: %s", name, result)
            except Exception:
                logger.exception("%s cycle failed", name)
            self._stop_event.wait(interval_seconds)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _ensure_aware(value).astimezone(UTC).isoformat()


def _decimal(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
