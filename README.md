# LinKit All

Local, open-source AI job search and auto-apply: discover jobs from boards and
career pages, rank them against your CV, tailor the CV per job with minimal
word-level edits, and apply — all from a local web UI. Bring your own AI
(Codex CLI, Claude CLI, or an API key).

> Status: early development. Nothing applies to jobs yet.

## Requirements
- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- [LibreOffice](https://www.libreoffice.org/download/) (renders tailored CVs to PDF)
- Google Chrome (for applying, later phases)

## Development
```bash
uv sync
uv run linkit doctor
uv run pytest
cd frontend && npm ci && npm run build   # builds the UI into src/linkit_all/static
uv run linkit                            # opens the UI at http://127.0.0.1:8765
```
UI hot reload: run `uv run linkit serve --no-open` with
`LINKIT_DEV_ORIGINS='["http://localhost:4200"]'`, then `npm start` in `frontend/`.

## License
AGPL-3.0-or-later. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
