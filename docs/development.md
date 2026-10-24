# Development

LinKit All is open source under the **AGPL-3.0-or-later** license. This page is for people who
want to run it from source or contribute.

## Set up

You need [uv](https://docs.astral.sh/uv/) and, for the web page, Node.js (the dev machine uses
Node 24.12 and Angular 21). Users of the finished package never need Node.

```bash
git clone <your fork or checkout>
cd "LinKit All"
uv sync
uv run linkit doctor
uv run linkit            # web page at http://127.0.0.1:8765
```

`uv sync` also installs the development tools (ruff, mypy, pytest, pre-commit and MkDocs
Material). Chrome and LibreOffice are needed for the apply tests and the PDF tests. LibreOffice tests
skip when it is missing.

To keep your real data apart from experiments, point `LINKIT_DATA_DIR` at a scratch folder.

## Checks before every commit

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

pre-commit runs ruff and mypy for you:

```bash
uv run pre-commit install
```

CI runs the same four commands on Windows, macOS and Linux with Python 3.11, 3.12 and 3.13,
and builds the frontend.

## Tests and fixtures

- Every new logic path gets a test.
- **No live-site calls in CI.** Tests use saved HTML or JSON in `tests/fixtures/<name>/`. A
  fixture is a trimmed copy of a real response.
- A new source or ATS handler comes as **a plugin + fixture + tests**.
- The end-to-end apply tests in `tests/e2e/` run in **dry-run mode only**, against saved forms,
  with every network request intercepted. They need Google Chrome. **Never submit a real
  application in a test.**
- Prompts live in `src/linkit_all/providers/prompts/*.j2`, never in code. Every AI answer is
  validated against a Pydantic schema.

## Adding a job source

A source is one module; nothing shared is edited, so many can be written side by side.
`registry()` imports every module in `linkit_all.sources` and its sub-packages and keeps every
`Source` subclass it finds. A module that fails to import is logged and skipped.

1. **Module** in the folder that fits: `src/linkit_all/sources/ats/<name>.py` (a company
   job-board vendor), `aggregators/` (an API listing many employers), `boards/` (a job site) or
   `companies/` (one employer).
2. **Class** `class Acme(Source)` with `name` (unique, lower case), `kind`
   (`"ats"`, `"aggregator"`, `"board"` or `"company"`), and `search()`. Add `fetch_details()` when
   the list has no description, `parallel` for public JSON APIs, `priority` when its copy of a
   duplicate job is better or worse than others. The constructor may take `provider` and
   `data_dir`. Several instances from one module (one per site) come from a module-level
   `def sources(**ctx) -> list[Source]` instead.
3. **ATS only:** `url_patterns = (re.compile(r"acme\.example/([\w-]+)", re.I),)`. The groups,
   joined with `/`, are the board slug. The detector picks them up, and `acme:slug` works in the
   company list.
4. **Aggregators, boards, companies:** implement `tasks(cfg)` returning `Task`s. They are only
   asked when the user lists the `name` under `sources.enabled` in the search config, or when the
   class sets `default_on = True`. ATS plugins run from the company list and need no switch.
5. **Helpers** in `linkit_all.sources.common`: `retry_while` (backoff that honours `Retry-After`),
   `paged` (offset paging with resume), `absolute`, `strip_html`. `Http` already rate-limits per
   host and retries 429 and 5xx.
6. **Tests:** `tests/unit/sources/test_<name>.py` with a trimmed real response in
   `tests/fixtures/<name>/`. The fixtures `load_fixture`, `search_pages`, `fetch_details` and
   `mock_transport` in `tests/unit/sources/conftest.py` do the plumbing. Test the stub fields,
   paging and resume, and the empty and error cases. No live calls.

**No bypassing.** A source reads what the site publishes to everyone, politely. Never use TLS
fingerprint spoofing, challenge-solving browsers, rotating proxies, or fake crawler or app user
agents; do not defeat a CAPTCHA or bot check. Obey robots.txt (`await http.allowed(url)`) unless
the source is a public ATS JSON API or a jobspy site. If a site blocks us, the source reports an
error and the maintainer decides; it does not get a workaround.

## Frontend

The UI is an Angular app in `frontend/` (signals, Tailwind, Chart.js). It builds into
`src/linkit_all/static`, which is gitignored and shipped inside the wheel.

```bash
cd frontend
npm ci
npx ng build             # must finish without warnings
```

For hot reload, run the server with the dev origin allowed, then start Angular:

=== "Windows (PowerShell)"

    ```powershell
    $env:LINKIT_DEV_ORIGINS = '["http://localhost:4200"]'
    uv run linkit serve --no-open
    # in another terminal
    cd frontend; npm start
    ```

=== "macOS / Linux"

    ```bash
    LINKIT_DEV_ORIGINS='["http://localhost:4200"]' uv run linkit serve --no-open
    # in another terminal
    cd frontend && npm start
    ```

## These docs

The docs are Markdown in `docs/`, built with MkDocs Material. The site is built without
analytics and without external fonts.

```bash
uv run mkdocs serve           # live preview
uv run mkdocs build --strict  # must finish with no warnings; writes site/
```

`site/` is gitignored. When behavior changes, update the page that describes it.

## Project layout

```text
src/linkit_all/
  api/         FastAPI routes, WebSocket events, one-run-at-a-time runner, local-only guard
  core/        settings, database models, state machine, search config, scheduler, logging
  providers/   AI adapters (codex_cli, claude_cli, litellm) and prompts/*.j2
  sources/     discovery plugins (ATS APIs, jobspy sites, Wuzzuf, Forasna, careers pages), ATS detector
  matching/    hard rules, local rank, AI scoring
  tailor/      docx/, latex/, render/, verify/, patch rules, pipeline
  apply/       handlers/, agent/, accounts/, vault/, email_verify/, answers, runner
  reports/     report numbers and CSV/PDF export
  cli.py       the `linkit` command
  pipeline.py  the five stages, shared by the CLI and the web page
frontend/      Angular app, built into src/linkit_all/static
tests/         unit/, e2e/ (dry-run only), fixtures/
docs/          these pages, profile.example.json, search.example.toml
scripts/       bundle_libreoffice.py
```

Data flows through one table, `jobs`. Its `state` column is the queue and the single source of
truth. Every transition goes through `core/state.py`, which writes a `job_events` row.

## Contributing rules

These come from the project's `CLAUDE.md`. Read it before a larger change.

- Keep changes **small and focused**, one module per task when you can. Do not refactor
  unrelated code.
- Type hints everywhere. ruff and mypy must be clean.
- Do not swap anything in the tech stack without asking the maintainer.
- If a task seems to conflict with a rule, stop and ask. Do not work around it.
- **Never break the hard constraints:**
    - no fabricated CV content, and locked facts stay locked;
    - no AI-guessed answers to legal or sensitive questions;
    - user data stays local; no telemetry; no hard-coded secrets; never log passwords,
      tokens or full CV text;
    - never click the final Submit in dry-run mode.
- Scrapers obey `robots.txt`, keep per-host rate limits, and never defeat bot challenges.
- Update `CLAUDE.md` when a decision in it changes.

## License

LinKit All is licensed under the **GNU Affero General Public License v3.0 or later**
(`LICENSE`). Some code may be reused from other AGPL projects (ApplyPilot and AIHawk). Any
file with reused code keeps its original copyright header and is listed in `NOTICE` with its
upstream source. The minimal LibreOffice bundle keeps LibreOffice's MPL-2.0 license files.
