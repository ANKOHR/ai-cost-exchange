from decimal import Decimal

from aicx.analysis import sensitivity


def test_sensitivity_ranking_matches_hand_computed_fixture(workflow, openai_table):
    table, stale, age = openai_table
    result = sensitivity(workflow, table, stale, age, architecture_id="direct")
    rows = result["rows"]

    assert [(row["variable"], row["impact"]) for row in rows[:6]] == [
        ("assumptions.monthly_runs", Decimal("17.51950000")),
        ("steps.draft.calls_per_run", Decimal("16.600000000")),
        ("prices.openai.models.flagship.output_per_million", Decimal("10.000000000000")),
        ("steps.draft.output_tokens", Decimal("10.000000000000")),
        ("prices.openai.models.flagship.input_per_million", Decimal("6.600000000000")),
        ("steps.draft.input_tokens", Decimal("6.600000000000")),
    ]


def test_cache_repeat_rate_plus_and_minus_change_cost_in_opposite_directions(workflow, openai_table):
    table, stale, age = openai_table
    result = sensitivity(workflow, table, stale, age)
    row = next(item for item in result["rows"] if item["variable"] == "assumptions.repeat_rate")
    assert row["plus_monthly"] < result["baseline_monthly"]
    assert row["minus_monthly"] > result["baseline_monthly"]


def test_explicit_volume_is_included_as_a_sensitivity_variable(workflow, openai_table):
    table, stale, age = openai_table
    result = sensitivity(workflow, table, stale, age, volume=5000)
    row = next(item for item in result["rows"] if item["variable"] == "--volume")
    assert row["minus_monthly"] < result["baseline_monthly"] < row["plus_monthly"]


def test_sensitivity_has_stated_range_and_cost_basis(workflow, openai_table):
    table, stale, age = openai_table
    result = sensitivity(workflow, table, stale, age)
    assert any("plus and minus 20 percent" in row for row in result["assumption_ledger"])
    assert all("impact" in row for row in result["rows"])
