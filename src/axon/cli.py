"""Command line interface."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from axon.providers.cortex import CortexProvider
from axon.providers.select import select_provider


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="axon")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve")
    index_cmd = sub.add_parser("index")
    index_cmd.add_argument("path")
    sub.add_parser("doctor")
    args = parser.parse_args(argv)

    if args.cmd == "serve":
        from axon import server

        server.main()
        return 0
    if args.cmd == "index":
        provider = select_provider(Path(args.path), prefer="builtin")
        print(provider.index(Path(args.path)))
        return 0
    if args.cmd == "doctor":
        doctor()
        return 0
    return 2


def doctor() -> None:
    cwd = Path.cwd()
    print(f"python: {sys.version.split()[0]}")
    print(f"rg: {_availability('rg')}")
    print(f"cortex: {'available' if CortexProvider.available() else 'missing'}")
    print(f"semgrep: {_availability('semgrep')}")
    try:
        provider = select_provider(cwd)
        print(f"active_backend: {provider.backend}")
    except Exception as exc:
        print(f"active_backend: unavailable ({type(exc).__name__}: {exc})")


def _availability(name: str) -> str:
    return "available" if shutil.which(name) else "missing"


if __name__ == "__main__":
    raise SystemExit(main())
