from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import json
import re
import xml.etree.ElementTree as ET

import httpx

from insider_tracker.services.openinsider import OpenInsiderRow


@dataclass
class SecVerificationResult:
    status: str
    details: dict

    def to_json(self) -> str:
        return json.dumps(self.details, sort_keys=True, default=str)


class SecClient:
    def __init__(self, user_agent: str, timeout_seconds: int = 20) -> None:
        self._client = httpx.Client(
            follow_redirects=True,
            timeout=timeout_seconds,
            headers={"User-Agent": user_agent},
        )

    def verify_filing(self, row: OpenInsiderRow) -> SecVerificationResult:
        try:
            sec_url = _normalize_sec_xml_url(row.sec_filing_url)
            response = self._client.get(sec_url)
            response.raise_for_status()
            return self._verify_xml(response.text, row)
        except Exception as exc:
            return SecVerificationResult(
                status="error",
                details={"error": str(exc), "sec_filing_url": row.sec_filing_url},
            )

    def _verify_xml(self, xml_text: str, row: OpenInsiderRow) -> SecVerificationResult:
        root = ET.fromstring(xml_text)
        _strip_namespaces(root)

        symbol = _find_text(root, ".//issuerTradingSymbol")
        issuer_name = _find_text(root, ".//issuerName")
        transactions = []
        for txn in root.findall(".//nonDerivativeTransaction"):
            code = _find_text(txn, ".//transactionCoding/transactionCode")
            shares = _find_decimal(_find_text(txn, ".//transactionAmounts/transactionShares/value"))
            price = _find_decimal(_find_text(txn, ".//transactionAmounts/transactionPricePerShare/value"))
            trade_date = _find_date(_find_text(txn, ".//transactionDate/value"))
            acquired_disposed = _find_text(
                txn,
                ".//transactionAmounts/transactionAcquiredDisposedCode/value",
            )
            transactions.append(
                {
                    "code": code,
                    "shares": shares,
                    "price": price,
                    "trade_date": trade_date,
                    "acquired_disposed": acquired_disposed,
                }
            )

        purchases = [txn for txn in transactions if txn["code"] == "P"]
        total_shares = sum((txn["shares"] or Decimal("0")) for txn in purchases)
        total_value = sum(
            (txn["shares"] or Decimal("0")) * (txn["price"] or Decimal("0")) for txn in purchases
        )
        weighted_price = None
        if purchases and total_shares > 0:
            weighted_price = total_value / total_shares

        detail = {
            "symbol_from_sec": symbol,
            "issuer_name_from_sec": issuer_name,
            "purchase_count": len(purchases),
            "total_purchase_shares": str(total_shares) if purchases else None,
            "weighted_average_purchase_price": str(weighted_price) if weighted_price is not None else None,
            "transaction_dates": [txn["trade_date"].isoformat() for txn in purchases if txn["trade_date"]],
            "symbol_match": symbol == row.symbol,
            "trade_date_match": row.trade_date.isoformat() if row.trade_date else None,
            "openinsider_price": str(row.transaction_price) if row.transaction_price is not None else None,
        }

        symbol_match = symbol == row.symbol
        trade_date_match = any(txn["trade_date"] == row.trade_date for txn in purchases)
        has_purchase = bool(purchases)
        price_match = _approx_equal(weighted_price, row.transaction_price)
        shares_match = _approx_equal(total_shares, Decimal(row.quantity)) if row.quantity is not None else False

        detail["price_match"] = price_match
        detail["shares_match"] = shares_match
        detail["trade_date_found"] = trade_date_match

        if symbol_match and has_purchase and trade_date_match and price_match:
            status = "verified"
        elif symbol_match and has_purchase:
            status = "partial"
        else:
            status = "mismatch"

        return SecVerificationResult(status=status, details=detail)


def _strip_namespaces(root: ET.Element) -> None:
    for elem in root.iter():
        if "}" in elem.tag:
            elem.tag = elem.tag.split("}", 1)[1]


def _find_text(root: ET.Element, path: str) -> str | None:
    value = root.findtext(path)
    return value.strip() if value else None


def _find_decimal(value: str | None) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(value)


def _find_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _approx_equal(left: Decimal | None, right: Decimal | None) -> bool:
    if left is None or right is None:
        return False
    tolerance = max(Decimal("0.02"), right * Decimal("0.005"))
    return abs(left - right) <= tolerance


def _normalize_sec_xml_url(url: str) -> str:
    normalized = url.replace("http://", "https://", 1)
    return re.sub(r"/xslF345X\d+/", "/", normalized)
