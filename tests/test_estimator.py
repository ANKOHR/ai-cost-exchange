from decimal import Decimal

from aicx.engine import estimate


def test_fixture_estimate_matches_hand_computed_costs(workflow, openai_table):
    table, stale, age = openai_table
    result = estimate(workflow, table, stale, age, architecture_id="direct")

    assert result["base_cost_per_run"] == Decimal("0.008873")
    assert result["base_cost_per_1k"] == Decimal("8.873")
    assert result["base_monthly_cost"] == Decimal("88.730000")
    assert result["adjusted_cost_per_run"] == Decimal("0.00875975")
    assert result["adjusted_cost_per_1k"] == Decimal("8.75975000")
    assert result["adjusted_monthly_cost"] == Decimal("87.59750000")


def test_throughput_uses_dependency_path_and_cache_adjusted_tokens(workflow, openai_table):
    table, stale, age = openai_table
    result = estimate(workflow, table, stale, age, architecture_id="direct")

    assert result["base_duration_seconds"] == Decimal("10.5")
    assert result["adjusted_duration_seconds"] == Decimal("9.745")


def test_volume_override_replaces_workflow_monthly_volume(workflow, openai_table):
    table, stale, age = openai_table
    result = estimate(workflow, table, stale, age, volume=2000)
    assert result["monthly_runs"] == 2000
    assert result["adjusted_monthly_cost"] == Decimal("17.51950000")


def test_independent_dag_branches_overlap_in_wall_time(workflow, openai_table):
    table, stale, age = openai_table
    workflow["steps"][2]["depends_on"] = []
    result = estimate(workflow, table, stale, age)
    assert result["base_duration_seconds"] == Decimal("8.6")


def test_estimate_contains_complete_assumption_ledger(workflow, openai_table):
    table, stale, age = openai_table
    ledger = estimate(workflow, table, stale, age)["assumption_ledger"]
    assert any("repeat rate" in entry for entry in ledger)
    assert any("tokens_per_second" in entry for entry in ledger)
    assert any("not a quote" in entry for entry in ledger)
