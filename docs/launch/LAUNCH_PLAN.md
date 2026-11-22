# LinKit All — discoverability & launch plan (agent checklist)

Repo: `silentco2/LinKit-All` · Version: 1.0.0 (PyPI live, Pages live) · Audit date: 2026-11-22

## Rules for the agent

- Work on a branch `launch/discoverability`, one commit per phase, open one PR. Do not push to `main` directly.
- Never post to social networks, open PRs on other people's repos, or submit forms on directories. Draft them in `docs/launch/` and stop for the maintainer.
- Every number written anywhere must match the current README/scorecard. Don't invent stats, users or stars.
- Keep the honest tone of the project: bold headline, but no claim the benchmarks do not back.
- After each phase, run its **Verify** step and tick the boxes in this file.

## Status (2026-11-22, branch `launch/discoverability`)

Ticked = done in this branch or on GitHub. **(maintainer)** = needs your account, a purchase or
a merge. Where the work differs from the plan:

- **Audit was partly stale:** description, homepage, 19 topics and the v1.0.0 Release already
  existed. Set to the plan's description and 20 topics; Discussions turned on; the release notes
  now start with the GIF and the install command.
- **Phase 1 issues:** #6 Workday, #7 iCIMS, #8 LibreOffice for macOS/Linux, #9 add a job board
  (pinned: #6, #7, #9; GitHub allows 3). Discussions #10 "Show your setup", #11 welcome.
- **Hook:** the first option, reworded to "tailors your CV in small checked edits": the
  benchmark lets 2 of 19 dishonest edits through, so "without inventing anything" and "never
  lies" would overclaim.
- **Phase 3:** `CLAUDE.md` and `PRODUCT.md` stay at the root (Claude Code and the impeccable
  design skill read them there); `ux-plan.md` moved to `docs/usability/`; `alembic.ini` folded
  into `pyproject.toml`; `brand/README.md` already existed; no FUNDING.yml (only if you want
  sponsorship); code of conduct in `.github/`. Root has 19 visible entries, not 15: the rest are
  files users expect or the build needs.
- **Phase 4:** the landing title uses the Phase 0 descriptor (lowercase) so there is one
  descriptor everywhere. No hreflang: there are no Arabic pages. Lighthouse on the built site:
  performance 99, accessibility 100, best practices 100, SEO 100.
- **Phase 5:** version **1.1.0**, not 1.0.1: `main` carries new features since 1.0.0 (add a
  job, backups, sponsor lists and more). Tag `v1.1.0` after merging.

## What the audit found

| Area | State | Impact |
|---|---|---|
| Name | Search engines treat "LinKit All" as a typo of "LinkedIn"; searching the name returns LinkedIn pages only | Critical |
| GitHub About / topics / website | GitHub's page showed none set (the launch kit lists them as a to-do) | Critical: GitHub search and Google's snippet use these |
| Stars / backlinks | 0 stars, no inbound links | Critical: GitHub search ranks by stars; Google needs links to index |
| README first screen | Strong one-liner, but caveat block before the demo, no badges, no star CTA, long benchmark wall | High |
| Repo root | `CLAUDE.md`, `PRODUCT.md`, `ux-plan.md`, `brand/` sit next to the README | Medium: looks unfinished |
| Docs site | Good title, meta, OG, JSON-LD, sitemap. But it lives on a github.io subpath (no root `robots.txt` you control) | Medium |
| Release page | Tag `v1.0.0` exists; GitHub Release object not confirmed | Medium |

Already good, keep it: demo GIF, `docs/compare.md`, launch kit, `llms.txt`, CONTRIBUTING/SECURITY, PyPI Trusted Publishing.

---

## Phase 0 — Name (decided: keep "LinKit All")

- [x] Use one fixed descriptor everywhere the name appears in a title:
  **"LinKit All — open-source AI job search & auto-apply (local, private)"**
- [x] Use the exact spelling `LinKit All` everywhere. Rename the extension from "LinkIt Fill" to "LinKit Fill" so the spelling matches.
- [x] **Optional rename to "LinKit": not recommended.** Skipped. `linkit` is taken on PyPI and 1,455 GitHub repos already use the word (MediaTek LinkIt and others), so it would rank worse than "LinKit All". Skip unless the maintainer says otherwise.
- [x] Note for the maintainer, not legal advice: a name that echoes "LinkedIn" carries some trademark risk. Keep the logo and colours clearly different from LinkedIn's.

## Phase 1 — GitHub repo settings (gh admin)

```bash
R=silentco2/LinKit-All
gh repo edit $R \
  --description "Open-source AI job search that runs on your computer: finds jobs, ranks them against your CV, tailors it honestly and auto-fills applications. Bring your own AI (ChatGPT, Claude, Ollama)." \
  --homepage "https://silentco2.github.io/LinKit-All/" \
  --enable-discussions --enable-issues
gh repo edit $R $(printf -- '--add-topic %s ' \
  job-search auto-apply job-application resume cv resume-tailoring ai-agent llm \
  ollama local-llm playwright browser-automation greenhouse lever workday \
  self-hosted privacy open-source python fastapi angular arabic)
```

- [x] Topics are capped at 20. Drop `angular` or `fastapi` first if the command fails.
- [ ] **(maintainer)** Social preview: the API cannot set it. Leave a manual step for the maintainer: Settings → General → Social preview → upload `docs/assets/social.png`. Check the card reads at thumbnail size: logo, the one-line promise, and a UI shot.
- [x] Release: if `gh release view v1.0.0` fails, create the release. Use the CHANGELOG 1.0.0 section as notes, put the demo GIF at the top, and add the install one-liner.
- [x] Pin 3–5 issues with `good first issue` / `help wanted` labels (new ATS handlers such as Workday and iCIMS are natural ones). Seed Discussions with one Q&A category and a "Show your setup" thread.
- [ ] **(maintainer)** Pin the repo on the maintainer's GitHub profile (manual step).

**Verify:** `gh repo view $R --json description,homepageUrl,repositoryTopics`

## Phase 2 — README rewrite (bold hook, honest details)

Target structure. The first screen must answer *what, for whom, why trust it, how to start*:

```
[logo]  LinKit All
One-line promise (outcome first)
Badges: PyPI version · Python · License · CI · Stars · Downloads
[Install] [Docs] [Compare] [Discussions]
Demo GIF (move it above the caveat block)
"⭐ If it saves you an application, star it — that's how others find it."
## Why LinKit All        ← 3–4 bullets: local/private, CV never invented, sensitive Qs never sent to AI, bring any AI
## Quick start           ← 3 commands, unchanged
## What it does          ← existing 5 steps, each with a small screenshot or icon
## How it compares       ← short 3-column table from docs/compare.md + link
## How well it works     ← 4-line summary + link to the scorecard (move the full tables to docs)
## Limits                ← keep, but shorter (top 4); full list in docs
## Privacy               ← 3 bullets + link
## Roadmap / Contributing / Star history / License
```

- [x] Hook, one of (pick by maintainer):
  - "Your job hunt on autopilot — on your own computer. Finds jobs, tailors your CV without inventing anything, and fills in the applications."
  - "The open-source job-hunting agent that never lies on your CV."
- [x] Turn the "Practice mode" caveat into a selling point under "Why": "Safe by default: Practice mode fills every form but never presses Submit."
- [x] Add the keywords people actually search for once, in natural sentences: *auto apply*, *job application bot*, *AI resume tailoring*, *Greenhouse / Lever / Workday*, *LinkedIn Easy Apply alternative*, *Ollama*.
- [x] Add 2–3 static screenshots (Home, Jobs, Needs you) at a width of about 800px. The GIF alone doesn't show in some previews.
- [x] Add a star-history chart (`api.star-history.com`) near the bottom.
- [x] Add an Arabic line + link: "متوفر بالعربية" → Arabic docs/post. It is a niche no competitor covers.
- [x] Use only absolute image URLs (the README is also the PyPI page).
- [x] Keep it under about 250 lines; move the moved-out detail into `docs/`.

**Verify:** `uv build && twine check dist/*` (PyPI renders it). Open the GitHub preview and check that the first screen at 1280×800 shows the promise, badges, buttons and the start of the GIF.

## Phase 3 — Repo hygiene (looks finished)

- [x] Move `CLAUDE.md`, `PRODUCT.md` and `ux-plan.md` to `.github/` or `docs/internal/`. Update any references, and keep `CLAUDE.md` wherever the maintainer's agent expects it.
- [x] Move `brand/` to `docs/assets/brand/`, or leave it but add a one-line `brand/README.md`.
- [x] Add `.github/FUNDING.yml` (only if the maintainer wants sponsorship), `CODE_OF_CONDUCT.md`, and a PR template.
- [x] Add issue forms: Bug, Site not supported (fields: ATS name, URL), Feature.
- [x] Add a CI badge and make sure `main` is green.

**Verify:** the root listing has 15 entries or fewer, and every root file is one a user expects.

## Phase 4 — Website SEO (silentco2.github.io/LinKit-All)

- [x] Landing `<title>` → "LinKit All — Open-Source AI Job Search & Auto-Apply (Local, Private)". The current `<title>` starts with the brand only.
- [x] Add an H1 that contains "AI job search" and "auto-apply". Keep one H1 per page.
- [x] Add a "Why not LinkedIn Easy Apply bots?" section and a FAQ, with FAQPage JSON-LD (is it safe, does it work on LinkedIn, which AI, is it free, does it lie on my CV).
- [x] Add `softwareVersion`, `author`, `codeRepository` and `screenshot` to the existing SoftwareApplication JSON-LD.
- [x] Add the landing page and every docs page to one sitemap. The current sitemap is under `/docs/` only.
- [x] Add a "comparison" landing page per competitor keyword: `/docs/compare/aihawk/`, `/docs/compare/applypilot/`. People search "AIHawk alternative".
- [x] Add hreflang alternates if Arabic pages exist.
- [x] Recommended: a custom domain (e.g. `linkitall.dev`), which gives a root `robots.txt`, cleaner links and its own authority. Domain purchase is a **maintainer decision**: draft the steps only.
- [ ] **(maintainer)** Google Search Console (a verification tag exists): submit the sitemap and request indexing of `/`, `/docs/`, `/docs/compare/` (manual step). Bing: submit through IndexNow.
- [x] Run Lighthouse on the landing page; fix anything under 90 for SEO and Accessibility.

**Verify:** `curl` the landing page and check the title, meta description, H1, JSON-LD and canonical. Validate with the Rich Results Test (manual).

## Phase 5 — PyPI & package listings

- [x] Set `project.urls` in `pyproject.toml`: Homepage, Documentation, Repository, Changelog, Issues. They appear in the PyPI sidebar and count as backlinks.
- [x] Expand `keywords` with: `auto-apply`, `job-application-bot`, `resume-tailoring`, `linkedin-alternative`, `workday`, `ollama`.
- [ ] **(maintainer, after merge)** Ship as `1.0.1` through the release workflow so PyPI picks up the new README and URLs.

**Verify:** the PyPI page shows the sidebar links and the README renders with images.

## Phase 6 — Backlinks & listings (draft only; maintainer submits)

Write `docs/launch/listings.md` with a ready-to-paste entry (one line + link) for each place:

- [x] Awesome lists: search GitHub for `awesome job search`, `awesome-selfhosted` (fits under its Personal Dashboards/Automation sections, check the rules), `awesome-python`, `awesome-ai-agents`, `awesome-llm-apps`. Record each list's contribution rules.
- [x] Directories: AlternativeTo (as an alternative to AIHawk, LazyApply, Simplify), OpenAlternative, SaaSHub, LibHunt, Console.dev newsletter, TLDR / Python Weekly / Pycoder's Weekly submission forms.
- [x] Arabic dev communities: list the groups and newsletters the maintainer can post in.
- [x] Write a dev.to / Hashnode / Medium article ("How I stopped an AI from lying on my CV: a patch-based tailoring guard"). The technical story earns links better than the product pitch. Draft it in `docs/launch/article.md`.

## Phase 7 — Launch burst (maintainer posts: LinkedIn + X, EN + AR)

GitHub Trending is driven by stars gained in a short window, so concentrate the push into 24–48 hours instead of trickling it.

- [x] Update `docs/launch/` with:
  - LinkedIn EN post and LinkedIn AR post: story first (built it for my own job hunt) + GIF + the one honest number (96% scorecard, with its caveat) + a clear ask: "a ⭐ helps others find it".
  - X thread (EN): 5–7 posts, GIF in post 1, link in the reply (X ranks posts with links lower), compare table as an image.
  - X thread (AR).
  - A 30–45s vertical screen recording script (setup → ranked jobs → filled form) for LinkedIn/X native video.
- [x] Schedule: Day 0 morning, LinkedIn EN plus the X thread. Day 0 evening (Cairo time), the AR posts. Day 1, the article. Days 2–5, one listing or community per day.
- [x] Maintainer's personal network: send a list of about 20 people to message personally (a short note, not a mass DM).
- [x] Note for the maintainer: with only LinkedIn and X, Trending is possible but harder. The ready `show-hn.md` and `reddit.md` drafts are the highest-leverage optional additions if you change your mind.

## Phase 8 — Keep momentum (weeks 2–8)

- [ ] **(ongoing)** Ship a small visible release every 1–2 weeks (new ATS handler, new source). Each release gets a GIF and a post.
- [ ] **(ongoing)** Answer every issue within 24h; label and thank first-time contributors.
- [ ] **(ongoing)** Re-run the scorecard monthly and update the README numbers.
- [x] Track progress weekly in `docs/launch/metrics.md`: stars, PyPI downloads (pypistats), Search Console impressions and position for: `linkit all`, `ai job auto apply open source`, `aihawk alternative`, `auto apply jobs local llm`.

## Definition of done

- Googling `LinKit All github` or `LinKit All job` returns the repo or site on page 1.
- GitHub search for `auto apply` or `job application ai` (sorted by best match) shows the repo on page 1–2.
- The first README screen shows the promise, badges, a CTA and the demo, and PyPI renders the same README.
- Every launch draft and listing is ready in `docs/launch/`, with numbers matching the README.
