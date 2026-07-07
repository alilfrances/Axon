from __future__ import annotations

import shutil

from axon import server
from axon.tools.sast import sast_scan


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


def test_server_registers_sast_refute_triage():
    tools = server.app.list_tools()
    if hasattr(tools, "__await__"):
        import asyncio

        tools = asyncio.run(tools)

    assert {"sast_scan", "refute", "triage"} <= {tool.name for tool in tools}
