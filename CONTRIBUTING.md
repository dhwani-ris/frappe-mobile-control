# Contributing to Frappe Mobile Control

Thank you for your interest in this project. This document describes how to set up a development environment, run checks, and submit changes.

## Code of conduct

Participation is governed by our [Code of Conduct](CODE_OF_CONDUCT.md). By contributing, you agree to uphold it.

## What to contribute

- Bug fixes and regressions tests
- Documentation improvements (`README.md`, code comments, and any relevant docs)
- Features that fit the scope of this server app (mobile auth endpoints, app configuration/status helpers, and related APIs)
- Test coverage and improvements to developer tooling

For large or API-breaking changes, it helps to open an issue first to agree on direction.

## Development setup

1. **Prerequisites**
   - Python tooling expected by the repo (see its docs / existing setup)
   - Node tooling if you modify web assets (see repo scripts/configs)

2. **Install tooling**
   - If you follow pre-commit (recommended), install it:
     - `pip install pre-commit`
   - Then install hooks:
     - `pre-commit install`

3. **Run locally**
   - Follow the repo’s `README.md` for bench installation and manual testing of the exposed mobile auth APIs.

## Quality checks before you push

Run:

```bash
pre-commit run --all-files
```

This repo uses a `pre-commit` configuration that includes formatting/linting via `ruff` and basic repository hygiene hooks.

## Commit messages

If your CI enforces semantic/conventional commit messages, follow the Conventional Commits format:

`type(scope)?: subject`

## Pull requests

1. Keep changes focused; avoid unrelated refactors in the same PR.
2. Update or add tests when behavior changes.
3. Describe **what** changed and **why** in the PR description. Link related issues when applicable.

Maintainers will review as time allows; feedback may request tests, docs, or smaller follow-up PRs.

## Security

If you believe you have found a security vulnerability, please follow [SECURITY.md](SECURITY.md) instead of filing a public issue.

## License

By contributing, you agree that your contributions will be licensed under the same terms as the project — see [LICENSE](LICENSE).
