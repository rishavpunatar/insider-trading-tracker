from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from insider_tracker.models import TickerSecurity


UTC = timezone.utc
ALLOWED_TYPES = {
    "Common Stock",
    "American Depositary Receipt",
    "Depositary Receipt",
    "REIT",
}
BLOCKED_TYPE_TERMS = {
    "ETF",
    "Mutual Fund",
    "Closed-End Fund",
    "Trust",
    "Preferred Stock",
    "Warrant",
    "Right",
    "Unit",
}
BLOCKED_NAME_TERMS = (
    " fund",
    " trust",
    " etf",
    " portfolio",
    " income fund",
    " municipal",
    " warrant",
    " rights",
    " unit",
    " preferred",
)


class SecTickerDirectory:
    def __init__(self, cache_dir: Path, user_agent: str, timeout_seconds: int = 20) -> None:
        self.cache_path = cache_dir / "company_tickers_exchange.json"
        self._client = httpx.Client(timeout=timeout_seconds, headers={"User-Agent": user_agent})
        self._memory_cache: dict[str, dict] | None = None

    def lookup(self, symbol: str) -> dict | None:
        data = self._load_data()
        return data.get(symbol.upper())

    def _load_data(self) -> dict[str, dict]:
        if self._memory_cache is not None:
            return self._memory_cache

        payload = None
        if self.cache_path.exists():
            age = datetime.now(UTC) - datetime.fromtimestamp(self.cache_path.stat().st_mtime, tz=UTC)
            if age < timedelta(hours=24):
                payload = json.loads(self.cache_path.read_text())

        if payload is None:
            response = self._client.get("https://www.sec.gov/files/company_tickers_exchange.json")
            response.raise_for_status()
            payload = response.json()
            self.cache_path.write_text(json.dumps(payload))

        fields = payload["fields"]
        rows = payload["data"]
        lookup = {}
        for row in rows:
            item = dict(zip(fields, row))
            lookup[item["ticker"].upper()] = item

        self._memory_cache = lookup
        return lookup


class SecurityReferenceService:
    def __init__(
        self,
        cache_dir: Path,
        user_agent: str,
        twelvedata_api_key: str | None,
        timeout_seconds: int = 20,
    ) -> None:
        self.sec_directory = SecTickerDirectory(cache_dir=cache_dir, user_agent=user_agent, timeout_seconds=timeout_seconds)
        self.twelvedata_api_key = twelvedata_api_key
        self._client = httpx.Client(timeout=timeout_seconds)

    def ensure_security(self, session: Session, symbol: str, company_name: str) -> TickerSecurity:
        symbol = symbol.upper()
        security = session.get(TickerSecurity, symbol)
        if security is not None and security.last_refreshed_at >= datetime.now(UTC) - timedelta(days=7):
            return security

        sec_entry = self.sec_directory.lookup(symbol)
        provider_payload = self._fetch_twelvedata_metadata(symbol) if self.twelvedata_api_key else None
        classification = self._classify(symbol, company_name, sec_entry, provider_payload)

        if security is None:
            security = TickerSecurity(symbol=symbol)

        security.company_name = sec_entry.get("name") if sec_entry else company_name
        security.cik = sec_entry.get("cik") if sec_entry else None
        security.exchange = (provider_payload or {}).get("exchange") or (sec_entry.get("exchange") if sec_entry else None)
        security.instrument_type = (provider_payload or {}).get("instrument_type")
        security.is_public_stock = classification["is_public_stock"]
        security.eligibility_status = classification["eligibility_status"]
        security.eligibility_reason = classification["eligibility_reason"]
        security.source_payload = json.dumps(
            {"sec": sec_entry, "twelvedata": provider_payload},
            sort_keys=True,
            default=str,
        )
        security.last_refreshed_at = datetime.now(UTC)
        session.add(security)
        session.flush()
        return security

    def _fetch_twelvedata_metadata(self, symbol: str) -> dict | None:
        response = self._client.get(
            "https://api.twelvedata.com/symbol_search",
            params={"symbol": symbol, "apikey": self.twelvedata_api_key},
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("data", [])
        for row in rows:
            if row.get("symbol", "").upper() == symbol.upper():
                return row
        return None

    def _classify(self, symbol: str, company_name: str, sec_entry: dict | None, provider_payload: dict | None) -> dict:
        company_name_lower = company_name.lower()
        provider_type = (provider_payload or {}).get("instrument_type")
        exchange = (provider_payload or {}).get("exchange") or (sec_entry.get("exchange") if sec_entry else None)
        is_listed = sec_entry is not None

        if provider_type in ALLOWED_TYPES:
            return {
                "is_public_stock": True,
                "eligibility_status": "eligible",
                "eligibility_reason": f"Twelve Data classified {symbol} as {provider_type}",
            }

        if provider_type in BLOCKED_TYPE_TERMS:
            return {
                "is_public_stock": False,
                "eligibility_status": "ineligible",
                "eligibility_reason": f"Twelve Data classified {symbol} as {provider_type}",
            }

        if any(term in company_name_lower for term in BLOCKED_NAME_TERMS):
            return {
                "is_public_stock": False,
                "eligibility_status": "ineligible",
                "eligibility_reason": f"Company name suggests a non-stock instrument: {company_name}",
            }

        if is_listed and exchange:
            return {
                "is_public_stock": True,
                "eligibility_status": "eligible_low_confidence",
                "eligibility_reason": f"SEC exchange directory lists {symbol} on {exchange}",
            }

        return {
            "is_public_stock": False,
            "eligibility_status": "unknown",
            "eligibility_reason": "Unable to confirm public stock eligibility",
        }

