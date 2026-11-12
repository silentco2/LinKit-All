# Contributing

Thanks for helping. The full guide is [docs/development.md](docs/development.md). The short version:

## Set up

```bash
uv sync
uv run linkit doctor
uv run linkit            # web page at http://127.0.0.1:8765
```

The web page needs a build first: `cd frontend && npm ci && npx ng build`. Set `LINKIT_DATA_DIR` to a scratch folder to keep your real data apart from experiments.

## Checks before every commit

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

CI runs the same four commands on Windows, macOS and Linux.

## Rules

- Keep changes small and focused. Do not refactor unrelated code.
- Type hints everywhere. ruff and mypy must be clean.
- Every new logic path gets a test.
- A new job source or ATS handler is a plugin, a saved fixture in `tests/fixtures/<name>/`, and tests. See "Adding a job source" in the development guide.
- No live-site calls in CI. Tests use saved HTML or JSON.
- End-to-end apply tests run in dry-run mode only. Never submit a real application in a test.
- Do not swap anything in the tech stack without asking first. If a change seems to conflict with a rule here or in [CLAUDE.md](CLAUDE.md), open an issue and ask.

## Hard constraints

Changes that break these will not be merged:

- No fabricated CV content. Locked facts stay locked.
- No AI-guessed answers to legal or sensitive questions (work authorization, visa, sponsorship, salary, demographics, disability, veteran status, criminal record, legal declarations).
- User data stays local. No telemetry. No hard-coded secrets. Never log passwords, tokens or full CV text.
- Never click the final Submit in dry-run mode.
- Scrapers never defeat CAPTCHAs or bot challenges.

## License

By contributing you agree your work is licensed under AGPL-3.0-or-later, the project license ([LICENSE](LICENSE)).
