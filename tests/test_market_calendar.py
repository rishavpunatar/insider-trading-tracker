from datetime import datetime, timezone

from insider_tracker.services.market_calendar import MarketCalendarService


def test_trading_day_offsets_skip_weekend_and_holiday():
    service = MarketCalendarService()
    first_seen = datetime(2026, 3, 27, 22, 0, tzinfo=timezone.utc)

    targets = {item.label: item.target_at for item in service.build_snapshot_targets(first_seen)}

    assert targets["plus_1d"].date().isoformat() == "2026-03-30"
    assert targets["plus_2d"].date().isoformat() == "2026-03-31"
    assert targets["plus_5d"].date().isoformat() == "2026-04-06"

