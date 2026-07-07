from __future__ import annotations

from axon.tools.triage import triage


def test_triage_suppresses_all_planted_fps_without_suppressing_tps(vuln_repo):
    result = triage(str(vuln_repo))
    suppressed_text = "\n".join(item["finding"]["snippet"] for item in result["suppressed"])
    reported_text = "\n".join(item["snippet"] for item in result["reported"])

    for marker in ["FP_TEST_CONTEXT", "FP_CONSTANT_INPUT", "FP_SANITIZED"]:
        assert marker in suppressed_text
    for marker in ["TP_CWE78", "TP_CWE89", "TP_CWE79", "TP_CWE22", "TP_CWE502", "TP_CWE327", "TRUE_CWE798"]:
        assert marker not in suppressed_text
        assert marker in reported_text

    assert result["precision"] == 1.0
    assert len(result["distinct_cwes"]) >= 7
