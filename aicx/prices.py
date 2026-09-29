from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
import sys
from typing import Any

from .errors import AICXError
from .io import as_date, load_yaml


_SOURCE_ROOT = Path(__file__).resolve().parent.parent
_SOURCE_PRICES_DIR = _SOURCE_ROOT / "data" / "prices"
_INSTALLED_PRICES_DIR = Path(sys.prefix) / "data" / "prices"
DEFAULT_PRICES_DIR = _SOURCE_PRICES_DIR if _SOURCE_PRICES_DIR.is_dir() else _INSTALLED_PRICES_DIR


def _decimal(value: Any, field: str, *, minimum: Decimal = Decimal(0)) -> Decimal:
    if isinstance(value, bool):
        raise AICXError("E_PRICE_VALUE", f"{field} must be numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise AICXError("E_PRICE_VALUE", f"{field} must be numeric") from None
    if not result.is_finite() or result < minimum:
        raise AICXError("E_PRICE_VALUE", f"{field} must be finite and at least {minimum}")
    return result


def validate_price_table(data: Any, path: Path) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise AICXError("E_PRICE_TABLE", f"{path} must contain a YAML mapping")
    provider = data.get("provider")
    if not isinstance(provider, dict) or not isinstance(provider.get("id"), str) or not provider["id"].strip():
        raise AICXError("E_PRICE_PROVIDER", f"{path} requires provider.id")
    version = data.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise AICXError("E_PRICE_VERSION", f"{path}: version must be a positive whole number")
    data["effective_date"] = as_date(data.get("effective_date"), "effective_date").isoformat()
    freshness = data.get("freshness_days")
    if isinstance(freshness, bool) or not isinstance(freshness, int) or freshness < 0:
        raise AICXError("E_PRICE_FRESHNESS", f"{path}: freshness_days must be a non-negative whole number")
    models = data.get("models")
    if not isinstance(models, dict) or not models:
        raise AICXError("E_PRICE_MODELS", f"{path}: models must be a non-empty mapping")
    for model_id, model in models.items():
        if not isinstance(model_id, str) or not isinstance(model, dict):
            raise AICXError("E_PRICE_MODEL", f"{path}: each model must be a named mapping")
        for field in ("input_per_million", "output_per_million", "tokens_per_second"):
            if field not in model:
                raise AICXError("E_PRICE_VALUE", f"{path}: models.{model_id}.{field} is required")
            _decimal(model[field], f"models.{model_id}.{field}", minimum=Decimal("0.0000000001") if field == "tokens_per_second" else Decimal(0))
    architectures = data.get("architectures")
    if not isinstance(architectures, dict) or not architectures:
        raise AICXError("E_PRICE_ARCHITECTURES", f"{path}: architectures must be a non-empty mapping")
    for architecture_id, architecture in architectures.items():
        if not isinstance(architecture_id, str) or not isinstance(architecture, dict):
            raise AICXError("E_PRICE_ARCHITECTURES", f"{path}: each architecture must be a named mapping")
        model_map = architecture.get("model_map")
        if not isinstance(model_map, dict) or not model_map:
            raise AICXError("E_PRICE_ARCHITECTURES", f"{path}: architectures.{architecture_id}.model_map must be a non-empty mapping")
        for logical, physical in model_map.items():
            if not isinstance(logical, str) or not isinstance(physical, str) or physical not in models:
                raise AICXError("E_PRICE_ARCHITECTURES", f"{path}: architectures.{architecture_id} maps {logical!r} to an unknown model")
    default_architecture = data.get("default_architecture")
    if not isinstance(default_architecture, str) or default_architecture not in architectures:
        raise AICXError("E_PRICE_ARCHITECTURES", f"{path}: default_architecture must name an architecture")
    return data


def list_prices(prices_dir: Path) -> list[tuple[dict[str, Any], bool, int]]:
    if not prices_dir.is_dir():
        raise AICXError("E_PRICE_DIR", f"price directory does not exist: {prices_dir}")
    tables: list[tuple[dict[str, Any], bool, int]] = []
    today = date.today()
    for path in sorted(prices_dir.glob("*.yaml")):
        table = validate_price_table(load_yaml(path), path)
        age = (today - as_date(table["effective_date"], "effective_date")).days
        tables.append((table, age > table["freshness_days"], age))
    if not tables:
        raise AICXError("E_PRICE_EMPTY", f"no provider price tables found in {prices_dir}")
    provider_ids = [table["provider"]["id"] for table, _, _ in tables]
    duplicates = sorted({provider_id for provider_id in provider_ids if provider_ids.count(provider_id) > 1})
    if duplicates:
        raise AICXError("E_PROVIDER_DUPLICATE", f"multiple price tables use provider id(s): {', '.join(duplicates)}")
    return tables


def load_price(prices_dir: Path, provider_id: str) -> tuple[dict[str, Any], bool, int]:
    for table, stale, age in list_prices(prices_dir):
        if table["provider"]["id"] == provider_id:
            return table, stale, age
    raise AICXError("E_PROVIDER_UNKNOWN", f"no price table for provider {provider_id!r}")


def stale_warning(table: dict[str, Any], stale: bool, age: int) -> str | None:
    if not stale:
        return None
    return (
        f"Price table {table['provider']['id']} v{table['version']} is stale: "
        f"effective {table['effective_date']}, age {age} days, freshness window {table['freshness_days']} days."
    )
