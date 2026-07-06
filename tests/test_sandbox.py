from __future__ import annotations

import sys

from axon.sandbox import run_in_sandbox


def test_run_in_sandbox_success(tmp_path):
    result = run_in_sandbox([sys.executable, "-c", "print('ok')"], tmp_path)

    assert result.exit_code == 0
    assert result.stdout.strip() == "ok"
    assert result.timed_out is False


def test_run_in_sandbox_timeout(tmp_path):
    result = run_in_sandbox([sys.executable, "-c", "import time; time.sleep(5)"], tmp_path, timeout_s=1)

    assert result.timed_out is True
    assert result.duration_s < 3
