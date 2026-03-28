from datetime import datetime, timedelta, timezone
from decimal import Decimal

from insider_tracker.services.quotes import QuoteSample, classify_single_source_snapshot


def test_confirmed_when_single_source_quote_is_at_or_after_target():
    target_at = datetime.now(timezone.utc)
    sample = QuoteSample(
        provider="yfinance",
        status="ok",
        symbol="AAPL",
        fetched_at=target_at,
        price=Decimal("100"),
        quote_timestamp=target_at + timedelta(minutes=1),
    )

    status, consensus, effective_at, note = classify_single_source_snapshot(sample, target_at)

    assert status == "confirmed"
    assert consensus == Decimal("100")
    assert effective_at == target_at + timedelta(minutes=1)
    assert "Single-source quote" in note


def test_waiting_when_quote_bar_is_still_before_target():
    target_at = datetime.now(timezone.utc)
    sample = QuoteSample(
        provider="yfinance",
        status="ok",
        symbol="AAPL",
        fetched_at=target_at,
        price=Decimal("100"),
        quote_timestamp=target_at - timedelta(minutes=1),
    )

    status, consensus, effective_at, note = classify_single_source_snapshot(sample, target_at)

    assert status == "waiting_for_source_bar"
    assert consensus is None
    assert effective_at is None
    assert "qualifying bar" in note


def test_waiting_when_source_has_not_published_bar_yet():
    target_at = datetime.now(timezone.utc)
    sample = QuoteSample(
        provider="yfinance",
        status="waiting_for_source_bar",
        symbol="AAPL",
        fetched_at=target_at,
        error="No 1-minute bar exists at or after the target time yet",
    )

    status, _, _, note = classify_single_source_snapshot(sample, target_at)

    assert status == "waiting_for_source_bar"
    assert "No 1-minute bar" in note


def test_failed_on_non_retriable_provider_status():
    target_at = datetime.now(timezone.utc)
    sample = QuoteSample(
        provider="yfinance",
        status="provider_error",
        symbol="AAPL",
        fetched_at=target_at,
        error="Bad payload",
    )

    status, _, _, note = classify_single_source_snapshot(sample, target_at)

    assert status == "failed"
    assert note == "Bad payload"
