# LinKit All — Master Plan

## Context
`D:\LinKit All` is empty except CLAUDE.md (no git, no code). This plan covers the whole project from first commit to public release,
fixes contradictions in CLAUDE.md, and details the very next step: project init.
Machine state: Python 3.10 system (uv will fetch 3.12), uv 0.12, Node 24, Codex + Claude CLIs on PATH, **LibreOffice and Tectonic not installed**.

## Decisions from interview (to write back into CLAUDE.md)
| Topic | Decision |
|---|---|
| Frontend | Angular (fix §8 "React app" → Angular) |
| Background work | asyncio worker pool in the FastAPI process; `jobs.state` is the queue (drop Huey) |
| ORM | SQLAlchemy 2 typed `Mapped` models + separate Pydantic API schemas (drop SQLModel) |
| Logging | loguru with a redaction filter (drop structlog) |
| CLI | Typer (add to §3) |
| Python | pin 3.12; CI tests 3.11–3.13 |
| License | AGPL-3.0 (code reused from ApplyPilot/AIHawk) + NOTICE with attribution |
| Install | `uv tool install linkit-all`; wheel bundles built Angular UI; `linkit doctor` checks externals |
| PDF render | LibreOffice headless required (doctor prints install link) |
| First user | maintainer's own job search first (DOCX CV, Gmail), then generalize for public |
| MVP sources | ATS APIs + python-jobspy (LinkedIn/Indeed) + regional boards (discovery moves up to phase 2) |
| ToS-risky features | LinkedIn Easy Apply, Indeed Apply, CapSolver: built, **off by default**, warning in UI + docs, low daily caps |
| Email verify | Gmail IMAP + app password; Outlook OAuth stays "later" |
| sqlite-vec | defer: numpy cosine over ≤10k fastembed vectors is enough; add when measured slow |
| APScheduler | phase 7 only (scheduler) |

### Tiered funnel (replaces §5.6 review modes)
- Hard rules + local embedding rank drop obvious mismatches for free → tier `low`.
- Survivors go to AI in **batches of 10–20 short job summaries per call** → score 1–10.
- Default tiers (editable): **8+ high → auto-apply**, **5–7 mid → user approval**, **<5 low → hidden, user may opt in to auto-apply**.
- Tailor **just before applying** (high on queue, mid after approval) — no AI spent on jobs never applied to.

New state machine (`jobs.state`, plus `jobs.tier`):
```
discovered -> enriched -> filtered_out | ranked -> scored
scored -> below_threshold (low) | awaiting_review (mid) | queued_apply (high / approved / low opted-in)
queued_apply -> tailored -> applying -> needs_user -> applied | failed | skipped
```

## Phases (whole project)

### Phase 0 — Init (next step, detailed below)

### Phase 1 — Core
- `core/`: settings (pydantic-settings, platformdirs paths), SQLAlchemy models (jobs, job_events, runs, profile, locked_facts, answers, llm_cache), Alembic baseline, SQLite WAL, state machine with `transition()` writing `job_events`.
- `providers/`: `LLMProvider.complete(prompt, schema)`; adapters `claude_cli`, `codex_cli`, `litellm_api`; JSON validation + 2 retries; prompt-hash cache; usage-limit → clean run pause; Jinja prompts in `providers/prompts/*.j2`.
- `tailor/docx/`: segmenter (body, tables, text boxes, headers/footers via lxml), patch applier (first-run write, keep formatting), patch validators (locked facts, unlisted skills, +10% chars, 15% word cap); `render/` LibreOffice → PDF; `verify/` page count + SSIM + pdfplumber; rollback on failure.
- CLI: `linkit doctor`, `linkit run tailor --job <id>`.
- Exit: tailor the maintainer's real CV against a sample JD; red-line patch list printed; PDF layout diff passes.

### Phase 2 — Discovery + matching
- `sources/`: plugin protocol, Greenhouse/Lever/Ashby JSON APIs, python-jobspy wrapper, regional boards (Wuzzuf, Bayt, Naukrigulf, Forasna — discovery only), ATS detector for pasted URLs.
- aiolimiter per domain, tenacity retries, checkpoint per page, dedupe (normalized URL + hash + rapidfuzz).
- `matching/`: hard rules, fastembed + skills overlap rank, AI batch tiering.
- Tests: saved HTML/JSON fixtures per source, no live calls in CI.
- Exit: one run discovers thousands of jobs and produces high/mid/low tiers within plan limits.

### Phase 3 — UI v1 (Angular)
- FastAPI routers + WebSocket event stream; Angular + Tailwind app built into `src/linkit_all/static`.
- Screens: setup wizard (profile, CV upload/preview, AI test, locked facts), jobs table (virtualized, tier filter), review queue (mid tier approve/reject in bulk), live run, basic report.

