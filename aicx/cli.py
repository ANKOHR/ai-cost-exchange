from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import yaml

from .analysis import compare, sensitivity
from .engine import estimate
from .errors import AICXError
from .io import load_workflow
from .prices import DEFAULT_PRICES_DIR, list_prices, load_price, stale_warning
from .reporting import HONESTY_BANNER, decimal_text, estimate_lines, html_report, markdown_report, money


_SOURCE_WORKFLOW = Path(__file__).resolve().parent.parent / "examples" / "support-workflow.yaml"
_INSTALLED_WORKFLOW = Path(sys.prefix) / "share" / "ai-cost-exchange" / "examples" / "support-workflow.yaml"
DEFAULT_WORKFLOW = _SOURCE_WORKFLOW if _SOURCE_WORKFLOW.is_file() else _INSTALLED_WORKFLOW


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aicx", description="Model AI workflow costs before implementation.")
    parser.add_argument("--prices-dir", type=Path, default=Path(os.environ.get("AICX_PRICES_DIR", DEFAULT_PRICES_DIR)), help="directory containing editable provider YAML tables")
    commands = parser.add_subparsers(dest="command", required=True)

    price_command = commands.add_parser("prices", help="list or inspect provider fixture price tables")
    price_subcommands = price_command.add_subparsers(dest="prices_command", required=True)
    price_subcommands.add_parser("list", help="list available price tables")
    show = price_subcommands.add_parser("show", help="show one provider table")
    show.add_argument("provider")

    validate = commands.add_parser("validate", help="validate a workflow specification")
    validate.add_argument("workflow", type=Path)

    estimate_command = commands.add_parser("estimate", help="estimate one provider and architecture")
    estimate_command.add_argument("workflow", type=Path)
    estimate_command.add_argument("--provider", default="openai")
    estimate_command.add_argument("--architecture")
    estimate_command.add_argument("--volume", type=int)

    compare_command = commands.add_parser("compare", help="compare providers and architectures")
    compare_command.add_argument("workflow", type=Path)
    compare_command.add_argument("--providers", help="comma-separated provider ids; defaults to all price tables")
    compare_command.add_argument("--architectures", help="comma-separated architecture names; defaults to all in each table")
    compare_command.add_argument("--volume", type=int)

    sensitivity_command = commands.add_parser("sensitivity", help="rank cost-driving assumptions by impact")
    sensitivity_command.add_argument("workflow", type=Path)
    sensitivity_command.add_argument("--provider", default="openai")
    sensitivity_command.add_argument("--architecture")
    sensitivity_command.add_argument("--volume", type=int)

    report = commands.add_parser("report", help="write a full Markdown or HTML model report")
    report.add_argument("workflow", type=Path, nargs="?", default=DEFAULT_WORKFLOW)
    report.add_argument("--format", choices=("md", "html"), default="md")
    report.add_argument("--volume", type=int)

    return parser


def _load_provider_tables(prices_dir: Path, provider_list: str | None) -> list[tuple[dict[str, Any], bool, int]]:
    all_tables = list_prices(prices_dir)
    if provider_list is None:
        return all_tables
    requested = [item.strip() for item in provider_list.split(",") if item.strip()]
    if not requested:
        raise AICXError("E_PROVIDER_LIST", "--providers must contain at least one provider id")
    by_id = {table["provider"]["id"]: (table, stale, age) for table, stale, age in all_tables}
    unknown = [provider for provider in requested if provider not in by_id]
    if unknown:
        raise AICXError("E_PROVIDER_UNKNOWN", f"no price table for provider(s): {', '.join(unknown)}")
    return [by_id[provider] for provider in dict.fromkeys(requested)]


def _print_prices(args: argparse.Namespace) -> None:
    if args.prices_command == "list":
        print("ID         PROVIDER       VERSION  EFFECTIVE    FRESHNESS  STATUS")
        for table, stale, age in list_prices(args.prices_dir):
            status = f"STALE ({age} days)" if stale else "current"
            print(f"{table['provider']['id']:<10} {table['provider'].get('name', ''):<14} {str(table['version']):<8} {table['effective_date']:<12} {table['freshness_days']:>3} days   {status}")
        print("Prices are editable fixture tables. This model is not a quote or billing statement.")
        return
    table, stale, age = load_price(args.prices_dir, args.provider)
    print(yaml.safe_dump(table, sort_keys=False, allow_unicode=False).rstrip())
    warning = stale_warning(table, stale, age)
    if warning:
        print(f"WARNING: {warning}")
    print("Prices are editable fixture tables. This model is not a quote or billing statement.")


