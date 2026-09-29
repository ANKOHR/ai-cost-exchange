from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from .errors import AICXError
from .io import as_date
from .prices import _decimal, stale_warning


MILLION = Decimal(1_000_000)


def number(value: Any, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise AICXError("E_NUMBER", f"{field} is not numeric") from None


def _topological(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {step["id"]: step for step in steps}
    pending = set(by_id)
    visited: set[str] = set()
    order: list[dict[str, Any]] = []
    while pending:
        ready = sorted(step_id for step_id in pending if all(dep in visited for dep in by_id[step_id].get("depends_on", [])))
        if not ready:
            raise AICXError("E_DEPENDENCY_CYCLE", "step dependencies contain a cycle")
        for step_id in ready:
            order.append(by_id[step_id])
            visited.add(step_id)
            pending.remove(step_id)
    return order


def estimate(
    workflow: dict[str, Any],
    table: dict[str, Any],
    stale: bool,
    age: int,
    *,
    architecture_id: str | None = None,
    volume: int | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    architecture_id = architecture_id or table["default_architecture"]
    if architecture_id not in table["architectures"]:
        raise AICXError("E_ARCHITECTURE_UNKNOWN", f"provider {table['provider']['id']!r} has no architecture {architecture_id!r}")
    architecture = table["architectures"][architecture_id]
    assumptions = workflow["assumptions"]
    monthly_runs = volume if volume is not None else assumptions.get("monthly_runs")
    if isinstance(monthly_runs, bool) or not isinstance(monthly_runs, int) or monthly_runs < 1:
        raise AICXError("E_VOLUME_REQUIRED", "provide --volume or set a positive whole-number assumptions.monthly_runs")
    repeat_rate = number(assumptions["repeat_rate"], "assumptions.repeat_rate")
    order = _topological(workflow["steps"])
    detail: list[dict[str, Any]] = []
    step_cost: dict[str, Decimal] = {}
    step_adjusted_cost: dict[str, Decimal] = {}
    base_step_duration: dict[str, Decimal] = {}
    adjusted_step_duration: dict[str, Decimal] = {}
    for step in order:
        step_id = step["id"]
        logical = step["model"]
        if logical not in architecture["model_map"]:
            raise AICXError("E_MODEL_MAPPING", f"architecture {architecture_id!r} does not map workflow model {logical!r} used by step {step_id!r}")
        physical = architecture["model_map"][logical]
        model = table["models"][physical]
        inputs = number(step["input_tokens"], f"steps.{step_id}.input_tokens")
        outputs = number(step["output_tokens"], f"steps.{step_id}.output_tokens")
        calls = number(step["calls_per_run"], f"steps.{step_id}.calls_per_run")
        input_price = _decimal(model["input_per_million"], f"models.{physical}.input_per_million")
        output_price = _decimal(model["output_per_million"], f"models.{physical}.output_per_million")
        tps = _decimal(model["tokens_per_second"], f"models.{physical}.tokens_per_second", minimum=Decimal("0.0000000001"))
        input_spend = calls * inputs * input_price / MILLION
        output_spend = calls * outputs * output_price / MILLION
        repeated_input_spend = input_spend * repeat_rate if step["cacheable"] else Decimal(0)
        cost = input_spend + output_spend
        adjusted_cost = cost - repeated_input_spend
        base_seconds = calls * (inputs + outputs) / tps
        adjusted_seconds = calls * (inputs * (1 - repeat_rate if step["cacheable"] else 1) + outputs) / tps
        step_cost[step_id] = cost
        step_adjusted_cost[step_id] = adjusted_cost
        dependency_base = max((base_step_duration[dep] for dep in step.get("depends_on", [])), default=Decimal(0))
        dependency_adjusted = max((adjusted_step_duration[dep] for dep in step.get("depends_on", [])), default=Decimal(0))
        base_step_duration[step_id] = dependency_base + base_seconds
        adjusted_step_duration[step_id] = dependency_adjusted + adjusted_seconds
        detail.append(
            {
                "id": step_id,
                "logical_model": logical,
                "physical_model": physical,
                "input_tokens": inputs,
                "output_tokens": outputs,
                "calls_per_run": calls,
                "cacheable": step["cacheable"],
                "depends_on": list(step.get("depends_on", [])),
                "input_per_million": input_price,
                "output_per_million": output_price,
                "tokens_per_second": tps,
                "cost_per_run": cost,
                "adjusted_cost_per_run": adjusted_cost,
                "duration_seconds": base_seconds,
                "adjusted_duration_seconds": adjusted_seconds,
            }
        )
    base_per_run = sum(step_cost.values(), Decimal(0))
    adjusted_per_run = sum(step_adjusted_cost.values(), Decimal(0))
    base_duration = max(base_step_duration.values(), default=Decimal(0))
    adjusted_duration = max(adjusted_step_duration.values(), default=Decimal(0))
    price_date = as_date(table["effective_date"], "effective_date")
    stale_text = stale_warning(table, stale, age)
    ledger = build_ledger(workflow, table, architecture_id, detail, monthly_runs, repeat_rate, stale_text)
    return {
        "workflow_name": workflow["name"],
        "provider_id": table["provider"]["id"],
        "provider_name": table["provider"].get("name", table["provider"]["id"]),
        "price_version": str(table["version"]),
        "effective_date": price_date.isoformat(),
        "freshness_days": table["freshness_days"],
        "stale": stale,
        "stale_warning": stale_text,
        "architecture": architecture_id,
        "monthly_runs": monthly_runs,
        "repeat_rate": repeat_rate,
        "base_cost_per_run": base_per_run,
        "adjusted_cost_per_run": adjusted_per_run,
        "base_cost_per_1k": base_per_run * 1000,
        "adjusted_cost_per_1k": adjusted_per_run * 1000,
        "base_monthly_cost": base_per_run * monthly_runs,
        "adjusted_monthly_cost": adjusted_per_run * monthly_runs,
        "base_duration_seconds": base_duration,
        "adjusted_duration_seconds": adjusted_duration,
        "steps": detail,
        "assumption_ledger": ledger,
        "as_of": (as_of or date.today()).isoformat(),
    }


def build_ledger(
    workflow: dict[str, Any],
    table: dict[str, Any],
    architecture_id: str,
    details: list[dict[str, Any]],
    monthly_runs: int,
    repeat_rate: Decimal,
    stale_text: str | None,
) -> list[str]:
    rows = [
        f"Workflow {workflow['name']!r}, spec version {workflow['version']}; prices in USD.",
        f"Provider {table['provider']['id']} price table v{table['version']}, effective {table['effective_date']}, freshness {table['freshness_days']} days.",
        f"Architecture {architecture_id!r}; logical model aliases resolve through its model_map.",
        f"Monthly volume: {monthly_runs} runs, from --volume or assumptions.monthly_runs.",
        f"Cache repeat rate: {repeat_rate}; applies to input tokens of cacheable steps only. Output tokens are always billed.",
        "Per-run cost = calls x (input tokens x input USD/M tokens + output tokens x output USD/M tokens) / 1,000,000.",
        "Caching-adjusted cost discounts the eligible input-token spend by repeat_rate; per-1k and monthly amounts multiply the per-run value by 1,000 and monthly volume.",
        "Wall time is the longest dependency path. Each step duration is calls x processed tokens / tokens_per_second; parallel branches overlap. Caching removes repeated input tokens from eligible step duration.",
        "Token counts and call counts are estimates supplied in the workflow, not measured usage.",
    ]
    if stale_text:
        rows.append(f"Stale price warning: {stale_text}")
    for item in details:
        rows.append(
            f"Step {item['id']}: {item['input_tokens']} estimated input tokens, {item['output_tokens']} estimated output tokens, "
            f"{item['calls_per_run']} calls per run; model {item['logical_model']} -> {item['physical_model']}; "
            f"cacheable={str(item['cacheable']).lower()}, depends_on={item['depends_on']}; "
            f"input ${item['input_per_million']}/M, output ${item['output_per_million']}/M, "
            f"throughput {item['tokens_per_second']} tokens/second."
        )
    rows.append("Model figures are not a quote and are not a billing statement.")
    return rows
