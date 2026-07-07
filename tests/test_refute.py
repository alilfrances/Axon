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


@pytest.mark.parametrize("bad_path", ["../../../etc/passwd", "/etc/passwd"])
def test_refute_rejects_path_escape(tmp_path, bad_path):
    # Untrusted finding path must never read outside the repo.
    result = refute(str(tmp_path), {"path": bad_path, "cwe": "CWE-78", "line": 1, "snippet": "x"})

    assert result["verdict"] == "report"
    assert result["challenge"] == "path-invalid"


def test_refute_sanitizer_spoof_in_comment_does_not_suppress(tmp_path):
    # A `.escape(` mention in a comment must NOT suppress a real vuln.
    (tmp_path / "x.py").write_text('def f(name):\n    return "<h1>" + name + "</h1>"\n')
    result = refute(
        str(tmp_path),
        {"path": "x.py", "cwe": "CWE-79", "line": 2, "snippet": 'return "<h1>" + name  # html.escape( spoof'},
    )

    assert result["verdict"] == "report"


def test_refute_real_sanitizer_still_suppresses(tmp_path):
    (tmp_path / "y.py").write_text('import html\ndef g(name):\n    return f"<p>{html.escape(name)}</p>"\n')
    result = refute(str(tmp_path), {"path": "y.py", "cwe": "CWE-79", "line": 3, "snippet": "x"})

    assert result["verdict"] == "suppress"
    assert result["challenge"] == "sanitized"
