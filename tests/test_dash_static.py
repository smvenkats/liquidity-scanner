from pathlib import Path


INDEX = Path(__file__).parents[1] / "dashboard" / "static" / "index.html"


def test_dashboard_table_has_status_column_and_date_aware_time_formatter():
    html = INDEX.read_text(encoding="utf-8")

    assert "<th>status</th>" in html
    assert "month:'short'" in html
    assert "day:'2-digit'" in html
    assert "s.status||'active'" in html