### Phase 4 — Apply v1
- Playwright with installed Chrome, persistent profile per site, human pacing, per-site caps, dry-run (never clicks final Submit).
- Handlers: Greenhouse, Lever, Ashby (no accounts). Answer bank (embedding match) → AI draft → Action Center; sensitive categories only from profile.
- Screenshots before submit + on confirmation, trace on failure; success only on confirmation text/email.
- Action Center screen + WebSocket notifications.

### Phase 5 — Apply v2 (accounts)
- Vault (AES-GCM, Argon2id, keyring cache), password generator honoring site rules, save before signup.
- Gmail IMAP verification (regex, AI fallback).
- Workday, iCIMS, Taleo, SmartRecruiters, SuccessFactors handlers.
- Opt-in: LinkedIn Easy Apply, Indeed Apply, CapSolver (warnings + caps).

### Phase 6 — Generic agent
- Generic career-page extractor (JSON-LD → CSS heuristics → AI).
- Generic AI form agent (a11y snapshot → field map JSON → fill → validate → next); model decides, code executes.

### Phase 7 — Later / release
- Local models (Ollama/LM Studio), LaTeX/ODT/PDF CV input, APScheduler runs, Outlook OAuth, reports over time + CSV/PDF export, Vault + Reports screens polished.
- MkDocs Material docs, GitHub repo + Actions (Win/macOS/Linux), first PyPI release.

## Known risks / blockers
- **Plan limits** on Codex/Claude CLIs: batching + cache + clean pause/resume; show calls used per run.
- **CLI flag drift**: detect flags from `--help` at runtime; adapters tested with recorded outputs.
- **DOCX fidelity**: text split across runs, fields, text boxes; LibreOffice vs Word rendering differences → SSIM tolerance tuned on real CVs.
- **Anti-bot / rate limits**: LinkedIn via jobspy blocks quickly; regional sites change HTML → fixtures + fail-soft per source.
- **Workday**: one account per company tenant → vault entries per tenant, IMAP verify each.
- **ToS / account bans** for LinkedIn/Indeed/CapSolver → opt-in only.
- **AGPL**: keep upstream copyright headers on reused files, NOTICE file.
- **Windows**: LibreOffice path discovery (`soffice.exe` not on PATH by default), long paths, Playwright headed Chrome.

## Phase 0 — Init (what gets executed after approval)
1. `git init`, `.gitignore` (Python, uv, Node, `static/` build output, user data), `.gitattributes`.
2. `uv init --lib --package` style project with hatchling; delete generated boilerplate (hello function, sample files). `.python-version` = 3.12.
3. `pyproject.toml`: name `linkit-all`, package `linkit_all`, script `linkit = "linkit_all.cli:app"`, `requires-python >=3.11`, AGPL-3.0.
   - Phase-1 deps: fastapi, uvicorn[standard], pydantic, pydantic-settings, sqlalchemy, alembic, typer, loguru, platformdirs, tenacity, jinja2, litellm, python-docx, lxml, pdfplumber, pymupdf, pillow, scikit-image.
   - Dev group: ruff, mypy, pytest, pre-commit.
   - ruff + mypy (strict on `src/`) + pytest config inside pyproject.
4. Folder tree per §8 (`src/linkit_all/{api,core,providers/prompts,sources,matching,tailor/{docx,render,verify},apply,reports}`, `tests/{unit,fixtures,e2e}`, `docs/`) — `__init__.py` only, no stub code. `frontend/` created in phase 3 by `ng new`.
5. `src/linkit_all/cli.py`: Typer app with `--version` and a real `doctor` (Python version, LibreOffice/soffice, Chrome, `codex`, `claude`, Tectonic optional) — the one piece of working code at init.
6. `.pre-commit-config.yaml` (ruff, ruff-format, mypy), `.github/workflows/ci.yml` (matrix Win/macOS/Linux × 3.11–3.13; idle until pushed).
7. `LICENSE` (AGPL-3.0), `NOTICE` (ApplyPilot/AIHawk attribution), short `README.md`.
8. Update CLAUDE.md: decisions table above, new tier funnel + state machine (§4, §5.3, §5.6), Angular in §8, Typer/loguru/SQLAlchemy/asyncio in §3, build order tweaks (regional discovery → phase 2, ToS-risky features opt-in), keep < 200 lines.
9. One test: `tests/unit/test_cli.py` (doctor runs, returns a report).
10. First commit.

## Verification (Phase 0)
- `uv sync` succeeds on Python 3.12.
- `uv run linkit --version` and `uv run linkit doctor` (should report LibreOffice missing on this machine).
- `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest` all green.
- `pre-commit run --all-files` green; `git log` shows the initial commit.
