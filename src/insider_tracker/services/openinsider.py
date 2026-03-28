from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
import json
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
import httpx


NEW_YORK = ZoneInfo("America/New_York")


@dataclass
class OpenInsiderRow:
    openinsider_row_key: str
    sec_filing_url: str
    filing_datetime: datetime | None
    trade_date: date | None
    symbol: str
    company_name: str
    insider_name: str
    insider_title: str
    flag_code: str
    trade_type: str
    transaction_price: Decimal | None
    quantity: int | None
    shares_owned: int | None
    ownership_change_pct: Decimal | None
    ownership_change_text: str | None
    transaction_value: Decimal | None

    def to_json(self) -> str:
        payload = asdict(self)
        payload["filing_datetime"] = self.filing_datetime.isoformat() if self.filing_datetime else None
        payload["trade_date"] = self.trade_date.isoformat() if self.trade_date else None
        payload["transaction_price"] = str(self.transaction_price) if self.transaction_price is not None else None
        payload["ownership_change_pct"] = str(self.ownership_change_pct) if self.ownership_change_pct is not None else None
        payload["transaction_value"] = str(self.transaction_value) if self.transaction_value is not None else None
        return json.dumps(payload, sort_keys=True)


class OpenInsiderClient:
    def __init__(self, user_agent: str, timeout_seconds: int = 20) -> None:
        self._client = httpx.Client(
            follow_redirects=True,
            timeout=timeout_seconds,
            headers={"User-Agent": user_agent},
        )

    def fetch_latest_rows(self, max_rows: int = 100) -> list[OpenInsiderRow]:
        response = self._client.get("http://openinsider.com/latest-insider-purchases-25k")
        response.raise_for_status()
        return self.parse_latest_rows(response.text, max_rows=max_rows)

    @staticmethod
    def parse_latest_rows(html: str, max_rows: int = 100) -> list[OpenInsiderRow]:
        soup = BeautifulSoup(html, "html.parser")
        table = soup.select_one("table.tinytable")
        if table is None:
            raise ValueError("Could not find OpenInsider results table")

        body = table.find("tbody")
        if body is None:
            raise ValueError("Could not find OpenInsider results table body")

        rows: list[OpenInsiderRow] = []
        for tr in body.find_all("tr", recursive=False)[:max_rows]:
            cells = tr.find_all("td", recursive=False)
            if len(cells) < 17:
                continue

            sec_link = cells[1].find("a")
            symbol_link = cells[3].find("a")
            insider_link = cells[5].find("a")

            if sec_link is None or symbol_link is None or insider_link is None:
                continue

            sec_url = sec_link["href"].strip()
            symbol = symbol_link.get_text(" ", strip=True).upper()
            filing_dt = _parse_openinsider_datetime(sec_link.get_text(" ", strip=True))
            trade_dt = _parse_date(cells[2].get_text(" ", strip=True))
            ownership_change_raw = cells[11].get_text(" ", strip=True) or None

            rows.append(
                OpenInsiderRow(
                    openinsider_row_key=sec_url,
                    sec_filing_url=sec_url,
                    filing_datetime=filing_dt,
                    trade_date=trade_dt,
                    symbol=symbol,
                    company_name=cells[4].get_text(" ", strip=True),
                    insider_name=insider_link.get_text(" ", strip=True),
                    insider_title=cells[6].get_text(" ", strip=True),
                    flag_code=cells[0].get_text(" ", strip=True),
                    trade_type=cells[7].get_text(" ", strip=True),
                    transaction_price=_parse_money(cells[8].get_text(" ", strip=True)),
                    quantity=_parse_int(cells[9].get_text(" ", strip=True)),
                    shares_owned=_parse_int(cells[10].get_text(" ", strip=True)),
                    ownership_change_pct=_parse_percent(ownership_change_raw),
                    ownership_change_text=ownership_change_raw,
                    transaction_value=_parse_money(cells[12].get_text(" ", strip=True)),
                )
            )

        return rows


def _parse_openinsider_datetime(value: str) -> datetime | None:
    if not value:
        return None
    local_dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=NEW_YORK)
    return local_dt.astimezone(ZoneInfo("UTC"))


def _parse_date(value: str) -> date | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_money(value: str) -> Decimal | None:
    if not value:
        return None
    normalized = value.replace("$", "").replace(",", "").replace("+", "").strip()
    if not normalized:
        return None
    return Decimal(normalized)


def _parse_int(value: str) -> int | None:
    if not value:
        return None
    normalized = value.replace(",", "").replace("+", "").strip()
    if not normalized:
        return None
    return int(normalized)


def _parse_percent(value: str | None) -> Decimal | None:
    if not value:
        return None
    normalized = value.replace("%", "").replace("+", "").strip()
    if not normalized or normalized.lower() == "new":
        return None
    return Decimal(normalized)

