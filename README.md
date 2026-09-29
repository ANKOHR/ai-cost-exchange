# AI Cost Exchange

AI Cost Exchange prices the workflow before you build it: providers, architectures, caching, and the one assumption your budget actually depends on.

It is a Python CLI workbench for modelling a workflow described as a directed acyclic graph (DAG). It calculates provider and architecture costs, caching-adjusted spend, throughput-derived duration, and which cost-driving assumption moves the estimate most.

## Quickstart

Python 3.10 or newer and PyYAML are required. Install the package and test tools with:

```powershell
python -m pip install -e ".[test]"
```

Try the included fixture workflow:

```powershell
aicx prices list
aicx prices show openai
aicx validate examples/support-workflow.yaml
aicx estimate examples/support-workflow.yaml --volume 10000
aicx compare examples/support-workflow.yaml --providers openai,anthropic
aicx sensitivity examples/support-workflow.yaml
aicx report examples/support-workflow.yaml --format md
aicx report --format html > report.html
```

The same commands work as `python -m aicx` if the package has not been installed. Place `--prices-dir PATH` before the subcommand to use another directory of provider YAML files. The `AICX_PRICES_DIR` environment variable can set a default directory.

Run the complete suite with `python -m pytest`.

## Architecture

```text
YAML workflow
     |
     v
Named validation errors and DAG checks
     |
     +-----------------------+
     |                       |
     v                       v
Editable provider YAML   Workflow assumptions
price tables             tokens, calls, repeat rate, volume
     |                       |
     +-----------+-----------+
                 v
          Decimal cost engine
          base and cache-adjusted spend
          dependency-path duration
                 |
       +---------+----------+
       |                    |
       v                    v
Provider and           One-at-a-time plus/minus
architecture comparison 20 percent sensitivity
       |                    |
       +---------+----------+
                 v
       CLI output and Markdown/HTML report
       with a full assumption ledger
```

Each step names a logical model such as `fast` or `quality`. Each provider's architecture maps those logical names to physical models. This lets the same workflow be priced with the same aliases across providers, and lets architectures such as `direct`, `economy`, and `quality_first` use different model selections. `depends_on` describes ordering. Independent branches overlap when duration is estimated.

## Honesty boundary

Prices are user-editable fixture tables with effective dates. They may be stale, and the CLI warns when a table is older than its declared freshness window. Token counts are user estimates or documented heuristics, not measurements. Caching and throughput figures follow from stated assumptions listed in the assumption ledger. The output is a model, not a quote and not a billing statement.

The shipped provider data is illustrative and is not a claim about current provider prices, performance, or availability. Replace it with values you have verified for your intended use. Freshness is checked against the machine's current local calendar date. The reports do not include generation timestamps; stale status can change when the calendar date changes.

## Price tables

Provider fixtures are YAML files in `data/prices/`. Each file has a provider id, table version, effective date, freshness window in days, a default architecture, per-model input and output prices per million tokens, and an assumed throughput in tokens per second. Architectures map workflow model aliases to model ids defined in the same provider table. `aicx prices list` shows available tables and stale status. `aicx prices show openai` prints the editable table. Create or edit a YAML file to add a provider, model, price, throughput assumption, or architecture. Keep the provider id equal to the filename stem for convenient editing.

All costs in the shipped tables are denominated in USD. Tables accept non-negative decimal prices and positive throughput assumptions. The version and effective date are user-maintained.

## Workflow specs

Workflow specs are version 1 YAML files. A workflow includes a name, assumptions, and one or more steps. Each step requires a unique id, logical model, estimated `input_tokens` and `output_tokens`, `calls_per_run`, and a boolean `cacheable` flag. Use `depends_on: [step_id]` to define DAG edges. Steps with no dependency may run in parallel. `calls_per_run` can be fractional when it represents an expected average.

`assumptions.repeat_rate` is required and must be between 0 and 1. `assumptions.monthly_runs` is optional if `--volume` is supplied. Token and call counts must be non-negative. The validator reports stable error names such as `E_STEP_ID_DUPLICATE`, `E_DEPENDENCY_UNKNOWN`, `E_DEPENDENCY_CYCLE`, `E_INPUT_TOKENS`, and `E_REPEAT_RATE`.

```yaml
version: 1
name: support-intake
assumptions:
  monthly_runs: 10000
  repeat_rate: 0.25
steps:
  - id: classify
    model: fast
    input_tokens: 1200
    output_tokens: 120
    calls_per_run: 1
    cacheable: true
  - id: answer
    model: quality
    input_tokens: 1320
    output_tokens: 500
    calls_per_run: 1
    cacheable: false
    depends_on: [classify]
```

Validate a workflow with `aicx validate wf.yaml`.

## Estimator

`aicx estimate wf.yaml --volume 10000` reports base cost and caching-adjusted cost per run, per 1,000 runs, and for the stated monthly volume. The volume can instead come from `assumptions.monthly_runs`. Cost is calculated with decimal arithmetic from calls, tokens, and the mapped model's input and output rates.

For each cacheable step, the repeat-rate assumption reduces eligible input tokens by that fraction. Output tokens remain billed. The throughput estimate divides step tokens by the model's tokens-per-second assumption, then uses the longest dependency path. Calls within a step are treated as sequential. Parallel DAG branches overlap. This is a simplified wall-clock model, not a latency guarantee.

## Comparison

`aicx compare wf.yaml --providers openai,anthropic` prices the same workflow across the selected providers and all of their architectures. Add `--architectures direct,economy` to choose architecture names. Results sort from cheapest by caching-adjusted cost per run. The output marks the cheapest and reports its absolute and percentage cost margin below the runner-up. Each provider uses its own fixture rates and model map.

## Sensitivity analysis

`aicx sensitivity wf.yaml` varies each workflow token estimate, call count, repeat rate, monthly volume, and used-model input/output price by plus and minus 20 percent, one variable at a time. It ranks variables by the largest absolute change in caching-adjusted monthly spend. A `--volume` override is varied too. Throughput is listed in the assumption ledger but is excluded from cost sensitivity because it changes duration, not spend. Percentage changes to repeat rate are relative changes, clamped to the valid 0 to 1 range.

## Reports

`aicx report wf.yaml --format md` writes a Markdown report. `aicx report wf.yaml --format html` writes a self-contained HTML report. When no workflow is supplied, the included support-intake fixture is used. Reports contain an estimate, provider and architecture comparison, sensitivity ranking, stale price notices where needed, and a full assumption ledger. The HTML report carries a banner stating that prices are editable fixture tables and figures follow from stated assumptions.

## Determinism

Calculations use `Decimal`, result ordering is stable, and reports omit generation timestamps. With the same workflow, price tables, CLI arguments, and local calendar date, repeated runs produce byte-identical output. Stale status depends on that date, so it may change after a freshness boundary passes.

## Tests

The pytest suite checks hand-calculated estimates and caching, provider and architecture comparison, sensitivity ranking, stale-price warnings, named validation errors, deterministic reports, and CLI smoke paths for every command.
