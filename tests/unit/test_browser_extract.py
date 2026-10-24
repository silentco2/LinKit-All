from pathlib import Path

from linkit_all.sources.browser_extract import (
    Capture,
    CssRecipe,
    Fields,
    Recipe,
    RecipeCache,
    dom_groups,
    is_challenge,
    run_recipe,
    shape,
    site,
)

PAGE = "https://www.acme.test/careers"
API = "https://www.acme.test/api/jobs"
DATA = {
    "meta": {"total": 3},
    "data": {
        "jobs": [
            {"id": 1, "title": "Backend Engineer", "path": "/jobs/1", "loc": {"city": "Cairo"}},
            {"id": 2, "title": "Data Analyst", "path": "https://jobs.lever.co/acme/2", "loc": {}},
            {"id": 3, "title": "Spy", "path": "https://evil.test/jobs/3"},
            {"id": 4, "title": "", "path": "/jobs/4"},
            {"id": 5, "title": "No link"},
            {"id": 1, "title": "Backend Engineer", "path": "/jobs/1#top"},
        ]
    },
}
FIELDS = Fields(title="title", url="path", location="loc.city")


def cap(html: str = "<html><body></body></html>", **responses: object) -> Capture:
    return Capture(PAGE, html, [], {API: DATA, **responses})


def test_shape_lists_objects_arrays_and_first_item_keys() -> None:
    lines = shape(DATA)
    assert lines[0].startswith("$: object {meta, data}")
    assert "data: object {jobs}" in lines
    jobs = next(ln for ln in lines if ln.startswith("data.jobs: array[6]"))
    assert "id=1" in jobs and "title=Backend Engineer" in jobs and "loc" in jobs
    assert shape([{"a": 1}, {"a": 2}]) == ["$: array[2] of {a=1}"]
    assert shape([]) == ["$: array[0] of nothing"] and shape("text") == []
    big = {f"k{i}": i for i in range(40)}
    assert len(shape(big)[0]) < 400 and shape(big)[0].endswith("...}")  # keys are truncated


def test_dom_groups_find_the_repeated_blocks() -> None:
    items = "".join(
        f'<li class="job"><a href="/jobs/{i}">Role {i}</a><span class="loc">Cairo</span></li>'
        for i in range(5)
    )
    html = (
        "<html><head><script>var x=1</script></head><body><nav><a>A</a><a>B</a></nav>"
        f'<ul id="list" class="jobs">{items}</ul><style>li{{}}</style></body></html>'
    )
    groups = dom_groups(html, PAGE)
    best = groups[0]
    assert best["selector"] == "ul.jobs > li.job" and best["count"] == 5
    assert best["samples"][0] == {"text": "Role 0 Cairo", "href": "https://www.acme.test/jobs/0"}
    assert len(best["samples"]) == 2
    assert dom_groups("<html><body><p>x</p></body></html>", PAGE) == []


def test_api_recipe_maps_fields_resolves_urls_and_drops_bad_items() -> None:
    recipe = Recipe(method="api_response", api_url=API, items_path="data.jobs", fields=FIELDS)
    jobs, method = run_recipe(recipe, cap())
    assert method == "api_response"
    # kept: relative -> absolute, the ATS link; dropped: other site, no title, no link, duplicate
    assert [(j.title, j.url) for j in jobs] == [
        ("Backend Engineer", "https://www.acme.test/jobs/1"),
        ("Data Analyst", "https://jobs.lever.co/acme/2"),
    ]
    assert jobs[0].location == "Cairo" and jobs[0].source == "careers"
    assert jobs[1].ats == "lever" and jobs[0].ats is None


def test_api_recipe_with_a_description_and_dates() -> None:
    data = [{"t": "Dev", "u": "/j/1", "d": "<p>Build <b>things</b></p>", "p": "2026-09-01"}]
    f = Fields(title="t", url="u", description="d", posted="p")
    recipe = Recipe(method="api_response", api_url=API, items_path="$", fields=f)
    (job,) = run_recipe(recipe, Capture(PAGE, "", [], {API: data}))[0]
    assert job.description.split() == ["Build", "things"] and job.posted_at is not None


