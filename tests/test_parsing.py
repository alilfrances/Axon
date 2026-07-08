from __future__ import annotations

from axon.parsing import PythonAstParser, iter_source_files


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


def test_iter_source_files_skips_build_dirs(fixture_repo):
    repo = fixture_repo()
    build = repo / "cmake-build-debug" / "_deps" / "googletest-src"
    build.mkdir(parents=True)
    (build / "gen.py").write_text("x = 1\n", encoding="utf-8")

    files = {str(p.relative_to(repo)) for p in iter_source_files(repo, (".py",))}

    assert "calc/core.py" in files
    assert not any("cmake-build" in f or "_deps" in f for f in files)


def test_iter_source_files_honors_gitignore(git_fixture_repo):
    repo = git_fixture_repo()
    (repo / ".gitignore").write_text(
        "__pycache__/\ngenerated/\n", encoding="utf-8"
    )
    gen = repo / "generated"
    gen.mkdir()
    (gen / "artifact.py").write_text("y = 2\n", encoding="utf-8")

    files = {str(p.relative_to(repo)) for p in iter_source_files(repo, (".py",))}

    assert "calc/core.py" in files
    assert "generated/artifact.py" not in files
