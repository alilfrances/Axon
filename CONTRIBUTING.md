# Contributing

## Development Setup

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,security]"
python -m pytest
```

## Pull Requests

- Keep changes focused and explain the user-visible impact.
- Add or update tests for behavior changes.
- Update docs when commands, packaging, security posture, or public API behavior changes.
- Do not include secrets, private repository data, generated credentials, or large generated files.
- Use the security reporting process in `SECURITY.md` for vulnerabilities.

## Security-Sensitive Changes

Changes to process execution, sandboxing, dependency installation, patch application, MCP input handling, or SAST/refutation logic require an explicit security-impact note in the pull request.

## Release Checklist

- Run the test suite.
- Confirm GitHub security workflows are passing.
- Bump `pyproject.toml`, `.claude-plugin/plugin.json`, and `.claude-plugin/marketplace.json` together.
- Publish release notes that call out security fixes separately from normal bug fixes.
