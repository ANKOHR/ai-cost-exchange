from datetime import date, timedelta

import yaml

from aicx.engine import estimate
from aicx.prices import list_prices


def test_old_fixture_table_emits_stale_warning(tmp_path, openai_table, workflow):
    table, _, _ = openai_table
    table["effective_date"] = (date.today() - timedelta(days=table["freshness_days"] + 1)).isoformat()
    (tmp_path / "openai.yaml").write_text(yaml.safe_dump(table, sort_keys=False), encoding="utf-8")

    (loaded, stale, age), = list_prices(tmp_path)
    assert stale is True
    assert age == loaded["freshness_days"] + 1
    result = estimate(workflow, loaded, stale, age)
    assert result["stale"] is True
    assert "stale" in result["stale_warning"]
    assert any("Stale price warning" in row for row in result["assumption_ledger"])


def test_table_within_freshness_window_is_not_stale(prices):
    assert all(not stale for _, stale, _ in prices)
