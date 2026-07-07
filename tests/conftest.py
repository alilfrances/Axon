from __future__ import annotations

from pathlib import Path
import subprocess

import pytest


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Keep central-store writes (~/.axon/data) out of the real home dir."""
    monkeypatch.setenv("AXON_DATA_DIR", str(tmp_path / "axon_data"))


def _write_calc_repo(root: Path) -> None:
    (root / "calc").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "calc" / "__init__.py").write_text("", encoding="utf-8")
    (root / "calc" / "core.py").write_text(
        "def add(a, b):\n"
        "    return a + b\n\n"
        "def divide(a, b):\n"
        "    return a / b\n\n"
        "def safe_divide(a, b):\n"
        "    return divide(a, b)\n\n"
        "def use_divide(value):\n"
        "    return divide(value, 2)\n",
        encoding="utf-8",
    )
    (root / "calc" / "api.py").write_text(
        "from calc.core import divide, safe_divide\n\n"
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


@pytest.fixture
def fixture_repo(tmp_path: Path):
    def make_repo() -> Path:
        root = tmp_path / "repo"
        _write_calc_repo(root)
        return root

    return make_repo


@pytest.fixture
def git_fixture_repo(tmp_path: Path):
    def make_repo() -> Path:
        root = tmp_path / "git_repo"
        _write_calc_repo(root)
        (root / ".gitignore").write_text(
            "__pycache__/\n*.pyc\n.pytest_cache/\n.axon/\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "axon@example.test"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "Axon Test"], cwd=root, check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=root, check=True, capture_output=True, text=True)
        return root

    return make_repo


@pytest.fixture
def vuln_repo(tmp_path: Path):
    root = tmp_path / "vuln_repo"
    (root / "app").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / "app" / "vuln.py").write_text(
        "import hashlib\n"
        "import os\n"
        "import pickle\n"
        "import sqlite3\n"
        "import subprocess\n\n"
        "SECRET_TOKEN = \"sk_live_TRUE_CWE798\"\n\n"
        "def run_user_command(cmd):\n"
        "    return subprocess.run(cmd, shell=True)  # TP_CWE78\n\n"
        "def load_user(db, username):\n"
        "    sql = f\"SELECT * FROM users WHERE name = '{username}'\"  # TP_CWE89\n"
        "    return db.execute(sql)\n\n"
        "def render_name(name):\n"
        "    return f\"<h1>{name}</h1>\"  # TP_CWE79\n\n"
        "def read_user_file(base, user_path):\n"
        "    return open(os.path.join(base, user_path)).read()  # TP_CWE22\n\n"
        "def load_pickle(data):\n"
        "    return pickle.loads(data)  # TP_CWE502\n\n"
        "def digest_password(password):\n"
        "    return hashlib.md5(password.encode()).hexdigest()  # TP_CWE327\n",
        encoding="utf-8",
    )
    (root / "app" / "safe.py").write_text(
        "import html\n"
        "import subprocess\n\n"
        "def constant_command():\n"
        "    return subprocess.run(\"echo safe\", shell=True)  # FP_CONSTANT_INPUT\n\n"
        "def render_safe(name):\n"
        "    return f\"<p>{html.escape(name)}</p>\"  # FP_SANITIZED\n",
        encoding="utf-8",
    )
    # Non-production context. Placed under examples/ (not tests/) because
    # Semgrep's built-in defaults pre-exclude tests/, so a finding there would
    # never reach refute. examples/ is scanned, letting refute demonstrate the
    # test-context suppression that protects precision.
    (root / "examples").mkdir()
    (root / "examples" / "demo.py").write_text(
        "import subprocess\n\n"
        "def demo_shell():\n"
        "    subprocess.run(cmd, shell=True)  # FP_TEST_CONTEXT\n",
        encoding="utf-8",
    )
    return root
