from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from typing import Any

from .errors import AICXError


def _number(value: Any, field: str, code: str, *, minimum: Decimal | None = None) -> Decimal:
    if isinstance(value, bool):
        raise AICXError(code, f"{field} must be a number")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise AICXError(code, f"{field} must be a number") from None
    if not number.is_finite():
        raise AICXError(code, f"{field} must be finite")
    if minimum is not None and number < minimum:
        raise AICXError(code, f"{field} must be at least {minimum}")
    return number


def validate_workflow(data: Any) -> None:
    if not isinstance(data, dict):
        raise AICXError("E_SPEC_ROOT", "workflow must be a YAML mapping")
    errors: list[AICXError] = []
    unknown_root = sorted(set(data) - {"version", "name", "assumptions", "steps"}, key=str)
    if unknown_root:
        errors.append(AICXError("E_SPEC_FIELD", f"unknown workflow field(s): {', '.join(str(field) for field in unknown_root)}"))
    if not isinstance(data.get("version"), int) or isinstance(data.get("version"), bool) or data.get("version") != 1:
        errors.append(AICXError("E_SPEC_VERSION", "version must be 1"))
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append(AICXError("E_SPEC_NAME", "name must be a non-empty string"))
    assumptions = data.get("assumptions")
    if not isinstance(assumptions, dict):
        errors.append(AICXError("E_ASSUMPTIONS", "assumptions must be a mapping"))
        assumptions = {}
    unknown_assumptions = sorted(set(assumptions) - {"repeat_rate", "monthly_runs"}, key=str)
    if unknown_assumptions:
        errors.append(AICXError("E_ASSUMPTION_FIELD", f"unknown assumption field(s): {', '.join(str(field) for field in unknown_assumptions)}"))
    if "repeat_rate" not in assumptions:
        errors.append(AICXError("E_REPEAT_RATE", "assumptions.repeat_rate is required"))
    else:
        try:
            repeat_rate = _number(assumptions["repeat_rate"], "assumptions.repeat_rate", "E_REPEAT_RATE", minimum=Decimal(0))
            if repeat_rate > 1:
                errors.append(AICXError("E_REPEAT_RATE", "assumptions.repeat_rate must be between 0 and 1"))
        except AICXError as exc:
            errors.append(exc)
    if "monthly_runs" in assumptions:
        try:
            volume = _number(assumptions["monthly_runs"], "assumptions.monthly_runs", "E_MONTHLY_VOLUME", minimum=Decimal(1))
            if volume != volume.to_integral_value():
                errors.append(AICXError("E_MONTHLY_VOLUME", "assumptions.monthly_runs must be a whole number"))
        except AICXError as exc:
            errors.append(exc)
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        errors.append(AICXError("E_STEPS", "steps must be a non-empty list"))
        steps = []
    seen: set[str] = set()
    clean_steps: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        where = f"steps[{index}]"
        if not isinstance(step, dict):
            errors.append(AICXError("E_STEP", f"{where} must be a mapping"))
            continue
        step_id = step.get("id")
        if not isinstance(step_id, str) or not step_id.strip():
            errors.append(AICXError("E_STEP_ID", f"{where}.id must be a non-empty string"))
        elif not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", step_id):
            errors.append(AICXError("E_STEP_ID", f"{where}.id must start with a letter or underscore and contain only letters, digits, underscores, or hyphens"))
        elif step_id in seen:
            errors.append(AICXError("E_STEP_ID_DUPLICATE", f"step id {step_id!r} appears more than once"))
        else:
            seen.add(step_id)
        model = step.get("model")
        if not isinstance(model, str) or not model.strip():
            errors.append(AICXError("E_STEP_MODEL", f"{where}.model must be a non-empty logical model name"))
        elif not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", model):
            errors.append(AICXError("E_STEP_MODEL", f"{where}.model must start with a letter or underscore and contain only letters, digits, underscores, or hyphens"))
        unknown_step_fields = sorted(set(step) - {"id", "model", "input_tokens", "output_tokens", "calls_per_run", "cacheable", "depends_on"}, key=str)
        if unknown_step_fields:
            errors.append(AICXError("E_STEP_FIELD", f"{where} has unknown field(s): {', '.join(str(field) for field in unknown_step_fields)}"))
        for field, code in (("input_tokens", "E_INPUT_TOKENS"), ("output_tokens", "E_OUTPUT_TOKENS"), ("calls_per_run", "E_CALLS_PER_RUN")):
            if field not in step:
                errors.append(AICXError(code, f"{where}.{field} is required"))
            else:
                try:
                    _number(step[field], f"{where}.{field}", code, minimum=Decimal(0))
                except AICXError as exc:
                    errors.append(exc)
        if "cacheable" not in step or not isinstance(step.get("cacheable"), bool):
            errors.append(AICXError("E_CACHEABLE", f"{where}.cacheable must be true or false"))
        dependencies = step.get("depends_on", [])
        if not isinstance(dependencies, list) or any(not isinstance(item, str) for item in dependencies):
            errors.append(AICXError("E_DEPENDENCIES", f"{where}.depends_on must be a list of step ids"))
        elif len(set(dependencies)) != len(dependencies):
            errors.append(AICXError("E_DEPENDENCIES", f"{where}.depends_on must not contain duplicates"))
        else:
            step["depends_on"] = dependencies
        clean_steps.append(step)
    for step in clean_steps:
        for dependency in step.get("depends_on", []) if isinstance(step.get("depends_on", []), list) else []:
            if dependency not in seen:
                errors.append(AICXError("E_DEPENDENCY_UNKNOWN", f"step {step.get('id', '<unknown>')!r} depends on unknown step {dependency!r}"))
            elif dependency == step.get("id"):
                errors.append(AICXError("E_DEPENDENCY_CYCLE", f"step {dependency!r} cannot depend on itself"))
    graph_errors = {"E_DEPENDENCY_UNKNOWN", "E_DEPENDENCY_CYCLE", "E_DEPENDENCIES", "E_STEP_ID", "E_STEP_ID_DUPLICATE"}
    if not any(error.code in graph_errors for error in errors):
        known = {step.get("id"): step for step in clean_steps if isinstance(step.get("id"), str)}
        pending = set(known)
        visited: set[str] = set()
        while pending:
            ready = {step_id for step_id in pending if all(dep in visited for dep in known[step_id].get("depends_on", []))}
            if not ready:
                errors.append(AICXError("E_DEPENDENCY_CYCLE", "step dependencies contain a cycle"))
                break
            visited.update(ready)
            pending.difference_update(ready)
    if errors:
        unique = list(dict.fromkeys((error.code, error.message) for error in errors))
        lines = "\n".join(f"  {code}: {message}" for code, message in unique)
        raise AICXError("E_SPEC_INVALID", f"workflow has {len(unique)} validation error(s):\n{lines}")
