# GitHub Public Repository Security

This repository stores the portable security baseline in git. A few GitHub protections are repository settings and must be enabled in GitHub after the repository is published.

## Required Repository Settings

Enable these in **Settings > Code security and analysis**:

- Dependency graph
- Dependabot alerts
- Dependabot security updates
- Secret scanning
- Push protection for secret scanning
- Code scanning
- Private vulnerability reporting

Enable these in **Settings > Actions > General**:

- Allow GitHub-created actions and verified Marketplace actions only.
- Set workflow permissions to read-only by default.
- Require approval for first-time outside contributors.
- Disable Actions from creating or approving pull requests unless a trusted release workflow explicitly needs it.

Enable these in **Settings > Pull Requests**:

- Automatically delete head branches.
- Require approval before allowing auto-merge.
- Prefer squash merges for a linear history.

## Branch Protection for `main`

Create a branch protection rule or repository ruleset for `main` with:

- Require a pull request before merging.
- Require at least 1 approving review.
- Require review from Code Owners.
- Dismiss stale pull request approvals when new commits are pushed.
- Require conversation resolution before merging.
- Require status checks before merging.
- Require branches to be up to date before merging.
- Require signed commits.
- Require linear history.
- Allow administrators to bypass the above settings for emergency maintenance only.
- Do not allow force pushes.
- Do not allow deletions.

Recommended required status checks:

- `tests / py3.10`
- `tests / py3.11`
- `tests / py3.12`
- `tests / py3.13`
- `package metadata`
- `dependency audit`
- `analyze / python`
- `dependency review`
- `semgrep`
- `gitleaks`

These checks must pass before a pull request can merge into `main`. Do not
configure this rule as advisory-only.

## Admin Bypass Policy

Administrator bypass is allowed so the repository can recover from broken
protection rules, compromised automation, or urgent security fixes. Any bypass
should be rare and documented in the pull request or release notes with:

- why bypass was needed
- which checks were unavailable or intentionally skipped
- the follow-up issue or commit that restores normal protection

## Release Protection

- Protect tags matching `v*`.
- Require signed tags.
- Build release artifacts from GitHub Actions, not from a maintainer workstation.
- Run the `Release Verification` workflow against the exact tag or SHA before publishing.
- Verify package metadata with `twine check`.
- For PyPI publishing, prefer trusted publishing with OpenID Connect instead of long-lived API tokens.

## Maintainer Operating Rules

- Use least-privilege GitHub tokens and rotate any token that may have touched a public log.
- Never paste secrets into issues, pull requests, workflow logs, or test fixtures.
- Treat changes to `.github/`, `.claude-plugin/serve.sh`, dependency metadata, sandboxing, patch application, and process execution as security-sensitive.
- Review Dependabot pull requests before merging; do not auto-merge major updates.
- Keep this document aligned with workflow names whenever checks are renamed.
