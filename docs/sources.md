# Sources

LinKit All reads jobs from four kinds of place. You choose them in the wizard's **Search**
step, or in a `search.toml` file ([example](search.example.toml)).

```toml
[search]
queries = ["python developer", "backend engineer"]
locations = ["Cairo, Egypt", "Remote"]
posted_within_days = 14
max_results_per_query = 200

[sources]
companies = ["https://boards.greenhouse.io/stripe", "lever:palantir"]
jobspy = ["linkedin", "indeed"]
jobspy_country = "egypt"
regional = ["wuzzuf", "bayt"]
```

## 1. Company boards and pasted URLs

This is the best source. Most companies post jobs on an applicant tracking system (ATS), and
those systems have a public JSON feed. It is fast, complete and polite.

| ATS | Example link or shorthand |
|---|---|
| Greenhouse | `https://boards.greenhouse.io/stripe` or `greenhouse:stripe` |
| Lever (global and EU) | `https://jobs.lever.co/palantir` or `lever:palantir` |
| Ashby | `https://jobs.ashbyhq.com/openai` or `ashby:openai` |
| SmartRecruiters | `https://careers.smartrecruiters.com/Company` or `smartrecruiters:Company` |
| Recruitee | `https://company.recruitee.com` or `recruitee:company` |
| Workable | `https://apply.workable.com/company` or `workable:company` |
| Workday | a `...myworkdayjobs.com` link, or `workday:tenant/wdN/site` |

Paste one entry per line in the `companies` list. You do not have to say which ATS it is.
LinKit All works it out from the link. If you paste a company's own careers page (for
example `https://example.com/careers`), it reads the page and looks for an embedded ATS
board. Entries it cannot map are listed as skipped at the end of the run, with the reason.

