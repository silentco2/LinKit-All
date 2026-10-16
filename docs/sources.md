# Sources

LinKit All reads jobs from three kinds of place. You choose them in the wizard's **Search**
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
3. **Unsupported.** Pages that need a real browser to draw their jobs, or that answer with a
   bot challenge, are reported as "unsupported" in the run. LinKit All never works around a
   challenge.

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
- **Wuzzuf** (Egypt, Saudi Arabia) has its search pages disallowed in `robots.txt`, so
  LinKit All reads its published job sitemaps instead. It keeps recent jobs whose address
  contains every word of one of your searches, then fetches those pages one every 10
  seconds, as Wuzzuf asks.
- **Forasna** (Egypt, Saudi Arabia) works the same way. Most of its job addresses are in
  Arabic, so use Arabic words in your searches to match them.

!!! warning "Site terms"
    Many job sites do not allow automated access in their terms of use. You are
    responsible for how you use them. Company boards and sitemaps are the gentlest options.

Naukrigulf is planned but not built.

## Politeness: robots.txt and rate limits

- **robots.txt.** Before LinKit All reads a company's own careers page (to look for a
  job board or for jobs), or a Forasna job page, it reads that site's `robots.txt` (once
  per run). If the file is missing (a 4xx answer), everything is allowed. If the site is
  down or errors (5xx or no answer), LinKit All does not crawl it this run. The file is
  read the way RFC 9309 describes: all groups that name `LinKitAll` are merged (otherwise
  the `*` groups), `*` and `$` work inside paths, and the longest matching rule wins (Allow
  wins a tie). A `Crawl-delay` that is slower than LinKit All's own rate is followed.
- **Where robots.txt is not checked.** The ATS feeds (Greenhouse, Lever and the others) are
  public JSON APIs meant for programs. Wuzzuf is built by hand around its published rules:
  it uses only sitemaps and job pages, never the disallowed search pages. The job-site
  library (python-jobspy) makes its own requests. Leaving these two out is a deliberate
  project decision.
- **Rate limits per host.** Normally 2 requests per second per host. Slower for some:
  LinkedIn 1 request per 2 seconds, Wuzzuf and Forasna 1 request per 10 seconds, Workable
  and Workday 1 per second.
- **Retries.** A 429, a 5xx or a network error is retried up to 4 times with growing waits.
- **No bot-challenge tricks.** Nothing here defeats a CAPTCHA or a bot check.

## Duplicates and resuming

- Every page of results is saved as soon as it arrives (a checkpoint). If a run stops, the
  next one carries on from the last page.
- Duplicates are removed by normalized link, by a hash of title, company and location, and
  by a near-duplicate check on titles within a company. The company's own ATS copy of a job
  wins over a job-site copy.
- Descriptions missing from a listing are fetched in the **Enrich** stage.
