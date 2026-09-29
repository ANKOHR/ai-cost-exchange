from __future__ import annotations

from decimal import Decimal
from html import escape
from typing import Any


HONESTY_BANNER = (
    "Prices are editable fixture tables. Figures follow from stated assumptions. "
    "Token counts are estimates. This model is not a quote or a billing statement."
)


def decimal_text(value: Decimal, places: int = 10) -> str:
    text = f"{value:.{places}f}".rstrip("0").rstrip(".")
    return text or "0"


def money(value: Decimal) -> str:
    return f"${decimal_text(value)}"


def estimate_lines(result: dict[str, Any], *, include_ledger: bool = True) -> list[str]:
    lines = [
        f"Workflow: {result['workflow_name']}",
        f"Provider: {result['provider_name']} ({result['provider_id']}), price table v{result['price_version']} effective {result['effective_date']}",
        f"Architecture: {result['architecture']}",
        f"Volume: {result['monthly_runs']} runs per month; repeat rate {decimal_text(result['repeat_rate'])}",
        f"Cost per run: {money(result['base_cost_per_run'])} before caching, {money(result['adjusted_cost_per_run'])} caching-adjusted",
        f"Cost per 1,000 runs: {money(result['base_cost_per_1k'])} before caching, {money(result['adjusted_cost_per_1k'])} caching-adjusted",
        f"Monthly cost: {money(result['base_monthly_cost'])} before caching, {money(result['adjusted_monthly_cost'])} caching-adjusted",
        f"Throughput-derived duration: {decimal_text(result['base_duration_seconds'], 4)} seconds before caching, {decimal_text(result['adjusted_duration_seconds'], 4)} seconds caching-adjusted",
    ]
    if result["stale_warning"]:
        lines.append(f"WARNING: {result['stale_warning']}")
    if include_ledger:
        lines.append("Assumption ledger:")
        lines.extend(f"  - {item}" for item in result["assumption_ledger"])
    lines.extend((HONESTY_BANNER, ""))
    return lines


def markdown_report(
    result: dict[str, Any],
    comparison: dict[str, Any],
    sensitivity: dict[str, Any],
) -> str:
    lines = [
        "# AI Cost Exchange report",
        "",
        f"> {HONESTY_BANNER}",
        "",
        "## Estimate",
        "",
        f"- Workflow: {result['workflow_name']}",
        f"- Provider: {result['provider_name']} ({result['provider_id']}), table v{result['price_version']}, effective {result['effective_date']}",
        f"- Architecture: {result['architecture']}",
        f"- Monthly volume: {result['monthly_runs']} runs; repeat rate: {decimal_text(result['repeat_rate'])}",
        f"- Cost per run: {money(result['base_cost_per_run'])} before caching; {money(result['adjusted_cost_per_run'])} caching-adjusted",
        f"- Cost per 1,000 runs: {money(result['base_cost_per_1k'])} before caching; {money(result['adjusted_cost_per_1k'])} caching-adjusted",
        f"- Monthly cost: {money(result['base_monthly_cost'])} before caching; {money(result['adjusted_monthly_cost'])} caching-adjusted",
        f"- Throughput-derived duration: {decimal_text(result['base_duration_seconds'], 4)} seconds before caching; {decimal_text(result['adjusted_duration_seconds'], 4)} seconds caching-adjusted",
        "",
    ]
    if result["stale_warning"]:
        lines.extend((f"> WARNING: {result['stale_warning']}", ""))
    lines.extend(("## Provider and architecture comparison", "", "| Provider | Architecture | Adjusted cost per run | Adjusted monthly cost | Result |", "| --- | --- | ---: | ---: | --- |"))
    for row in comparison["rows"]:
        winner = (row["provider_id"], row["architecture"]) in comparison["winner_ids"]
        mark = "CHEAPEST" if winner else ""
        if row["stale_warning"]:
            mark = (mark + "; " if mark else "") + "STALE PRICES"
        lines.append(f"| {row['provider_id']} | {row['architecture']} | {money(row['adjusted_cost_per_run'])} | {money(row['adjusted_monthly_cost'])} | {mark} |")
    if comparison["runner_up"]:
        runner = comparison["runner_up"]
        lines.append("")
        lines.append(
            f"Cheapest margin over runner-up: {money(comparison['margin'])} per run "
            f"({decimal_text(comparison['margin_percent'], 4)}% below {runner['provider_id']} / {runner['architecture']})."
        )
    lines.extend(("", "## Sensitivity analysis", "", f"Baseline caching-adjusted monthly cost: {money(sensitivity['baseline_monthly'])}.", "", "| Rank | Variable | Minus 20% monthly cost | Plus 20% monthly cost | Maximum impact |", "| ---: | --- | ---: | ---: | ---: |"))
    for rank, row in enumerate(sensitivity["rows"], start=1):
        lines.append(f"| {rank} | {row['variable']} | {money(row['minus_monthly'])} | {money(row['plus_monthly'])} | {money(row['impact'])} |")
    lines.extend(("", "## Full assumption ledger", ""))
    ledger: list[str] = []
    for source in (result["assumption_ledger"], comparison["assumption_ledger"], sensitivity["assumption_ledger"]):
        for item in source:
            if item not in ledger:
                ledger.append(item)
    lines.extend(f"- {item}" for item in ledger)
    lines.append("")
    return "\n".join(lines)


def html_report(markdown: str) -> str:
    """Render the report data with a small built-in Markdown subset."""
    output: list[str] = []
    in_table = False
    in_list = False
    for line in markdown.splitlines():
        if line.startswith("| "):
            if not in_table:
                output.append("<table>")
                in_table = True
            if line.startswith("| ---"):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            tag = "th" if not output[-1].startswith("<tr>") and "<table>" in output else "td"
            output.append("<tr>" + "".join(f"<{tag}>{escape(cell)}</{tag}>" for cell in cells) + "</tr>")
            continue
        if in_table:
            output.append("</table>")
            in_table = False
        if line.startswith("- "):
            if not in_list:
                output.append("<ul>")
                in_list = True
            output.append(f"<li>{escape(line[2:])}</li>")
            continue
        if in_list:
            output.append("</ul>")
            in_list = False
        if not line:
            continue
        if line.startswith("> "):
            output.append(f"<div class=\"honesty-banner\">{escape(line[2:])}</div>")
        elif line.startswith("### "):
            output.append(f"<h3>{escape(line[4:])}</h3>")
        elif line.startswith("## "):
            output.append(f"<h2>{escape(line[3:])}</h2>")
        elif line.startswith("# "):
            output.append(f"<h1>{escape(line[2:])}</h1>")
        else:
            output.append(f"<p>{escape(line)}</p>")
    if in_table:
        output.append("</table>")
    if in_list:
        output.append("</ul>")
    body = "\n".join(output)
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>AI Cost Exchange report</title>\n<style>body{font:16px/1.5 system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#17202a}"
        ".honesty-banner{background:#fff2cc;border:1px solid #e3bd53;padding:1rem;font-weight:600}table{border-collapse:collapse;width:100%;margin:1rem 0}"
        "th,td{border:1px solid #bbb;padding:.45rem;text-align:left}th{background:#eef2f5}code{overflow-wrap:anywhere}</style>\n</head>\n<body>\n"
        f"{body}\n</body>\n</html>\n"
    )
