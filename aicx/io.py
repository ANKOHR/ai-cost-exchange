from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .errors import AICXError


class UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that does not silently discard repeated keys."""


def _unique_mapping(loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False):
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in result
        except TypeError as exc:
            raise AICXError("E_YAML_KEY", "mapping keys must be scalar values") from exc
        if duplicate:
            raise AICXError("E_YAML_DUPLICATE_KEY", f"duplicate key {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def load_yaml(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.load(handle, Loader=UniqueKeyLoader)
    except AICXError:
        raise
    except FileNotFoundError as exc:
        raise AICXError("E_FILE_NOT_FOUND", f"file not found: {path}") from exc
    except PermissionError as exc:
        raise AICXError("E_FILE_READ", f"cannot read file: {path}") from exc
    except yaml.YAMLError as exc:
        raise AICXError("E_YAML_PARSE", f"invalid YAML in {path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise AICXError("E_YAML_ENCODING", f"file is not valid UTF-8: {path}") from exc


def load_workflow(path: Path) -> dict[str, Any]:
    data = load_yaml(path)
    from .validation import validate_workflow

    validate_workflow(data)
    return data


def as_date(value: Any, field: str) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise AICXError("E_PRICE_DATE", f"{field} must be an ISO date such as 2026-09-01")
