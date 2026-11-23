# Website SEO: steps only the maintainer can do

These need your accounts or a purchase, so they are written down here instead of done.

## 1. After this branch is merged and the site redeploys

1. Google Search Console (the verification tag is already in the landing page):
   - Sitemaps: submit `https://silentco2.github.io/LinKit-All/sitemap.xml`. It now lists the
     landing page and every docs page.
   - URL inspection: request indexing for `/`, `/docs/`, `/docs/compare/`,
     `/docs/compare/aihawk/`, `/docs/compare/applypilot/` and `/docs/results/`.
2. Bing Webmaster Tools: sign in with the same Google account and import the site from Search
   Console. Bing's IndexNow needs a key file served from the site root; GitHub Pages can serve
   it from `landing/<key>.txt`, but only do it if you keep Bing Webmaster Tools.
3. Rich Results Test (https://search.google.com/test/rich-results) on the landing page: it
   should find SoftwareApplication and FAQPage.
4. GitHub social preview: Settings → General → Social preview → upload `docs/assets/social.png`.
   Check at thumbnail size that the logo, the one-line promise and the UI shot read.
5. Pin the repo on your GitHub profile.

## 2. Optional: a custom domain (your decision; costs money)

Why: a root `robots.txt` you control, shorter links, and links that build the domain's own
authority instead of github.io's. Example: `linkitall.dev` (check availability yourself).

1. Buy the domain at any registrar.
2. DNS: four `A` records for the apex to GitHub Pages (185.199.108.153, 185.199.109.153,
   185.199.110.153, 185.199.111.153) and a `CNAME` for `www` to `silentco2.github.io`.
3. Repo Settings → Pages → Custom domain: enter it, wait for the DNS check, tick Enforce HTTPS.
4. Then in code (a follow-up change): `site_url` in `mkdocs.yml`, `BASE` in
   `scripts/build_site.py`, the canonical/og URLs and JSON-LD in `landing/index.html`,
   `[project.urls]` in `pyproject.toml`, and `docs/llms.txt`. Old github.io links redirect
   automatically.
5. Add the new domain as a property in Search Console and submit its sitemap.
