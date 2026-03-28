from insider_tracker.services.openinsider import OpenInsiderRow
from insider_tracker.services.sec import SecClient


SAMPLE_XML = """
<ownershipDocument>
  <issuer>
    <issuerName>Sample Corp</issuerName>
    <issuerTradingSymbol>SAMP</issuerTradingSymbol>
  </issuer>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-03-27</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>100</value></transactionShares>
        <transactionPricePerShare><value>10.00</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-03-27</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>200</value></transactionShares>
        <transactionPricePerShare><value>11.00</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>
"""


def test_sec_verifier_computes_weighted_average_purchase_price():
    row = OpenInsiderRow(
        openinsider_row_key="row",
        sec_filing_url="http://example.com",
        filing_datetime=None,
        trade_date=__import__("datetime").date(2026, 3, 27),
        symbol="SAMP",
        company_name="Sample Corp",
        insider_name="Jane Doe",
        insider_title="CEO",
        flag_code="",
        trade_type="P - Purchase",
        transaction_price=__import__("decimal").Decimal("10.666666"),
        quantity=300,
        shares_owned=1000,
        ownership_change_pct=None,
        ownership_change_text=None,
        transaction_value=__import__("decimal").Decimal("3200"),
    )

    client = SecClient(user_agent="test-agent")
    result = client._verify_xml(SAMPLE_XML, row)

    assert result.status == "verified"
    assert result.details["symbol_match"] is True
    assert result.details["price_match"] is True
    assert result.details["shares_match"] is True
