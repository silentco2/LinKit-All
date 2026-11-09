# ruff: noqa: RUF001  # en dashes and Arabic-Indic digits are the point of these fixtures
"""Rule-based CV reading and setup suggestions (core/infer.py). Synthetic CVs, no real people."""

from datetime import date
from pathlib import Path

from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT

from linkit_all.core.infer import (
    CvFacts,
    Experience,
    cv_links,
    infer,
    read_cv,
    years_experience,
)

TODAY = date(2026, 1, 1)

EN_CV = [
    "Sara Ahmed",
    "Backend Engineer",
    "Cairo, Egypt | +20 100 123 4567 | sara.ahmed@example.com",
    "linkedin.com/in/sara-ahmed | github.com/saraahmed | https://sara.dev",
    "SUMMARY",
    "Backend engineer focused on APIs.",
    "EXPERIENCE",
    "Backend Engineer at Acme Corp | Jan 2021 - Present",
    "• Built FastAPI services with PostgreSQL (2022 - 2023)",
    "Software Developer — Globex | 03/2018 – 12/2020",
    "• Maintained the billing system",
    "Python Intern, Initech | Jun 2017 - Aug 2017",
    "EDUCATION",
    "B.Sc. Computer Science, Cairo University, 2013 - 2017",
    "SKILLS",
    "Python, FastAPI, PostgreSQL • Docker | Teamwork",
]

AR_CV = [
    "عبد الرحمن محمد أحمد",
    "مهندس برمجيات",
    "القاهرة، مصر | +٢٠ ١٠٠ ١٢٣ ٤٥٦٧ | abdo@example.com",
    "الخبرات العملية",
    "مهندس برمجيات في شركة النيل | يناير ٢٠٢٠ – حتى الآن",
    "مطور ويب - شركة الأهرام | مارس 2017 - ديسمبر 2019",
    "التعليم",
    "بكالوريوس هندسة الحاسبات - جامعة القاهرة",
    "المهارات",
    "بايثون، SQL، التواصل",
]


def test_english_cv_facts() -> None:
    f = read_cv(EN_CV)
    assert f.full_name == "Sara Ahmed" and not f.name_check
    assert f.email == "sara.ahmed@example.com"
    assert f.phone == "+201001234567"
    assert f.location == "Cairo, Egypt"
    assert f.linkedin == "https://linkedin.com/in/sara-ahmed"
    assert f.github == "https://github.com/saraahmed"
    assert f.portfolio == "https://sara.dev"
    assert [(e.title, e.company, e.current, e.intern) for e in f.experiences] == [
        ("Backend Engineer", "Acme Corp", True, False),
        ("Software Developer", "Globex", False, False),
        ("Python Intern", "Initech", False, True),
    ]
    assert f.experiences[1].start == date(2018, 3, 1) and f.experiences[1].end == date(2020, 12, 1)
    assert f.education == ["B.Sc. Computer Science", "Cairo University"]
    assert {"Python", "FastAPI", "PostgreSQL", "Docker", "Teamwork"} <= set(f.skills)


def test_arabic_cv_facts() -> None:
    f = read_cv(AR_CV)
    assert f.full_name == "عبد الرحمن محمد أحمد"
    assert f.phone == "+201001234567"  # Arabic-Indic digits
    assert f.location == "القاهرة، مصر"
    first = current = f.experiences[0]
    assert (first.title, first.company) == ("مهندس برمجيات", "شركة النيل")
    assert current.current and current.start == date(2020, 1, 1)
    assert f.experiences[1].start == date(2017, 3, 1) and f.experiences[1].end == date(2019, 12, 1)
    assert f.education == ["بكالوريوس هندسة الحاسبات", "جامعة القاهرة"]
    assert {"بايثون", "SQL", "التواصل"} <= set(f.skills)
    out = infer(f, TODAY)
    assert out["answers.country"].value == "Egypt"
    assert out["answers.city"].value == "القاهرة"
    assert out["track"].value == "tech"


def _exp(start: date, end: date | None, **kw: bool) -> Experience:
    return Experience(start=start, end=end, current=end is None, **kw)


