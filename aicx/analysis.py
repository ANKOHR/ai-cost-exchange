from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from .engine import estimate, number


SENSITIVITY_FACTOR = Decimal("0.20")


def compare(
    workflow: dict[str, Any],
    tables: list[tuple[dict[str, Any], bool, int]],
    *,
    architectures: list[str] | None = None,
    volume: int | None = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for table, stale, age in tables:
        names = architectures if architectures is not None else sorted(table["architectures"])
        for architecture in names:
            result = estimate(workflow, table, stale, age, architecture_id=architecture, volume=volume)
            rows.append(result)
    rows.sort(key=lambda row: (row["adjusted_cost_per_run"], row["provider_id"], row["architecture"]))
    if not rows:
        raise ValueError("comparison requires at least one provider and architecture")
    cheapest = rows[0]["adjusted_cost_per_run"]
    winners = [row for row in rows if row["adjusted_cost_per_run"] == cheapest]
    runner_up = next((row for row in rows if row["adjusted_cost_per_run"] > cheapest), None)
    margin = (runner_up["adjusted_cost_per_run"] - cheapest) if runner_up else Decimal(0)
    margin_percent = (margin / runner_up["adjusted_cost_per_run"] * 100) if runner_up and runner_up["adjusted_cost_per_run"] else Decimal(0)
    return {
        "rows": rows,
        "winner_ids": {(row["provider_id"], row["architecture"]) for row in winners},
        "runner_up": runner_up,
        "margin": margin,
        "margin_percent": margin_percent,
        "monthly_runs": rows[0]["monthly_runs"],
        "assumption_ledger": _comparison_ledger(workflow, rows),
    }


def _comparison_ledger(workflow: dict[str, Any], rows: list[dict[str, Any]]) -> list[str]:
    repeat_rate = rows[0]["repeat_rate"]
    ledger = [
        f"Workflow {workflow['name']!r}, version {workflow['version']}; all rows use the same step estimates and DAG.",
        f"Monthly volume is {rows[0]['monthly_runs']} runs. Repeat rate is {repeat_rate}; caching discounts repeated input tokens on cacheable steps. Output tokens remain billed.",
        "The same logical model aliases, estimated input/output tokens, calls per run, cache flags, and dependencies are applied to every row:",
        "Each provider's effective date, freshness window, model prices, throughput, and architecture alias map are shown in the following rows.",
    ]
    for step in workflow["steps"]:
        ledger.append(
            f"Step {step['id']}: logical model {step['model']}; {step['input_tokens']} estimated input tokens; "
            f"{step['output_tokens']} estimated output tokens; {step['calls_per_run']} calls per run; "
            f"cacheable={str(step['cacheable']).lower()}; depends_on={step.get('depends_on', [])}."
        )
    for row in rows:
        ledger.append(
            f"{row['provider_id']} {row['architecture']}: table v{row['price_version']} effective {row['effective_date']}, "
            f"freshness window {row['freshness_days']} days; "
            f"adjusted cost ${row['adjusted_cost_per_run']} per run from its own model price table."
        )
        if row["stale_warning"]:
            ledger.append(f"Stale price warning: {row['stale_warning']}")
        for item in row["steps"]:
            ledger.append(
                f"{row['provider_id']}/{row['architecture']} step {item['id']}: {item['logical_model']} -> {item['physical_model']}; "
                f"input ${item['input_per_million']}/M, output ${item['output_per_million']}/M, {item['tokens_per_second']} tokens/second."
            )
    ledger.append("Token counts are estimates, prices are editable fixture values, and results are not quotes or billing statements.")
    return ledger


def sensitivity(
    workflow: dict[str, Any],
    table: dict[str, Any],
    stale: bool,
    age: int,
    *,
    architecture_id: str | None = None,
    volume: int | None = None,
) -> dict[str, Any]:
    baseline = estimate(workflow, table, stale, age, architecture_id=architecture_id, volume=volume)
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, step in enumerate(workflow["steps"]):
        for field in ("input_tokens", "output_tokens", "calls_per_run"):
            _add_candidate(rows, seen, f"steps.{step['id']}.{field}")
            _set_pair(rows[-1], workflow, table, stale, age, architecture_id, volume, lambda w, p, i=index, f=field: w["steps"][i].__setitem__(f, number(w["steps"][i][f], f"{step['id']}.{f}") * (1 - SENSITIVITY_FACTOR)))
    assumptions = workflow["assumptions"]
    _append_sensitivity(rows, seen, workflow, table, stale, age, architecture_id, volume, "assumptions.repeat_rate", lambda w, p, s: w["assumptions"].__setitem__("repeat_rate", max(Decimal(0), min(Decimal(1), number(w["assumptions"]["repeat_rate"], "repeat_rate") * (1 + s)))))
    if volume is None and "monthly_runs" in assumptions:
        _append_sensitivity(rows, seen, workflow, table, stale, age, architecture_id, volume, "assumptions.monthly_runs", lambda w, p, s: w["assumptions"].__setitem__("monthly_runs", max(1, int((number(w["assumptions"]["monthly_runs"], "monthly_runs") * (1 + s)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)))))
    actual_architecture = architecture_id or table["default_architecture"]
    actual_map = table["architectures"][actual_architecture]["model_map"]
    used_models = sorted({actual_map[step["model"]] for step in workflow["steps"]})
    for model_id in used_models:
        for field in ("input_per_million", "output_per_million"):
            key = (model_id, field)
            if key in seen:
                continue
            seen.add(key)
            _append_sensitivity(
                rows,
                seen,
                workflow,
                table,
                stale,
                age,
                architecture_id,
                volume,
                f"prices.{table['provider']['id']}.models.{model_id}.{field}",
                lambda w, p, s, m=model_id, f=field: p["models"][m].__setitem__(f, number(p["models"][m][f], f"{m}.{f}") * (1 + s)),
                pair_mutator=lambda w, p, m=model_id, f=field: p["models"][m].__setitem__(f, number(p["models"][m][f], f"{m}.{f}") * (1 - SENSITIVITY_FACTOR)),
            )
    if volume is not None:
        plus_volume = max(1, int((Decimal(volume) * (1 + SENSITIVITY_FACTOR)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)))
        minus_volume = max(1, int((Decimal(volume) * (1 - SENSITIVITY_FACTOR)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)))
        rows.append(
            {
                "variable": "--volume",
                "plus_monthly": estimate(workflow, table, stale, age, architecture_id=architecture_id, volume=plus_volume)["adjusted_monthly_cost"],
                "minus_monthly": estimate(workflow, table, stale, age, architecture_id=architecture_id, volume=minus_volume)["adjusted_monthly_cost"],
            }
        )
    baseline_monthly = baseline["adjusted_monthly_cost"]
    for row in rows:
        row["positive_impact"] = abs(row["plus_monthly"] - baseline_monthly)
        row["negative_impact"] = abs(row["minus_monthly"] - baseline_monthly)
        row["impact"] = max(row["positive_impact"], row["negative_impact"])
    rows.sort(key=lambda row: (-row["impact"], row["variable"]))
    return {
        "baseline_monthly": baseline_monthly,
        "baseline_per_run": baseline["adjusted_cost_per_run"],
        "provider_id": baseline["provider_id"],
        "architecture": baseline["architecture"],
        "monthly_runs": baseline["monthly_runs"],
        "repeat_rate": baseline["repeat_rate"],
        "rows": rows,
        "assumption_ledger": baseline["assumption_ledger"] + [
            "Sensitivity varies each cost-driving workflow, volume, repeat-rate, and used-model input by plus and minus 20 percent, one variable at a time.",
            "Sensitivity ranks the largest absolute change in caching-adjusted monthly cost. Throughput is excluded because it affects duration, not cost.",
        ],
    }


def _add_candidate(rows: list[dict[str, Any]], seen: set[tuple[str, str]], variable: str) -> None:
    key = (variable, "")
    if key not in seen:
        seen.add(key)
        rows.append({"variable": variable})


def _set_pair(row: dict[str, Any], workflow: dict[str, Any], table: dict[str, Any], stale: bool, age: int, architecture_id: str | None, volume: int | None, minus_mutator: Any) -> None:
    plus_workflow, plus_table = deepcopy(workflow), deepcopy(table)
    minus_workflow, minus_table = deepcopy(workflow), deepcopy(table)
    # The candidate's plus mutation has already been encoded by its field path.
    _apply_variable(plus_workflow, plus_table, row["variable"], 1 + SENSITIVITY_FACTOR)
    minus_mutator(minus_workflow, minus_table)
    plus_volume = _candidate_volume(plus_workflow, volume)
    minus_volume = _candidate_volume(minus_workflow, volume)
    row["plus_monthly"] = estimate(plus_workflow, plus_table, stale, age, architecture_id=architecture_id, volume=plus_volume)["adjusted_monthly_cost"]
    row["minus_monthly"] = estimate(minus_workflow, minus_table, stale, age, architecture_id=architecture_id, volume=minus_volume)["adjusted_monthly_cost"]


def _apply_variable(workflow: dict[str, Any], table: dict[str, Any], variable: str, scale: Decimal) -> None:
    if variable.startswith("steps."):
        _, step_id, field = variable.split(".")
        for step in workflow["steps"]:
            if step["id"] == step_id:
                step[field] = number(step[field], variable) * scale
                return
    elif variable == "assumptions.repeat_rate":
        workflow["assumptions"]["repeat_rate"] = max(Decimal(0), min(Decimal(1), number(workflow["assumptions"]["repeat_rate"], variable) * scale))
    elif variable == "assumptions.monthly_runs":
        workflow["assumptions"]["monthly_runs"] = max(1, int((number(workflow["assumptions"]["monthly_runs"], variable) * scale).quantize(Decimal("1"), rounding=ROUND_HALF_UP)))
    elif variable.startswith("prices."):
        _, provider_id, _, model_id, field = variable.split(".")
        if provider_id == table["provider"]["id"]:
            table["models"][model_id][field] = number(table["models"][model_id][field], variable) * scale


def _candidate_volume(workflow: dict[str, Any], volume: int | None) -> int | None:
    return volume


def _append_sensitivity(
    rows: list[dict[str, Any]],
    seen: set[tuple[str, str]],
    workflow: dict[str, Any],
    table: dict[str, Any],
    stale: bool,
    age: int,
    architecture_id: str | None,
    volume: int | None,
    variable: str,
    plus_mutator: Any,
    *,
    pair_mutator: Any | None = None,
) -> None:
    key = (variable, "")
    if key in seen:
        return
    seen.add(key)
    plus_workflow, plus_table = deepcopy(workflow), deepcopy(table)
    minus_workflow, minus_table = deepcopy(workflow), deepcopy(table)
    plus_mutator(plus_workflow, plus_table, SENSITIVITY_FACTOR)
    if pair_mutator is not None:
        pair_mutator(minus_workflow, minus_table)
    else:
        _apply_variable(minus_workflow, minus_table, variable, 1 - SENSITIVITY_FACTOR)
    plus_volume = _candidate_volume(plus_workflow, volume)
    minus_volume = _candidate_volume(minus_workflow, volume)
    rows.append(
        {
            "variable": variable,
            "plus_monthly": estimate(plus_workflow, plus_table, stale, age, architecture_id=architecture_id, volume=plus_volume)["adjusted_monthly_cost"],
            "minus_monthly": estimate(minus_workflow, minus_table, stale, age, architecture_id=architecture_id, volume=minus_volume)["adjusted_monthly_cost"],
        }
    )
