# Website SEO: steps only the maintainer can do

These need your accounts or a purchase, so they are written down here instead of done.

The site lives at `https://linkit-all.github.io/`, built from this repo by `.github/workflows/docs.yml`
and published to `linkit-all/linkit-all.github.io`. The old address
`https://silentco2.github.io/LinKit-All/` keeps every page as an instant move notice (refresh +
canonical to the same page at the new address). Never turn on Pages for another repo in the
`linkit-all` organization: it would share the address.

## 1. After the move is merged and both sites redeploy

1. Google Search Console:
   - Add a URL-prefix property for `https://linkit-all.github.io/` and verify it. Try the HTML tag
     first: the landing page already carries your `google-site-verification` tag. If Google
     gives a new tag, replace the one in `landing/index.html`.
   - Sitemaps: submit `https://linkit-all.github.io/sitemap.xml` on the new property.
   - On the old property (`https://silentco2.github.io/LinKit-All/`), submit its sitemap again:
     it now lists the old URLs, so Google recrawls them soon and sees each move. Keep the old
     property for a few months and watch the pages move over.
   - The Change of Address tool does not work for github.io addresses: the steps above replace it.
   - URL inspection on the new property: request indexing for `/`, `/docs/`, `/docs/compare/`,
     `/docs/compare/aihawk/`, `/docs/compare/applypilot/` and `/docs/results/`.
2. Bing Webmaster Tools: add `https://linkit-all.github.io/` (import from Search Console).
   IndexNow needs a key file served from the site root: put it at `landing/<key>.txt`.
3. Rich Results Test (https://search.google.com/test/rich-results) on the new landing page: it
   should find SoftwareApplication and FAQPage.
4. Update the links you control outside this repo: PyPI (the next release reads
   `[project.urls]`) and any profile or post you can still edit.
5. GitHub social preview: Settings → General → Social preview → upload `docs/assets/social.png`.
6. Pin the repo on your GitHub profile.

## 2. Optional: a custom domain (your decision; costs money)

Why: shorter links, and links that build the domain's own authority instead of github.io's.
`linkit-all.github.io` already has its own root `robots.txt`.

1. Buy the domain at any registrar.
2. DNS: four `A` records for the apex to GitHub Pages (185.199.108.153, 185.199.109.153,
   185.199.110.153, 185.199.111.153) and a `CNAME` for `www` to `linkit-all.github.io`.
3. `linkit-all/linkit-all.github.io` Settings → Pages → Custom domain: enter it, wait for the
   DNS check, tick Enforce HTTPS. The workflow must then also publish a `CNAME` file.
4. Then in code: `BASE` in `scripts/build_site.py`, `site_url` and `extra.homepage` in
   `mkdocs.yml`, the canonical/og URLs and JSON-LD in `landing/index.html`, `installUrl` in
   `overrides/main.html`, `[project.urls]` in `pyproject.toml`, and `docs/llms.txt`.
5. Add the new domain as a property in Search Console and submit its sitemap.
