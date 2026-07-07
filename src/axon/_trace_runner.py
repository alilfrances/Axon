"""Trace one pytest target and emit repo-local executed lines as JSON."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import trace
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    if not argv:
        print(json.dumps({}))
        return 2
    import pytest

    repo = Path.cwd().resolve()
    tracer = trace.Trace(count=True, trace=False)
    with contextlib.redirect_stdout(sys.stderr), contextlib.redirect_stderr(sys.stderr):
        try:
            exit_code = tracer.runfunc(pytest.main, ["-q", "-p", "no:cacheprovider", argv[0]])
        except SystemExit as exc:
            exit_code = int(exc.code or 0)
    lines: dict[str, set[int]] = {}
    for (filename, lineno), _count in tracer.results().counts.items():
        path = Path(filename).resolve()
        try:
            rel = path.relative_to(repo)
        except ValueError:
            continue
        if _skip(rel):
            continue
        lines.setdefault(str(rel), set()).add(int(lineno))
    print(json.dumps({file: sorted(values) for file, values in sorted(lines.items())}))
    return int(exit_code)


def _skip(path: Path) -> bool:
    return any(part in {".venv", "venv", ".tox", ".git", ".axon"} for part in path.parts)


if __name__ == "__main__":
    raise SystemExit(main())
