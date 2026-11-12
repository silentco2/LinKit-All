# Launch kit

Ready-to-post texts for the 1.0.0 launch. The maintainer posts them; nothing here is posted
automatically. This folder is left out of the docs site.

| File | Where | When |
|---|---|---|
| [show-hn.md](show-hn.md) | Hacker News, "Show HN" | Launch day, a weekday morning US Eastern |
| [reddit.md](reddit.md) | r/opensource, r/selfhosted, r/Python, r/cscareerquestions (check each sub's self-promotion rule first) | Launch day and the days after, one sub a day |
| [product-hunt.md](product-hunt.md) | Product Hunt | A Tuesday to Thursday, 00:01 Pacific |
| [arabic-post.md](arabic-post.md) | LinkedIn, X, Arabic developer groups | Launch day |

Before posting:

1. The PyPI release exists and `uv tool install linkit-all` works on a clean machine.
2. The docs site is live at https://silentco2.github.io/LinKit-All/.
3. The repo has its description, topics and social preview set (see below).
4. Every number in a post still matches the README (benchmark and scorecard change).
5. Someone who writes Arabic natively has read `arabic-post.md`.

## Repository settings (GitHub, Settings > General)

- **Description:** Open-source AI job search that runs on your computer: finds jobs, ranks them
  against your CV, tailors it honestly and fills in applications.
- **Website:** https://silentco2.github.io/LinKit-All/
- **Topics:** `job-search`, `auto-apply`, `job-application`, `resume`, `cv`, `ai-agent`,
  `llm`, `ollama`, `playwright`, `fastapi`, `angular`, `privacy`, `self-hosted`, `arabic`
- **Social preview:** upload `docs/assets/social.png` (1280 × 640).
- **Pages:** Source "GitHub Actions" (the `Docs` workflow deploys on every push to `main`).
