from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def plan_xml() -> str:
    return (FIXTURES / "plan_8000157.xml").read_text(encoding="utf-8")


@pytest.fixture
def fchg_xml() -> str:
    return (FIXTURES / "fchg_8000157.xml").read_text(encoding="utf-8")
