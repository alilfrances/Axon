"""Run one pytest target and emit exception frames with locals as JSON."""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

import pytest

_MAX_FRAMES = 15
_MAX_LOCALS = 20
_MAX_REPR = 200


def _safe_repr(value: object) -> str:
    try:
        text = repr(value)
    except Exception as exc:
        text = f"<unreprable {type(value).__name__}: {type(exc).__name__}>"
    return text[:_MAX_REPR]


class _Collector:
    def __init__(self, repo: Path):
        self.repo = repo
        self.failures: list[dict] = []

    def pytest_exception_interact(self, node, call, report):
        excinfo = call.excinfo
        if excinfo is None:
            return
        frames: list[dict] = []
        raw = getattr(excinfo, "_excinfo", (None, None, excinfo.value.__traceback__))[2]
        while raw is not None and len(frames) < _MAX_FRAMES * 2:
            frame = raw.tb_frame
            filename = Path(frame.f_code.co_filename)
            try:
                rel = str(filename.resolve().relative_to(self.repo))
            except ValueError:
                raw = raw.tb_next
                continue
            if any(part in {".venv", "venv", ".axon", ".git"} for part in Path(rel).parts):
                raw = raw.tb_next
                continue
            locals_out = {}
            for name, value in list(frame.f_locals.items())[:_MAX_LOCALS]:
                if name.startswith("__"):
                    continue
                locals_out[name] = _safe_repr(value)
            frames.append(
                {
                    "file": rel,
                    "line": raw.tb_lineno,
                    "function": frame.f_code.co_name,
                    "locals": locals_out,
                }
            )
            raw = raw.tb_next
        self.failures.append(
            {
                "test_id": node.nodeid,
                "exception_type": excinfo.type.__name__,
                "message": _safe_repr(excinfo.value),
                "frames": frames[-_MAX_FRAMES:],
            }
        )


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    if not argv:
        print(json.dumps({"failures": [], "exit_code": 2}))
        return 2

    collector = _Collector(Path.cwd().resolve())
    with contextlib.redirect_stdout(sys.stderr):
        exit_code = pytest.main(["-q", "-p", "no:cacheprovider", argv[0]], plugins=[collector])
    print(json.dumps({"failures": collector.failures, "exit_code": int(exit_code)}))
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
