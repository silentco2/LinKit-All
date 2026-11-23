## What this changes

## How it was checked

- [ ] `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy` and `uv run pytest` pass
- [ ] New logic has tests; a new source or handler has a saved fixture (no live-site calls in tests)
- [ ] Nothing fabricates CV content, sends sensitive answers to the AI, or presses Submit in Practice mode
