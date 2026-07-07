from __future__ import annotations

import pytest

from axon.tools.refute import refute
from axon.tools.sast import sast_scan


def _finding(repo, marker: str) -> dict:
    for finding in sast_scan(str(repo))["findings"]:
        if marker in finding["snippet"]:
            return finding
    raise AssertionError(f"missing finding for {marker}")


def test_refute_static_mode_only(vuln_repo):
    finding = _finding(vuln_repo, "TP_CWE78")

    with pytest.raises(ValueError, match="static"):
        refute(str(vuln_repo), finding, mode="poc")


@pytest.mark.parametrize(
    ("marker", "challenge"),
    [
        ("FP_TEST_CONTEXT", "test-context"),
        ("FP_CONSTANT_INPUT", "constant-input"),
        ("FP_SANITIZED", "sanitized"),
    ],
)
def test_refute_false_positive_challenges(vuln_repo, marker, challenge):
    result = refute(str(vuln_repo), _finding(vuln_repo, marker))

    assert result["verdict"] == "suppress"
    assert result["challenge"] == challenge


def test_refute_true_positive_survives(vuln_repo):
    result = refute(str(vuln_repo), _finding(vuln_repo, "TP_CWE89"))

    assert result["verdict"] == "report"
