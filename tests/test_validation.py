from pathlib import Path

import pytest

from aicx.errors import AICXError
from aicx.io import load_workflow


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda w: w["steps"].append(dict(w["steps"][0])), "E_STEP_ID_DUPLICATE"),
        (lambda w: w["steps"][0].__setitem__("input_tokens", -1), "E_INPUT_TOKENS"),
        (lambda w: w["assumptions"].__setitem__("repeat_rate", 1.2), "E_REPEAT_RATE"),
        (lambda w: w["steps"][0].__setitem__("depends_on", ["missing"]), "E_DEPENDENCY_UNKNOWN"),
        (lambda w: w["steps"][0].__setitem__("depends_on", None), "E_DEPENDENCIES"),
        (lambda w: w["steps"][0].__setitem__("depends_on", [w["steps"][0]["id"]]), "E_DEPENDENCY_CYCLE"),
        (lambda w: w["steps"][0].__setitem__("cacheable", "yes"), "E_CACHEABLE"),
        (lambda w: w["steps"][0].__setitem__("input_token", 1), "E_STEP_FIELD"),
        (lambda w: w.__setitem__("version", 2), "E_SPEC_VERSION"),
    ],
)
def test_malformed_workflows_fail_with_named_errors(tmp_path, workflow, mutate, code):
    import yaml

    mutate(workflow)
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(workflow, sort_keys=False), encoding="utf-8")
    with pytest.raises(AICXError) as caught:
        load_workflow(path)
    assert "E_SPEC_INVALID" in str(caught.value)
    assert code in str(caught.value)


def test_duplicate_yaml_mapping_keys_fail_by_name(tmp_path):
    path = tmp_path / "duplicate.yaml"
    path.write_text("version: 1\nversion: 1\n", encoding="utf-8")
    with pytest.raises(AICXError, match="E_YAML_DUPLICATE_KEY"):
        load_workflow(path)
