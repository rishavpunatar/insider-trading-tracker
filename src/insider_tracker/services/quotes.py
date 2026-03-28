from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import json

import httpx


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

    def fetch_quote(self, symbol: str) -> QuoteSample:
        raise NotImplementedError


class TwelveDataProvider(BaseQuoteProvider):
    provider_name = "twelvedata"

    def __init__(self, api_key: str | None, timeout_seconds: int = 20) -> None:
        self.api_key = api_key
        self._client = httpx.Client(timeout=timeout_seconds)

    def fetch_quote(self, symbol: str) -> QuoteSample:
        fetched_at = datetime.now(UTC)
        if not self.api_key:
            return QuoteSample(
                provider=self.provider_name,
                status="missing_api_key",
                symbol=symbol,
                fetched_at=fetched_at,
                error="TWELVEDATA_API_KEY is not configured",
            )

        try:
            response = self._client.get(
                "https://api.twelvedata.com/quote",
                params={"symbol": symbol, "apikey": self.api_key, "prepost": "true"},
            )
            response.raise_for_status()
            payload = response.json()
            if "code" in payload:
                return QuoteSample(
                    provider=self.provider_name,
                    status="provider_error",
                    symbol=symbol,
                    fetched_at=fetched_at,
                    error=payload.get("message") or payload.get("code"),
                    raw_payload=payload,
                )

            quote_timestamp = None
            if payload.get("last_quote_at"):
                quote_timestamp = datetime.fromtimestamp(int(payload["last_quote_at"]), tz=UTC)

            price_value = payload.get("close") or payload.get("price")
            return QuoteSample(
                provider=self.provider_name,
                status="ok",
                symbol=symbol,
                fetched_at=fetched_at,
                price=Decimal(str(price_value)) if price_value is not None else None,
                quote_timestamp=quote_timestamp,
                raw_payload=payload,
            )
        except Exception as exc:
            return QuoteSample(
                provider=self.provider_name,
                status="network_error",
                symbol=symbol,
                fetched_at=fetched_at,
                error=str(exc),
            )


class FinancialModelingPrepProvider(BaseQuoteProvider):
    provider_name = "fmp"

    def __init__(self, api_key: str | None, timeout_seconds: int = 20) -> None:
        self.api_key = api_key
        self._client = httpx.Client(timeout=timeout_seconds)

    def fetch_quote(self, symbol: str) -> QuoteSample:
        fetched_at = datetime.now(UTC)
        if not self.api_key:
            return QuoteSample(
                provider=self.provider_name,
                status="missing_api_key",
                symbol=symbol,
                fetched_at=fetched_at,
                error="FMP_API_KEY is not configured",
            )

        try:
            response = self._client.get(
                "https://financialmodelingprep.com/stable/quote",
                params={"symbol": symbol, "apikey": self.api_key},
            )
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict) and payload.get("Error Message"):
                return QuoteSample(
                    provider=self.provider_name,
                    status="provider_error",
                    symbol=symbol,
                    fetched_at=fetched_at,
                    error=payload["Error Message"],
                    raw_payload=payload,
                )
            if not isinstance(payload, list) or not payload:
                return QuoteSample(
                    provider=self.provider_name,
                    status="provider_error",
                    symbol=symbol,
                    fetched_at=fetched_at,
                    error="Empty quote payload",
                    raw_payload=payload if isinstance(payload, (dict, list)) else None,
                )

            row = payload[0]
            quote_timestamp = None
            if row.get("timestamp"):
                quote_timestamp = datetime.fromtimestamp(int(row["timestamp"]), tz=UTC)

            price_value = row.get("price")
            return QuoteSample(
                provider=self.provider_name,
                status="ok",
                symbol=symbol,
                fetched_at=fetched_at,
                price=Decimal(str(price_value)) if price_value is not None else None,
                quote_timestamp=quote_timestamp,
                raw_payload=row,
            )
        except Exception as exc:
            return QuoteSample(
                provider=self.provider_name,
                status="network_error",
                symbol=symbol,
                fetched_at=fetched_at,
                error=str(exc),
            )


def classify_snapshot(primary: QuoteSample, secondary: QuoteSample, target_at: datetime, threshold_pct: float) -> tuple[str, Decimal | None, datetime | None, str | None]:
    primary_fresh = _is_fresh(primary, target_at)
    secondary_fresh = _is_fresh(secondary, target_at)

    if primary_fresh and secondary_fresh and primary.price is not None and secondary.price is not None:
        difference_pct = _difference_percent(primary.price, secondary.price)
        if difference_pct <= Decimal(str(threshold_pct)):
            consensus = (primary.price + secondary.price) / Decimal("2")
            effective_at = max(primary.quote_timestamp, secondary.quote_timestamp)
            return "confirmed", consensus, effective_at, None
        return "disputed", None, max(primary.quote_timestamp, secondary.quote_timestamp), f"Difference {difference_pct:.4f}% exceeded threshold"

    if primary_fresh or secondary_fresh:
        return "pending_secondary", None, None, "Only one provider returned a fresh quote"

    if primary.status.endswith("error") and secondary.status.endswith("error"):
        return "failed", None, None, "Both providers returned errors"

    return "waiting_for_fresh_quote", None, None, "Providers have not yet returned a fresh quote"


def _is_fresh(sample: QuoteSample, target_at: datetime) -> bool:
    if sample.status != "ok" or sample.quote_timestamp is None or sample.price is None:
        return False
    return sample.quote_timestamp >= target_at


def _difference_percent(left: Decimal, right: Decimal) -> Decimal:
    baseline = (left + right) / Decimal("2")
    if baseline == 0:
        return Decimal("0")
    return abs(left - right) / baseline * Decimal("100")

