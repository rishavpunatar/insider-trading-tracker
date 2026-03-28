from insider_tracker.services.openinsider import OpenInsiderClient


SAMPLE_HTML = """
<table class="tinytable">
  <thead>
    <tr>
      <th>X</th><th>Filing Date</th><th>Trade Date</th><th>Ticker</th><th>Company Name</th>
      <th>Insider Name</th><th>Title</th><th>Trade Type</th><th>Price</th><th>Qty</th>
      <th>Owned</th><th>Delta</th><th>Value</th><th>1d</th><th>1w</th><th>1m</th><th>6m</th>
    </tr>
  </thead>
  <tbody>
    <tr style="background:#e7ffe7">
      <td align="right"></td>
      <td align="right"><div><a href="http://www.sec.gov/Archives/edgar/data/1/row.xml">2026-03-27 21:58:47</a></div></td>
      <td align="right"><div>2026-03-23</div></td>
      <td><b><a href="/PMEC">PMEC</a></b></td>
      <td><a href="/PMEC">Primech Holdings Ltd</a></td>
      <td><a href="/insider/123">Ho Kin Wai</a></td>
      <td>CEO, 10%</td>
      <td>P - Purchase</td>
      <td align="right">$1.14</td>
      <td align="right">+839,963</td>
      <td align="right">20,255,731</td>
      <td align="right">+4%</td>
      <td align="right">+$958,650</td>
      <td></td><td></td><td></td><td></td>
    </tr>
  </tbody>
</table>
"""


def test_parse_latest_rows():
    rows = OpenInsiderClient.parse_latest_rows(SAMPLE_HTML, max_rows=10)

    assert len(rows) == 1
    row = rows[0]
    assert row.symbol == "PMEC"
    assert row.company_name == "Primech Holdings Ltd"
    assert row.insider_name == "Ho Kin Wai"
    assert row.trade_type == "P - Purchase"
    assert str(row.transaction_price) == "1.14"
    assert row.quantity == 839963
    assert row.shares_owned == 20255731
    assert str(row.transaction_value) == "958650"
    assert str(row.ownership_change_pct) == "4"

