from decimal import Decimal

from aicx.analysis import compare


def test_comparison_finds_cheapest_architecture_and_correct_margin(workflow, prices):
    result = compare(workflow, prices)
    assert result["winner_ids"] == {("openai", "economy")}
    assert result["rows"][0]["adjusted_cost_per_run"] == Decimal("0.00211975")
    assert result["runner_up"]["provider_id"] == "openai"
    assert result["runner_up"]["architecture"] == "direct"
    assert result["margin"] == Decimal("0.00664000")
    assert result["margin_percent"] == Decimal("0.00664") / Decimal("0.00875975") * 100


def test_comparison_prices_same_steps_across_six_provider_architectures(workflow, prices):
    result = compare(workflow, prices)
    assert len(result["rows"]) == 6
    assert {(row["provider_id"], row["architecture"]) for row in result["rows"]} == {
        (provider, architecture)
        for provider in ("openai", "anthropic")
        for architecture in ("direct", "economy", "quality_first")
    }
    assert "step estimates and DAG" in result["assumption_ledger"][0]


def test_comparison_marks_all_equal_cost_scenarios_as_tied(workflow, prices):
    workflow["steps"] = [workflow["steps"][0]]
    workflow["steps"][0]["model"] = "fast"
    result = compare(workflow, [prices[1]], architectures=["direct", "economy"])
    assert result["winner_ids"] == {("openai", "direct"), ("openai", "economy")}
    assert result["margin"] == Decimal(0)
