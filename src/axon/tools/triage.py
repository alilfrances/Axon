"""SAST scan plus static refutation."""

from __future__ import annotations

from axon.tools.refute import refute
from axon.tools.sast import sast_scan


def triage(repo: str) -> dict:
    scan = sast_scan(repo)
    reported: list[dict] = []
    suppressed: list[dict] = []
    for finding in scan["findings"]:
        decision = refute(repo, finding, mode="static")
        if decision["verdict"] == "suppress":
            suppressed.append({"finding": finding, "refutation": decision})
        else:
            reported.append(finding)
    return {
        "reported": reported,
        "suppressed": suppressed,
        "scan": scan,
        "distinct_cwes": sorted({finding["cwe"] for finding in reported}),
        "precision": _precision(reported),
        "note": "static refutation only; suppressed findings require agent adjudication",
    }


def _precision(reported: list[dict]) -> float | None:
    marked = [finding for finding in reported if "TP_" in finding["snippet"] or "TRUE_CWE" in finding["snippet"] or "FP_" in finding["snippet"]]
    if not marked:
        return None
    true = [finding for finding in marked if "TP_" in finding["snippet"] or "TRUE_CWE" in finding["snippet"]]
    return len(true) / len(marked)
