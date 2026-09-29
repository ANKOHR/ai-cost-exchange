from pathlib import Path

import pytest

from aicx.io import load_workflow
from aicx.prices import DEFAULT_PRICES_DIR, list_prices, load_price


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / "examples" / "support-workflow.yaml"


@pytest.fixture
def workflow():
    return load_workflow(WORKFLOW_PATH)


@pytest.fixture
def price_dir():
    return DEFAULT_PRICES_DIR


@pytest.fixture
def prices(price_dir):
    return list_prices(price_dir)


@pytest.fixture
def openai_table(price_dir):
    return load_price(price_dir, "openai")