def _print_comparison(result: dict[str, Any]) -> None:
    print("PROVIDER    ARCHITECTURE      ADJUSTED/RUN    ADJUSTED/MONTH    RESULT")
    for row in result["rows"]:
        winner = (row["provider_id"], row["architecture"]) in result["winner_ids"]
        mark = "CHEAPEST" if winner else ""
        if row["stale_warning"]:
            mark = (mark + " / " if mark else "") + "STALE PRICES"
        print(f"{row['provider_id']:<11} {row['architecture']:<17} {money(row['adjusted_cost_per_run']):>14} {money(row['adjusted_monthly_cost']):>16} {mark}")
    runner = result["runner_up"]
    if runner:
        winners = ", ".join(f"{provider}/{architecture}" for provider, architecture in sorted(result["winner_ids"]))
        print(f"Cheapest: {winners}")
        print(f"Margin over runner-up: {money(result['margin'])} per run ({decimal_text(result['margin_percent'], 4)}% below {runner['provider_id']}/{runner['architecture']})")
    print("Assumption ledger:")
    for item in result["assumption_ledger"]:
        print(f"  - {item}")
    print(HONESTY_BANNER)


def _print_sensitivity(result: dict[str, Any]) -> None:
    print(f"Sensitivity for {result['provider_id']}/{result['architecture']}; baseline monthly adjusted cost {money(result['baseline_monthly'])}.")
    print("RANK  VARIABLE                                             MINUS 20%        PLUS 20%      MAX IMPACT")
    for rank, row in enumerate(result["rows"], start=1):
        print(f"{rank:>4}  {row['variable']:<52} {money(row['minus_monthly']):>14} {money(row['plus_monthly']):>14} {money(row['impact']):>14}")
    print("Assumption ledger:")
    for item in result["assumption_ledger"]:
        print(f"  - {item}")
    print(HONESTY_BANNER)


def run(args: argparse.Namespace) -> int:
    if args.command == "prices":
        _print_prices(args)
        return 0
    if args.command == "validate":
        load_workflow(args.workflow)
        print(f"Valid workflow: {args.workflow}")
        print("Token counts and call counts are user estimates. The model is not a quote or a billing statement.")
        return 0
    if args.command == "estimate":
        workflow = load_workflow(args.workflow)
        table, stale, age = load_price(args.prices_dir, args.provider)
        result = estimate(workflow, table, stale, age, architecture_id=args.architecture, volume=args.volume)
        print("\n".join(estimate_lines(result)))
        return 0
    if args.command == "compare":
        workflow = load_workflow(args.workflow)
        tables = _load_provider_tables(args.prices_dir, args.providers)
        architectures = [item.strip() for item in args.architectures.split(",") if item.strip()] if args.architectures else None
        if args.architectures and not architectures:
            raise AICXError("E_ARCHITECTURES", "--architectures must contain at least one architecture name")
        _print_comparison(compare(workflow, tables, architectures=architectures, volume=args.volume))
        return 0
    if args.command == "sensitivity":
        workflow = load_workflow(args.workflow)
        table, stale, age = load_price(args.prices_dir, args.provider)
        _print_sensitivity(sensitivity(workflow, table, stale, age, architecture_id=args.architecture, volume=args.volume))
        return 0
    if args.command == "report":
        workflow = load_workflow(args.workflow)
        primary, stale, age = load_price(args.prices_dir, "openai")
        result = estimate(workflow, primary, stale, age, volume=args.volume)
        tables = list_prices(args.prices_dir)
        comparison = compare(workflow, tables, volume=args.volume)
        sensitivity_result = sensitivity(workflow, primary, stale, age, volume=args.volume)
        markdown = markdown_report(result, comparison, sensitivity_result)
        print(html_report(markdown) if args.format == "html" else markdown, end="" if markdown.endswith("\n") else "\n")
        return 0
    raise AICXError("E_COMMAND", f"unknown command {args.command!r}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except AICXError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
