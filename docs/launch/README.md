# Launch kit

Ready-to-post texts. The maintainer posts them; nothing here is posted automatically. This
folder is left out of the docs site. Every number must match the README on the day you post
(the benchmark and scorecard change).

## Files

| File | Where | When |
|---|---|---|
| [linkedin-en.md](linkedin-en.md) | LinkedIn, English | Day 0 morning |
| [x-thread-en.md](x-thread-en.md) | X, English thread | Day 0 morning |
| [linkedin-ar.md](linkedin-ar.md) | LinkedIn, Arabic | Day 0 evening (Cairo time) |
| [x-thread-ar.md](x-thread-ar.md) | X, Arabic thread | Day 0 evening (Cairo time) |
| [arabic-post.md](arabic-post.md) | Arabic developer groups (longer version) | Days 2–5 |
| [video-script.md](video-script.md) | 30–45 s vertical video for LinkedIn and X | Record before Day 0 |
| [article.md](article.md) | dev.to, then Hashnode and Medium with the canonical link | Day 1 |
| [listings.md](listings.md) | Awesome lists, directories, newsletters, Arabic communities | Days 2–5, one a day |
| [seo-manual-steps.md](seo-manual-steps.md) | Search Console, Bing, social preview, custom domain | Right after merge |
| [metrics.md](metrics.md) | Weekly tracking | Every week, weeks 1–8 |
| [show-hn.md](show-hn.md), [reddit.md](reddit.md), [product-hunt.md](product-hunt.md) | Optional | See below |

## Schedule

GitHub Trending counts stars gained in a short window, so keep the push inside 24–48 hours.

1. **Before Day 0:** merge, tag `v1.1.0`, check PyPI shows the new README and sidebar links,
   upload the social preview, do [seo-manual-steps.md](seo-manual-steps.md) part 1.
2. **Day 0 morning:** LinkedIn EN + X thread EN.
3. **Day 0 evening (Cairo):** LinkedIn AR + X thread AR.
4. **Day 1:** the article.
5. **Days 2–5:** one listing or community a day from [listings.md](listings.md).

With only LinkedIn and X, Trending is possible but harder. `show-hn.md` and `reddit.md` are the
highest-leverage additions if you change your mind; update their numbers first.

## Your own network

Message about 20 people yourself, one by one, on Day 0: people job hunting now, developers who
star tools they like, and people in Arabic tech communities. A short personal note works better
than a mass DM:

> I just open-sourced the tool I built for my own job hunt: it finds jobs, tailors the CV a few
> words per job and fills in applications, on your own computer. If you're job hunting, I'd love
> your honest feedback: https://github.com/silentco2/LinKit-All

Keep the list of names in your own notes, not in this repository.

## Weeks 2–8

- Ship a small visible release every 1–2 weeks (a new ATS handler, a new source). Each gets a
  GIF and a short post.
- Answer every issue within 24 hours; label and thank first-time contributors.
- Re-run the scorecard monthly and update the README numbers (and these drafts).
- Fill in [metrics.md](metrics.md) every week.

## Before posting

1. `uv tool install linkit-all` works on a clean machine and shows the new version.
2. The docs site is live at https://silentco2.github.io/LinKit-All/.
3. The social preview is uploaded (Settings → General → Social preview).
4. Every number in a post still matches the README.
5. Someone who writes Arabic natively has read the Arabic posts.

## Repository settings (set on 2026-11-22)

- **Description:** Open-source AI job search that runs on your computer: finds jobs, ranks them
  against your CV, tailors it honestly and auto-fills applications. Bring your own AI (ChatGPT,
  Claude, Ollama).
- **Website:** https://silentco2.github.io/LinKit-All/
- **Topics (20, the cap):** `job-search`, `auto-apply`, `job-application`, `resume`, `cv`,
  `resume-tailoring`, `ai-agent`, `llm`, `ollama`, `local-llm`, `playwright`,
  `browser-automation`, `greenhouse`, `lever`, `workday`, `self-hosted`, `privacy`,
  `open-source`, `python`, `arabic`
- **Discussions:** on, with a welcome post and a "Show your setup" thread.
- **Pinned issues:** Workday handler (#6), iCIMS handler (#7), add a job board (#9).
- **Social preview:** upload `docs/assets/social.png` (1280 × 640; regenerate with
  `uv run --no-sync python scripts/make_social_card.py`). Manual: the API can't set it.
- **Pages:** Source "GitHub Actions" (the `Docs` workflow deploys on every push to `main`).
