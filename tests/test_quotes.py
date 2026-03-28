from datetime import datetime, timedelta, timezone
from decimal import Decimal

from insider_tracker.services.quotes import QuoteSample, classify_snapshot


def test_confirmed_when_both_quotes_are_fresh_and_close():
    target_at = datetime.now(timezone.utc)
    primary = QuoteSample(
        provider="a",
        status="ok",
        symbol="AAPL",
        fetched_at=target_at,
        price=Decimal("100"),
        quote_timestamp=target_at + timedelta(minutes=1),
    )
    secondary = QuoteSample(
        provider="b",
        status="ok",
        symbol="AAPL",
        fetched_at=target_at,
        price=Decimal("100.3"),
        quote_timestamp=target_at + timedelta(minutes=1),
    )

    status, consensus, effective_at, note = classify_snapshot(primary, secondary, target_at, threshold_pct=0.75)

    assert status == "confirmed"
    assert consensus == Decimal("100.15")
    assert effective_at == target_at + timedelta(minutes=1)
    assert note is None


def test_disputed_when_prices_diverge():
    target_at = datetime.now(timezone.utc)
    primary = QuoteSample(
        provider="a",
        status="ok",
        symbol="AAPL",
        fetched_at=target_at,
        price=Decimal("100"),
        quote_timestamp=target_at + timedelta(minutes=1),
    )
    secondary = QuoteSample(
        provider="b",
        status="ok",
        symbol="AAPL",
        fetched_at=target_at,
        price=Decimal("105"),
        quote_timestamp=target_at + timedelta(minutes=1),
    )

    status, consensus, _, note = classify_snapshot(primary, secondary, target_at, threshold_pct=0.75)

    assert status == "disputed"
    assert consensus is None
    assert "exceeded threshold" in note


def test_waiting_for_fresh_quote_when_only_stale_data_exists():
    target_at = datetime.now(timezone.utc)
    primary = QuoteSample(
        provider="a",
        status="ok",
        symbol="AAPL",
        fetched_at=target_at,
        price=Decimal("100"),
        quote_timestamp=target_at - timedelta(minutes=10),
    )
    secondary = QuoteSample(
        provider="b",
        status="provider_error",
        symbol="AAPL",
        fetched_at=target_at,
        error="down",
    )

    status, _, _, _ = classify_snapshot(primary, secondary, target_at, threshold_pct=0.75)

    assert status == "waiting_for_fresh_quote"

