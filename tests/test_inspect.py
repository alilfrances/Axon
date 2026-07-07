from __future__ import annotations


def test_inspect_captures_exception_frames_and_locals(fixture_repo):
    from axon.tools.inspect_run import inspect_test

    root = fixture_repo()
    result = inspect_test(str(root), "tests/test_calc.py::test_divide_zero_returns_none")
    assert not result["degraded"]
    failure = result["failures"][0]
    assert failure["exception_type"] == "ZeroDivisionError"
    frames = failure["frames"]
    files = [f["file"] for f in frames]
    assert "calc/core.py" in files
    divide_frame = next(f for f in frames if f["function"] == "divide")
    assert divide_frame["locals"]["a"] == "1"
    assert divide_frame["locals"]["b"] == "0"


def test_inspect_passing_test_reports_no_failures(fixture_repo):
    from axon.tools.inspect_run import inspect_test

    root = fixture_repo()
    result = inspect_test(str(root), "tests/test_calc.py::test_add")
    assert result["failures"] == [] and not result["degraded"]


def test_inspect_bogus_target_degrades(fixture_repo):
    from axon.tools.inspect_run import inspect_test

    result = inspect_test(str(fixture_repo()), "tests/nope.py::test_missing")
    assert result["failures"] == []
