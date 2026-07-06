from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def fixture_repo(tmp_path: Path):
    def make_repo() -> Path:
        root = tmp_path / "repo"
        (root / "calc").mkdir(parents=True)
        (root / "tests").mkdir()
        (root / "calc" / "__init__.py").write_text("", encoding="utf-8")
        (root / "calc" / "core.py").write_text(
            "def add(a, b):\n"
            "    return a + b\n\n"
            "def divide(a, b):\n"
            "    return a / b\n\n"
            "def use_divide(value):\n"
            "    return divide(value, 2)\n",
            encoding="utf-8",
        )
        (root / "calc" / "api.py").write_text(
            "from calc.core import divide\n\n"
            "def ratio(a, b):\n"
            "    return divide(a, b)\n",
            encoding="utf-8",
        )
        (root / "tests" / "test_calc.py").write_text(
            "from calc.core import add, divide\n\n"
            "def test_add():\n"
            "    assert add(1, 2) == 3\n\n"
            "def test_divide_zero_returns_none():\n"
            "    assert divide(1, 0) is None\n",
            encoding="utf-8",
        )
        return root

    return make_repo
