from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal


UTC = timezone.utc
NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class SnapshotScheduleEntry:
    label: str
    target_at: datetime


class MarketCalendarService:
    def __init__(self) -> None:
        self._calendar = mcal.get_calendar("NYSE")

    def build_snapshot_targets(self, first_seen_at: datetime) -> list[SnapshotScheduleEntry]:
        if first_seen_at.tzinfo is None:
            raise ValueError("first_seen_at must be timezone-aware")

        local_seen = first_seen_at.astimezone(NEW_YORK)
        schedule = [
            SnapshotScheduleEntry(label="site_seen", target_at=first_seen_at.astimezone(UTC)),
            SnapshotScheduleEntry(label="plus_30m", target_at=(first_seen_at + timedelta(minutes=30)).astimezone(UTC)),
            SnapshotScheduleEntry(label="plus_3h", target_at=(first_seen_at + timedelta(hours=3)).astimezone(UTC)),
        ]

        for offset in range(1, 6):
            future_date = self._nth_trading_day_after(local_seen, offset)
            local_target = datetime.combine(future_date, local_seen.timetz().replace(tzinfo=None), tzinfo=NEW_YORK)
            schedule.append(
                SnapshotScheduleEntry(
                    label=f"plus_{offset}d",
                    target_at=local_target.astimezone(UTC),
                )
            )

        return schedule

    def _nth_trading_day_after(self, seen_local: datetime, offset: int):
        start_date = seen_local.date()
        end_date = start_date + timedelta(days=20)
        trading_days = self._calendar.schedule(start_date=start_date, end_date=end_date).index.date.tolist()
        future_days = [day for day in trading_days if day > start_date]
        if len(future_days) < offset:
            raise ValueError("Not enough trading days returned by calendar")
        return future_days[offset - 1]

