from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import logging
from pathlib import Path

import pandas as pd
import yfinance as yf


UTC = timezone.utc


@dataclass
class QuoteSample:
    provider: str
    status: str
    symbol: str
    fetched_at: datetime
    price: Decimal | None = None
    quote_timestamp: datetime | None = None
    error: str | None = None
    raw_payload: dict | list | None = None

    def to_json(self) -> str | None:
        if self.raw_payload is None:
            return None
        return json.dumps(self.raw_payload, sort_keys=True, default=str)


class BaseQuoteProvider:
    provider_name = "base"

    def fetch_quote_at(self, symbol: str, target_at: datetime) -> QuoteSample:
        raise NotImplementedError


class YahooFinanceProvider(BaseQuoteProvider):
    provider_name = "yfinance"

    def __init__(self, cache_dir: Path) -> None:
        tz_cache = cache_dir / "yfinance_tz"
        tz_cache.mkdir(parents=True, exist_ok=True)
        logging.getLogger("yfinance").setLevel(logging.ERROR)
        yf.set_tz_cache_location(str(tz_cache))

    def fetch_quote_at(self, symbol: str, target_at: datetime) -> QuoteSample:
        fetched_at = datetime.now(UTC)
        normalized_target = _ensure_aware(target_at)

        try:
            history = yf.Ticker(symbol).history(
                start=normalized_target - timedelta(minutes=2),
                end=normalized_target + timedelta(hours=36),
                interval="1m",
                prepost=True,
                auto_adjust=False,
                actions=False,
            )

            if history.empty:
                return QuoteSample(
                    provider=self.provider_name,
                    status="waiting_for_source_bar",
                    symbol=symbol,
                    fetched_at=fetched_at,
                    error="Yahoo Finance returned no 1-minute bars for the requested window",
                )

            matching_row = _first_bar_at_or_after(history, normalized_target)
            if matching_row is None:
                return QuoteSample(
                    provider=self.provider_name,
                    status="waiting_for_source_bar",
                    symbol=symbol,
                    fetched_at=fetched_at,
                    error="No 1-minute bar exists at or after the target time yet",
                    raw_payload={"row_count": len(history)},
                )

            bar_timestamp = _normalize_index_timestamp(matching_row.name)
            price_value = matching_row["Open"]
            if pd.isna(price_value):
                price_value = matching_row["Close"]
            if pd.isna(price_value):
                return QuoteSample(
                    provider=self.provider_name,
                    status="waiting_for_source_bar",
                    symbol=symbol,
                    fetched_at=fetched_at,
                    error="Selected Yahoo Finance bar did not contain a usable price",
                )

            return QuoteSample(
                provider=self.provider_name,
                status="ok",
                symbol=symbol,
                fetched_at=fetched_at,
                price=Decimal(str(price_value)) if price_value is not None else None,
                quote_timestamp=bar_timestamp,
                raw_payload={
                    "interval": "1m",
                    "bar_timestamp": bar_timestamp.isoformat(),
                    "open": None if pd.isna(matching_row["Open"]) else float(matching_row["Open"]),
                    "close": None if pd.isna(matching_row["Close"]) else float(matching_row["Close"]),
                    "high": None if pd.isna(matching_row["High"]) else float(matching_row["High"]),
                    "low": None if pd.isna(matching_row["Low"]) else float(matching_row["Low"]),
                    "volume": None if pd.isna(matching_row["Volume"]) else int(matching_row["Volume"]),
                },
            )
        except Exception as exc:
            return QuoteSample(
                provider=self.provider_name,
                status="network_error",
                symbol=symbol,
                fetched_at=fetched_at,
                error=str(exc),
            )


def classify_single_source_snapshot(sample: QuoteSample, target_at: datetime) -> tuple[str, Decimal | None, datetime | None, str | None]:
    normalized_target = _ensure_aware(target_at)

    if sample.status == "ok" and sample.quote_timestamp is not None and sample.price is not None:
        if sample.quote_timestamp >= normalized_target:
            return "confirmed", sample.price, sample.quote_timestamp, f"Single-source quote from {sample.provider}"
        return "waiting_for_source_bar", None, None, "A qualifying bar has not been published yet"

    if sample.status in {"waiting_for_source_bar", "network_error"}:
        return "waiting_for_source_bar", None, None, sample.error

    return "failed", None, None, sample.error


def _first_bar_at_or_after(history: pd.DataFrame, target_at: datetime):
    index = history.index
    if index.tz is None:
        history.index = index.tz_localize(UTC)
    else:
        history.index = index.tz_convert(UTC)

    filtered = history.loc[history.index >= target_at]
    if filtered.empty:
        return None
    return filtered.iloc[0]


def _normalize_index_timestamp(value) -> datetime:
    timestamp = value.to_pydatetime() if hasattr(value, "to_pydatetime") else value
    return _ensure_aware(timestamp)


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
