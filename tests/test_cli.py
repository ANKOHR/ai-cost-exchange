from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

import pytest

from aicx.cli import main
from conftest import WORKFLOW_PATH


def invoke(args):
    out, err = StringIO(), StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        status = main(args)
    return status, out.getvalue(), err.getvalue()


@pytest.mark.parametrize(
    "command",
    [
        ["prices", "list"],
        ["prices", "show", "openai"],
        ["validate", str(WORKFLOW_PATH)],
        ["estimate", str(WORKFLOW_PATH), "--volume", "10000"],
        ["compare", str(WORKFLOW_PATH), "--providers", "openai,anthropic"],
        ["sensitivity", str(WORKFLOW_PATH)],
        ["report", str(WORKFLOW_PATH), "--format", "md"],
        ["report", str(WORKFLOW_PATH), "--format", "html"],
    ],
)
def test_cli_smoke_for_every_command(price_dir, command):
    status, stdout, stderr = invoke(["--prices-dir", str(price_dir), *command])
    assert status == 0, stderr
    assert stdout
    assert "Prices are editable" in stdout or "editable fixture tables" in stdout or "Valid workflow:" in stdout


def test_deterministic_report_bytes_for_same_inputs(price_dir):
    args = ["--prices-dir", str(price_dir), "report", str(WORKFLOW_PATH), "--format", "md"]
    first = invoke(args)[1].encode("utf-8")
    second = invoke(args)[1].encode("utf-8")
    assert first == second


def test_html_report_has_honesty_banner_and_full_ledger(price_dir):
    status, output, stderr = invoke(["--prices-dir", str(price_dir), "report", str(WORKFLOW_PATH), "--format", "html"])
    assert status == 0, stderr
    assert "class=\"honesty-banner\"" in output
    assert "Prices are editable fixture tables" in output
    assert "Full assumption ledger" in output
    assert "step draft" in output


def test_validate_failure_returns_named_error(price_dir, tmp_path):
    path = Path(tmp_path) / "bad.yaml"
    path.write_text("version: 1\nname: broken\nassumptions:\n  repeat_rate: 0.2\nsteps: []\n", encoding="utf-8")
    status, output, error = invoke(["--prices-dir", str(price_dir), "validate", str(path)])
    assert status == 2
    assert not output
    assert "E_STEPS" in error


def test_report_without_workflow_uses_included_fixture(price_dir):
    status, output, stderr = invoke(["--prices-dir", str(price_dir), "report", "--format", "md"])
    assert status == 0, stderr
    assert "support-intake" in output


def test_comparison_cli_marks_winner_and_margin(price_dir):
    status, output, stderr = invoke(["--prices-dir", str(price_dir), "compare", str(WORKFLOW_PATH), "--providers", "openai,anthropic"])
    assert status == 0, stderr
    assert "CHEAPEST" in output
    assert "Margin over runner-up" in output


def test_estimate_cli_stale_warning_for_old_price_table(tmp_path):
    from datetime import date, timedelta

    import yaml

    from aicx.prices import DEFAULT_PRICES_DIR

    data = yaml.safe_load((DEFAULT_PRICES_DIR / "openai.yaml").read_text(encoding="utf-8"))
    data["effective_date"] = (date.today() - timedelta(days=data["freshness_days"] + 5)).isoformat()
    (tmp_path / "openai.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    status, output, stderr = invoke(["--prices-dir", str(tmp_path), "estimate", str(WORKFLOW_PATH)])
    assert status == 0, stderr
    assert "WARNING: Price table openai" in output
