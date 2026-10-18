from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).parent.parent


def load_json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


@pytest.fixture
def airports():
    from hongthai.config import load_airports

    return load_airports(ROOT / "airports.json")