def test_years_union_includes_interns_and_overlaps() -> None:
    facts = CvFacts(
        experiences=[
            _exp(date(2020, 1, 1), date(2022, 1, 1)),
            _exp(date(2021, 1, 1), date(2023, 1, 1)),  # overlaps: union is 2020-2023
        ]
    )
    assert years_experience(facts, TODAY) == 3
    # an internship adds its years (2018-2020 does not overlap 2020-2023)
    facts.experiences.append(_exp(date(2018, 1, 1), date(2020, 1, 1), intern=True))
    assert years_experience(facts, TODAY) == 5
    assert years_experience(CvFacts(), TODAY) is None
    only_intern = CvFacts(experiences=[_exp(date(2015, 1, 1), date(2016, 1, 1), intern=True)])
    assert years_experience(only_intern, TODAY) == 1
    # a current job runs to today
    assert years_experience(CvFacts(experiences=[_exp(date(2021, 1, 1), None)]), TODAY) == 5


def test_en_infer_values_and_levels() -> None:
    out = infer(read_cv(EN_CV), TODAY)
    assert (
        out["answers.years_experience"].value == 7
    )  # 2021-2026 + 2018-03..2020-12 + 2017 internship
    assert out["answers.years_experience"].source == "years"
    assert out["filters.seniority"].value == ["senior", "lead"]
    assert out["filters.title_exclude"].value == ["intern", "junior"]
    assert out["answers.current_title"].value == "Backend Engineer"
    assert out["answers.current_company"].value == "Acme Corp"
    assert out["answers.current_title"].check and out["answers.current_company"].check
    assert out["track"].value == "tech" and out["track"].level == "suggest"
    assert out["search.queries"].value == [
        "Backend Engineer",
        "Software Developer",
    ]  # no intern title
    assert out["search.queries"].level == "suggest"
    assert out["answers.city"].value == "Cairo" and out["answers.country"].value == "Egypt"
    locked = out["profile.locked_facts"].value
    assert {"Acme Corp", "Globex", "Initech", "Backend Engineer", "Cairo University"} <= set(locked)
    for key, iv in out.items():
        expected = (
            "suggest"
            if key in {"track", "search.queries", "answers.authorized_countries"}
            else "auto"
        )
        assert iv.level == expected, key


def test_intern_title_is_a_query_only_when_nothing_else() -> None:
    only = CvFacts(
        experiences=[Experience(title="Python Intern", start=date(2025, 1, 1), intern=True)]
    )
    assert infer(only, TODAY)["search.queries"].value == ["Python Intern"]  # kept as written
    other = CvFacts(
        experiences=[
            Experience(title="Python Intern", start=date(2025, 1, 1), intern=True),
            Experience(title="Senior Developer", start=date(2020, 1, 1), end=date(2024, 1, 1)),
        ]
    )
    assert infer(other, TODAY)["search.queries"].value == ["Developer"]


def test_authorized_countries_is_only_a_suggestion() -> None:
    iv = infer(read_cv(EN_CV), TODAY)["answers.authorized_countries"]
    assert iv.level == "suggest" and iv.value == ["Egypt"] and iv.source == "country"


def test_seniority_band_and_title_raise() -> None:
    def band(title: str, start: date) -> list[str]:
        facts = CvFacts(
            experiences=[Experience(title=title, company="X", start=start, current=True)]
        )
        return infer(facts, TODAY)["filters.seniority"].value  # type: ignore[no-any-return]

    assert band("Analyst", date(2025, 6, 1)) == ["intern", "junior"]
    assert band("Analyst", date(2024, 1, 1)) == ["junior", "mid"]
    assert band("Analyst", date(2022, 1, 1)) == ["mid", "senior"]
    assert band("Senior Analyst", date(2022, 1, 1)) == ["senior", "lead"]  # raised one band
    assert band("Analyst", date(2012, 1, 1)) == ["lead", "manager", "executive"]
    # A level the title names wins over the years: that level and the one above it.
    assert band("Head of Sales", date(2012, 1, 1)) == ["manager", "executive"]
    assert band("Senior Accountant", date(2019, 1, 1)) == ["senior", "lead"]  # 7 years
    assert band("Junior Accountant", date(2012, 1, 1)) == ["junior", "mid"]
    assert band("Team Lead", date(2024, 1, 1)) == ["lead", "manager"]
    assert band("Marketing Intern", date(2012, 1, 1)) == ["intern", "junior"]
    assert band("محاسب كبير", date(2019, 1, 1)) == ["senior", "lead"]
    facts = CvFacts(experiences=[Experience(title="Analyst", start=date(2022, 1, 1), current=True)])
    assert infer(facts, TODAY)["filters.title_exclude"].value == [
        "intern",
        "director",
        "vp",
        "head of",
    ]


