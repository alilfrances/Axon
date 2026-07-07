from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from axon import server
from axon.tools.sast import _semgrep_binary, sast_scan


def test_sast_scan_offline_rules_find_distinct_cwes(vuln_repo):
    result = sast_scan(str(vuln_repo))

    cwes = {finding["cwe"] for finding in result["findings"]}
    assert len(cwes) >= 3
    assert {"CWE-78", "CWE-89", "CWE-79"} <= cwes
    assert result["config"].endswith("axon_python.yml")
    assert "--metrics=off" in result["command"]
    assert all(".axon/" not in f["path"] for f in result["findings"])
    assert all(f["fingerprint"] for f in result["findings"])


def test_sast_binary_fact_is_real_or_reported(vuln_repo):
    result = sast_scan(str(vuln_repo))

    if shutil.which("semgrep"):
        assert result["semgrep_available"] is True
    assert result["findings"]


def test_bundled_semgrep_rules_do_not_flag_axon_non_sql_fstrings():
    rule_text = (Path(__file__).resolve().parents[1] / "src" / "axon" / "rules" / "axon_python.yml").read_text(
        encoding="utf-8"
    )
    assert 'pattern: $SQL = f"..."' not in rule_text
    assert "select|insert|update|delete|drop|alter|create" in rule_text

    if not _semgrep_binary():
        pytest.skip("semgrep is not installed")

    repo = Path(__file__).resolve().parents[1]
    result = sast_scan(str(repo), timeout=120)

    if result["backend"] != "semgrep":
        pytest.skip(f"semgrep unavailable: {result['semgrep_error']}")
    assert [f for f in result["findings"] if f["cwe"] == "CWE-89"] == []


def test_server_registers_sast_refute_triage():
    tools = server.app.list_tools()
    if hasattr(tools, "__await__"):
        import asyncio

        tools = asyncio.run(tools)

    assert {"sast_scan", "refute", "triage"} <= {tool.name for tool in tools}