def test_a_recipe_that_does_not_match_the_captures_yields_nothing() -> None:
    page = cap()
    invented = Recipe(method="api_response", api_url="https://evil.test/api", fields=FIELDS)
    assert run_recipe(invented, page) == ([], "")  # not one of our captures
    for bad in (
        Recipe(method="api_response", api_url=API, items_path="data.nope", fields=FIELDS),
        Recipe(method="api_response", api_url=API, items_path="meta", fields=FIELDS),  # not a list
        Recipe(method="api_response", api_url=API, items_path="data.jobs"),  # no fields
        Recipe(
            method="api_response",
            api_url=API,
            items_path="data.jobs",
            fields=Fields(title="x", url="y"),
        ),
        Recipe(method="css"),  # no selectors
        Recipe(method="json_ld"),  # no JSON-LD captured
    ):
        assert run_recipe(bad, page) == ([], "")


HTML = (
    "<html><body><ul id='l'>"
    "<li class='job'><h3>Backend Engineer</h3><a href='/jobs/1'>Apply</a><i>Cairo</i>"
    "<time datetime='2026-09-01'>1 Sep</time></li>"
    "<li class='job'><h3>Analyst</h3><a href='https://evil.test/x'>Apply</a></li>"
    "<li class='job'><h3>Designer</h3><a href='mailto:a@b.c'>Apply</a></li>"
    "<li class='job'><a href='/jobs/4'><h3>Whole item link</h3></a></li>"
    "</ul></body></html>"
)


def test_css_recipe_reads_the_rendered_html() -> None:
    css = CssRecipe(item="li.job", title="h3", link="a", location="i", posted="time")
    jobs, method = run_recipe(Recipe(method="css", css=css), Capture(PAGE, HTML))
    assert method == "css"
    assert [(j.title, j.url) for j in jobs] == [
        ("Backend Engineer", "https://www.acme.test/jobs/1"),
        ("Whole item link", "https://www.acme.test/jobs/4"),
    ]
    assert jobs[0].location == "Cairo" and jobs[0].posted_at is not None
    cards = (
        "<body><a class='c' href='/j/1'><h3>One</h3></a><a class='c' href='/j/2'><h3>Two</h3></a>"
    )
    whole = Recipe(method="css", css=CssRecipe(item="a.c", title="h3", link=":scope"))
    assert [j.url for j in run_recipe(whole, Capture(PAGE, cards))[0]] == [
        "https://www.acme.test/j/1",
        "https://www.acme.test/j/2",
    ]
    broken = Recipe(method="css", css=CssRecipe(item="li[", title="h3", link="a"))
    assert run_recipe(broken, Capture(PAGE, HTML)) == ([], "")


def test_zero_jobs_falls_through_json_ld_then_api_then_css() -> None:
    css = CssRecipe(item="li.job", title="h3", link="a")
    wrong_api = Recipe(
        method="api_response", api_url=API, items_path="nope", fields=FIELDS, css=css
    )
    page = Capture(PAGE, HTML, [], {API: DATA})
    jobs, method = run_recipe(wrong_api, page)
    assert method == "css" and len(jobs) == 2
    page.json_ld = [{"@type": "JobPosting", "title": "From JSON-LD", "url": "/jobs/9"}]
    jobs, method = run_recipe(wrong_api.model_copy(update={"method": "css"}), page)
    assert method == "css"  # the chosen method runs first when it works
    jobs, method = run_recipe(wrong_api, page)
    assert method == "json_ld" and jobs[0].title == "From JSON-LD"  # then json_ld before api/css


def test_recipe_cache_keeps_parameters_only(tmp_path: Path) -> None:
    cache = RecipeCache(tmp_path / "careers" / "recipes.json")
    assert cache.get("acme.test") is None
    cache.put("acme.test", Recipe(method="api_response", api_url=API, fields=FIELDS, reason="why"))
    text = cache.path.read_text("utf-8")
    assert "saved_at" in text and "why" not in text and "Backend" not in text
    got = cache.get("acme.test")
    assert got is not None and got.api_url == API and got.fields == FIELDS
    cache.drop("acme.test")
    assert cache.get("acme.test") is None
    cache.path.write_text("{not json", "utf-8")
    assert cache.get("acme.test") is None  # a damaged file is just an empty cache


def test_helpers() -> None:
    assert site("https://careers.acme.co.uk/x") == "acme.co.uk" and site(PAGE) == "acme.test"
    assert is_challenge(200, "Just a moment...", "") and not is_challenge(200, "Careers", "captcha")
    assert is_challenge(403, "Careers", "<p>Please verify you are human</p>")