def test_track_tech_vs_general() -> None:
    tech_skills = CvFacts(skills=["Python", "docker", "SQL"])
    assert infer(tech_skills, TODAY)["track"].value == "tech"
    tech_title = CvFacts(
        experiences=[Experience(title="QA Tester", start=date(2020, 1, 1), end=date(2021, 1, 1))]
    )
    assert infer(tech_title, TODAY)["track"].value == "tech"  # "QA" is a tech title word
    tech_title = CvFacts(
        experiences=[Experience(title="Data Analyst", start=date(2020, 1, 1), end=date(2021, 1, 1))]
    )
    assert infer(tech_title, TODAY)["track"].value == "tech"
    general = read_cv(
        [
            "Mona Samir",
            "EXPERIENCE",
            "Accountant at Delta Trading | 2019 - 2024",
            "SKILLS",
            "Excel, Accounting, Python",
        ]
    )
    assert infer(general, TODAY)["track"].value == "general"
    civil = CvFacts(
        experiences=[Experience(title="Civil Engineer", start=date(2020, 1, 1), current=True)]
    )
    assert infer(civil, TODAY)["track"].value == "general"


def test_queries_strip_seniority_and_dedupe() -> None:
    exps = [
        Experience(title="Senior Backend Engineer", start=date(2022, 1, 1), current=True),
        Experience(title="Backend Engineer", start=date(2019, 1, 1), end=date(2022, 1, 1)),
        Experience(title="Jr. Developer", start=date(2017, 1, 1), end=date(2019, 1, 1)),
        Experience(title="Head of Data", start=date(2016, 1, 1), end=date(2017, 1, 1)),
    ]
    q = infer(CvFacts(experiences=exps), TODAY)["search.queries"].value
    assert q == ["Backend Engineer", "Developer", "Data"]
    many = [
        Experience(title=f"Role{i}", start=date(2000 + i, 1, 1), end=date(2000 + i, 6, 1))
        for i in range(8)
    ]
    assert len(infer(CvFacts(experiences=many), TODAY)["search.queries"].value) == 5


def test_missing_data_omits_keys() -> None:
    assert infer(CvFacts(), TODAY) == {}
    out = infer(read_cv(["Sara Ahmed", "sara@example.com"]), TODAY)
    assert set(out) == {
        "profile.full_name",
        "profile.email",
    }
    assert read_cv([]) == CvFacts()


def test_ambiguous_name_is_flagged() -> None:
    f = read_cv(["Sara Ahmed", "Cairo Egypt", "sara@example.com"])
    assert f.full_name == "Sara Ahmed" and f.name_check
    assert infer(f, TODAY)["profile.full_name"].check


def test_cv_links_and_link_preference(tmp_path: Path) -> None:
    doc = Document()
    p = doc.add_paragraph("Reach me: ")
    for text, url in [
        ("LinkedIn", "https://www.linkedin.com/in/sara-ahmed"),
        ("email", "mailto:sara@real.example"),
        ("call", "tel:+201001234567"),
        ("site", "https://sara.example/portfolio"),
    ]:
        rid = doc.part.relate_to(url, RT.HYPERLINK, is_external=True)
        # minimal w:hyperlink element so the relationship is a real used link
        from docx.oxml import parse_xml
        from docx.oxml.ns import nsdecls, qn

        h = parse_xml(
            f'<w:hyperlink {nsdecls("w", "r")} r:id="{rid}"><w:r><w:t>{text}</w:t></w:r></w:hyperlink>'
        )
        assert h.get(qn("r:id")) == rid
        p._p.append(h)
    path = tmp_path / "cv.docx"
    doc.save(str(path))
    links = cv_links(path)
    assert "https://www.linkedin.com/in/sara-ahmed" in links and "mailto:sara@real.example" in links
    assert cv_links(tmp_path / "cv.tex") == []
    # visible text says nothing; the link targets win
    f = read_cv(["Sara Ahmed", "LinkedIn | email | call | site"], links)
    assert f.linkedin == "https://www.linkedin.com/in/sara-ahmed"
    assert f.email == "sara@real.example"
    assert f.phone == "+201001234567"
    assert f.portfolio == "https://sara.example/portfolio"