For Greenhouse, Lever and Ashby you can also apply with a dedicated form handler. For the
rest, LinKit All can find the jobs, and applying uses the [generic AI form agent](applying.md#handlers-and-the-generic-agent).

## 2. Careers pages with no known ATS

If a link is not one of the systems above and has no embedded board, LinKit All tries to read
the page itself. It goes in this order and stops at the first that works:

1. **JSON-LD.** Many career pages describe each job in structured data (`JobPosting`).
2. **Job-like links.** It follows links that look like job pages (for example `/jobs/...`),
   and reads each one. For pages without structured data it reads the page's heading and
   a plainly labelled location. When that is not enough, it sends the page text to your AI,
   10 pages per call. It skips the AI whenever the free steps are enough.
3. **Browser fallback.** Many career pages draw their job list with JavaScript, so the
   plain page has no jobs in it. When steps 1 and 2 find nothing and you have an AI
   connected, LinKit All opens the page once in headless Chrome, waits for the page to settle (at most about 20 seconds), and collects:
   JSON-LD job postings, the JSON the page loaded in the background, and a short summary
   of the repeated blocks in the drawn page. Your AI then picks **how** to read the list:
   the JSON-LD, one of those JSON responses, or CSS selectors. It decides only; LinKit All
   checks the choice against what it captured and runs it. Job links always come from the
   page or the response, never from the AI, and must be on the company's own site or a
   known ATS. If the chosen method finds no jobs, the other methods that the page supports
   are tried (JSON-LD, then the JSON response, then CSS). The jobs found this way then
   follow the same path as in step 2 (a job whose description came with the list skips
   fetching its page).
   This costs **one AI call per site**: the working recipe is saved per site in
   `careers/recipes.json` in the data folder (the method and its settings only, no page
   text) and reused on later runs. If a saved recipe stops finding jobs, it is dropped
   and the AI is asked once more. Chrome is started only when a page needs it, at most two
   pages are open at once and one per site, and it is closed at the end of the discovery run.
4. **Unsupported.** Pages that still give nothing (or when there is no AI or no Chrome), or
   that answer with a bot challenge, are reported as "unsupported" in the run. LinKit All
   never works around a challenge or a CAPTCHA, and the browser never clicks anything.

It follows at most the careers page plus three "next page" links.

## 3. Job sites

| Setting | Sites |
|---|---|
| `jobspy` | `linkedin`, `indeed`, `glassdoor`, `google`, `zip_recruiter` |
| `regional` | `wuzzuf`, `bayt`, `forasna` |

`jobspy_country` sets the country for Indeed (for example `egypt` or `united arab emirates`).
Glassdoor is searched without a country.

- **LinkedIn, Indeed, Glassdoor, Google, ZipRecruiter and Bayt** are read through the
  [python-jobspy](https://github.com/speedyapply/JobSpy) library. LinKit All runs one
  request stream per site. These sites limit automated searches fast, and LinkedIn
  especially. A search that fails is not marked done, so a resumed run tries it again.
- **Wuzzuf** (Egypt, Saudi Arabia) protects its search pages with Cloudflare, so
  LinKit All reads its published job sitemaps instead. It keeps recent jobs whose address
  contains every word of one of your searches, then fetches those pages one every 10
  seconds, as Wuzzuf asks.
- **Forasna** (Egypt, Saudi Arabia) works the same way. Most of its job addresses are in
  Arabic, so use Arabic words in your searches to match them.

!!! warning "Site terms"
    Many job sites do not allow automated access in their terms of use. You are
    responsible for how you use them. Company boards and sitemaps are the gentlest options.

Naukrigulf is planned but not built.

## Discovered company boards

Besides the companies you list, LinKit All can keep its own list of company job boards and
crawl a few hundred of them each run.

```toml
[sources]
use_discovered_boards = true   # default false
boards_per_run = 300           # 0 to 20000; the oldest-crawled boards go first
```

- **Where they come from.** `linkit discover-boards [--ats NAME ...] [--max-per-ats N]` asks
  [Common Crawl](https://commoncrawl.org)'s public URL index which pages it has seen on each
  ATS's hosts (for example `jobs.lever.co/*` or `*.myworkdayjobs.com`), reads the company out
  of each link with the same patterns that recognise pasted links, and stores the new ones.
  It prints how many boards it found and how many were new per ATS. `--max-per-ats` defaults
  to 5000. The command can be run again at any time; it only adds what is missing.
- **Where they are kept.** The `boards` table in the local database: ATS, company slug, where
  it came from (`commoncrawl`, `user` for your own list, `detected` for an ATS board found on a
  company careers page), when it was last crawled, how many jobs it had and how many crawls
  failed in a row.
- **How they are crawled.** With `use_discovered_boards` on, each discover run takes the
  `boards_per_run` active boards that were crawled longest ago (never-crawled first), after the
  companies you listed. Your own companies always run and do not count against that number.
  A board that fails 5 crawls in a row is switched off; one success resets the count.
- **Politeness.** The index gets at most 1 request per second, with the usual retries and
  waits, and a descriptive `User-Agent`. The index's `robots.txt` is not enforced, but its
  `Crawl-delay` still slows the requests.
- A new ATS plugin takes part by setting `cdx_hosts` (a list of Common Crawl URL patterns) next
  to its `url_patterns`.
- The newest Common Crawl collection is sometimes listed before its index is fully served (a
  query answers 404). Such a collection is dropped and the next newest is used, up to three;
  the log says which one each ATS used.

## 4. Telegram channels

Many hiring posts live only in public Telegram channels. LinKit All reads their **web
preview** (`https://t.me/s/<channel>`), the page anyone can open without an account: no login,
no bot, no Telegram API. Turn it on with the **Read jobs from Telegram channels** switch in
the Search step (or put `"telegram"` in `sources.enabled`) and edit the channel list there.

```toml
[sources]
enabled = ["telegram"]
telegram_channels = ["hrlunapark", "@job_python", "https://t.me/zrabota"]
```

- **Channels.** The default list has 95 channels, taken from the open-source
  [freehire](https://github.com/strelov1/freehire) project (MIT licence; see `NOTICE`). They are
  mostly Russian, Ukrainian, Indian and English-language channels, so replace the list with
  channels in your own languages. One per line; `@name` and `t.me/name` links are accepted.
  A channel that does not exist or has its preview switched off is reported as unsupported.
- **What becomes a job.** A post is looked at only if it contains a hiring word (English,
  Russian, Ukrainian, Spanish or Arabic, such as `مطلوب` or `وظيفة`; Arabic letter variants and
  diacritics are ignored) or links to a known job board. This costs no AI.
- **Posts that link to a board** (Greenhouse, Lever, Workable and the others) become jobs
  that apply through that link. No AI is needed.
- **Other posts** are read by your chosen AI, 10 posts per call, about 1,500 characters each.
  A post may hold several jobs or none. The post text is sent to your AI provider, as with your
  CV; nothing else leaves your computer. The AI never invents a job: it only reports what the
  post says, and the post itself is kept as the description. With no AI connected, these
  posts are skipped.
- **Age.** Posts older than 45 days are not stored. Each run reads up to 5 preview pages (about
  100 posts) per channel.
- **Politeness.** One channel at a time, at least 2 seconds between requests.
- **Job address.** A job's address is its post (`https://t.me/<channel>/<id>`), which is what
  stops it being stored twice. A second job found in the same post ends in `?job=2`.

## Politeness: rate limits and Crawl-delay

- **robots.txt is not enforced.** No source refuses a URL because of it (maintainer decision,
  2026-10-25). LinKit All never bypasses bot protection: no TLS-fingerprint spoofing,
  challenge-solving browsers, rotating proxies or fake crawler or app user agents, and a bot
  challenge makes the source report the page as unsupported.
- **Crawl-delay.** Before the first request to a site's HTML pages, LinKit All reads that
  site's `robots.txt` once per run, only for its `Crawl-delay` (the largest value in the
  groups that name `LinKitAll`, otherwise the `*` groups). A delay slower than LinKit All's own
  rate is followed. A missing or failing `robots.txt` changes nothing.
- **Rate limits per host.** Normally 2 requests per second per host. Slower for some:
  LinkedIn 1 request per 2 seconds, Wuzzuf and Forasna 1 request per 10 seconds, Workable
  and Workday (`myworkdayjobs.com`, `myworkdaysite.com`) 1 per second, Workstream 1 per second,
  Join 1.5 per second, HigherMe 1 request per 3 seconds.
- **Which ATS applies.** A job found through a job site, aggregator, company plugin or Telegram
  channel is labelled with that source, but when its apply link is on a known ATS (Greenhouse,
  Lever, Workday...) the job is routed to that ATS's apply handler. The source name is kept.
- **Retries.** A 429, a 5xx or a network error is retried up to 4 times with growing waits.
- **No bot-challenge tricks.** Nothing here defeats a CAPTCHA or a bot check.

## Duplicates and resuming

- Every page of results is saved as soon as it arrives (a checkpoint). If a run stops, the
  next one carries on from the last page.
- Duplicates are removed by normalized link, by a hash of title, company and location, and
  by a near-duplicate check on titles within a company. The company's own ATS copy of a job
  wins over a job-site copy.
- Descriptions missing from a listing are fetched in the **Enrich** stage.
