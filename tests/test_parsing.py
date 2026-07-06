from __future__ import annotations

from axon.parsing import PythonAstParser


def test_python_parser_records_symbols_calls_imports(fixture_repo):
    repo = fixture_repo()
    facts = PythonAstParser().parse_file(repo / "calc" / "api.py", repo)

    assert [s.name for s in facts.symbols] == ["ratio"]
    assert ("ratio", "divide") in facts.calls
    assert "calc.core" in facts.imports


def test_python_parser_parse_error_no_crash(tmp_path):
    path = tmp_path / "bad.py"
    path.write_text("def nope(:\n", encoding="utf-8")

    facts = PythonAstParser().parse_file(path, tmp_path)

    assert facts.parse_error is not None
    assert facts.symbols == []