def test_experience_formats() -> None:
    lines = [
        "EXPERIENCE",
        "Acme | Sales Manager | 2019 - 2022",
        "Sales Executive, Beta Co 03/2015 – 06/2017",
        "Gamma Ltd",
        "Account Manager",
        "2022 — Now",
        "Delta (Jan 2013 to Dec 2014)",
        "Cashier",
    ]
    exps = read_cv(lines).experiences
    assert [(e.title, e.company) for e in exps[:3]] == [
        ("Sales Manager", "Acme"),
        ("Sales Executive", "Beta Co"),
        ("Account Manager", "Gamma Ltd"),
    ]
    assert exps[2].current and exps[2].start == date(2022, 1, 1)
    assert exps[3].start == date(2013, 1, 1) and exps[3].end == date(2014, 12, 1)


def test_internship_only_pdf_cv(tmp_path: Path) -> None:
    """P3 of the UX7 round: one internship, a PDF whose font prints the dash as a middle dot."""
    import pymupdf
    from docx import Document
    from pdf2docx import Converter

    from linkit_all.tailor.docx.segments import load_segments

    lines = [
        "Youssef Kamal",
        "Marketing Graduate",
        "Riyadh, Saudi Arabia  |  youssef.k@example.com  |  +966 50 123 4567",
        "",
        "Experience",
        "Marketing Intern at Saudi Retail Co  |  Jun 2025 – Dec 2025",
        "",
        "Skills",
        "Social media, Canva, Google Analytics",
        "",
        "Education",
        "BBA Marketing, King Saud University 2025",
    ]
    pdf, docx = tmp_path / "cv.pdf", tmp_path / "cv.docx"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    for i, line in enumerate(lines):
        page.insert_text((50, 60 + 20 * i), line, fontsize=11, fontname="helv")
    doc.save(str(pdf))
    conv = Converter(str(pdf))
    conv.convert(str(docx))
    conv.close()
    texts = [s.text for s in load_segments(Document(str(docx))) if s.text.strip()]

    facts = read_cv(texts)
    assert [(e.title, e.company, e.intern) for e in facts.experiences] == [
        ("Marketing Intern", "Saudi Retail Co", True)
    ]
    got = infer(facts, date(2026, 11, 1))
    assert got["answers.years_experience"].value == 0
    assert got["answers.years_experience"].note == "under_one_year"
    assert got["search.queries"].value == ["Marketing Intern"]
    assert got["filters.seniority"].value == ["intern", "junior"]
    assert got["answers.current_title"].value == "Marketing Intern"
    assert got["answers.current_company"].value == "Saudi Retail Co"
    assert got["answers.current_company"].level == "suggest"  # it ended: the user confirms


def test_senior_title_beats_years_band() -> None:
    cv = ["Mona Adel", "Experience", "Senior Accountant at Nile Foods | Mar 2019 - Present"]
    got = infer(read_cv(cv), date(2026, 3, 1))
    assert got["answers.years_experience"].value == 7
    assert got["filters.seniority"].value == ["senior", "lead"]
    assert "note" in got["answers.years_experience"].model_dump() and not got["answers.years_experience"].note  # fmt: skip


def test_github_in_links_is_not_a_skill() -> None:
    lines = [
        "Layla Hassan",
        "Cairo, Egypt | layla@example.com",
        "https://github.com/layla-dev",
        "GitHub | LinkedIn",
        "Skills",
        "Python, Docker",
        "Version control with Git",
    ]
    skills = read_cv(lines, links=["https://github.com/layla-dev"]).skills
    assert "github" not in [x.lower() for x in skills]
    assert {"Python", "Docker", "Git"} <= set(skills)
    # Named in the Skills list itself, it is a skill.
    listed = read_cv(["Skills", "Python, GitHub"], links=["https://github.com/layla-dev"])
    assert "GitHub" in listed.skills
