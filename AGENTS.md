# Repository Guidelines

## Project Structure & Module Organization

This repository is currently a clean workspace with no source tree, tests, dependency manifests, or Git metadata detected. Keep new code organized by purpose.

Recommended layout:

- `src/` for application code and reusable modules.
- `tests/` for automated tests that mirror the `src/` structure.
- `data/` for small sample inputs only; avoid committing large or sensitive financial datasets.
- `docs/` for design notes, data-source notes, and usage examples.
- `scripts/` for repeatable maintenance or data-processing commands.

## Build, Test, and Development Commands

No build or test commands are configured yet. When adding tooling, document the exact command here and keep it runnable from the repository root.

Examples to add once applicable:

- `python -m pytest` to run Python tests.
- `python -m src.main` to run a Python entry point.
- `npm test` to run JavaScript or TypeScript tests.
- `make build` for a project-level build wrapper.

Prefer checked-in scripts or Make targets for multi-step workflows.

## Coding Style & Naming Conventions

Use descriptive names tied to the financial-statement domain, such as `income_statement_parser` or `cash_flow_loader`. Keep modules small and focused.

Follow the formatter and linter for the language introduced. For Python, prefer 4-space indentation, `snake_case` for files/functions, `PascalCase` for classes, and type hints for public functions. For JavaScript or TypeScript, prefer `camelCase` for variables/functions and `PascalCase` for classes/components.

## Testing Guidelines

Place tests under `tests/` and name them after the behavior under test. Python tests should follow `test_*.py`; JavaScript or TypeScript tests should use `*.test.*` or the convention required by the selected framework.

Include tests for parsing logic, numeric transformations, error handling, missing fields, and malformed statements.

## Commit & Pull Request Guidelines

No Git history is available in this workspace, so no existing commit convention could be inferred. Until one is established, use concise imperative commit messages, for example `Add statement parser tests`.

Pull requests should include a summary, reason for the change, test results, and any data-source or schema implications. Link issues when available and include screenshots only for UI changes.

## Security & Configuration Tips

Do not commit API keys, downloaded filings with restricted licensing, or proprietary financial data. Store local configuration in ignored environment files and provide safe examples such as `.env.example` when configuration becomes necessary.
