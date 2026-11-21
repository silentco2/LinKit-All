"""Jobs the user adds one at a time: a link (up to 25), or one link plus the posting's text when
the page cannot be read. They enter at `enriched` with data["manual"]: the hard rules, the
one-per-company rule and the off-title trash skip them (the user picked them); the trust check,
AI score and tiers still apply. A job a hard rule dropped earlier is brought back the same way.
No AI here: the page is read like a careers-page job (JSON-LD, else heading + page text)."""

from typing import Any, Literal

from sqlalchemy.orm import Session, sessionmaker

from linkit_all.core.models import Job, JobEvent, JobState
from linkit_all.core.state import transition
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub, remote_from_text
from linkit_all.sources.careers import MIN_TEXT, Careers, Unsupported
from linkit_all.sources.http import Http
from linkit_all.sources.store import Deduper, _apply_data

MAX_LINKS = 25
SOURCE = "manual"
Status = Literal["added", "brought_back", "duplicate", "unreadable", "needs_text"]
_KEPT_OUT = ("reported", "closed", "company")  # trash reasons a hand-add does not undo


async def read(http: Http, url: str) -> JobStub | Status:
    """The job at `url`, or why not: "unreadable" (dead link, bot check) or "needs_text" (the
    page holds no posting text, usually drawn by JavaScript: paste it instead)."""
    try:
        got = await Careers().read_job(http, url)
    except Unsupported:
        return "unreadable"
    if got is None:
        return "unreadable"
    stub, structured = got
    if not structured and len(stub.description) < MIN_TEXT:
        return "needs_text"
    return stub.model_copy(update={"source": SOURCE})


def pasted(url: str, title: str, company: str, text: str) -> JobStub:
    return JobStub(source=SOURCE, url=url, title=title.strip(), company=company.strip(),
                   description=text.strip(), apply_url=url,
                   remote=remote_from_text(title, text[:500]))  # fmt: skip


MAX_PDF = 10_000_000


def pdf_text(data: bytes) -> str:
    """The text of a posting saved as PDF, for the paste fields. ValueError when it is not a PDF,
    too big, or holds no text (a scan: we do not run OCR)."""
    import pymupdf

    if len(data) > MAX_PDF:
        raise ValueError("this PDF is over 10 MB")
    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            text = "\n".join(page.get_text() for page in doc)
    except Exception as e:  # pymupdf raises its own types for a broken file
        raise ValueError("this file is not a PDF that can be read") from e
    lines = [" ".join(line.split()) for line in text.splitlines()]
    text = "\n".join(lines).strip()
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    if len(text) < MIN_TEXT:
        raise ValueError("this PDF holds no text (a scan?): paste the posting instead")
    return text


def store(db: sessionmaker[Session], stub: JobStub) -> tuple[Status, int]:
    """Save one hand-added job. (status, job id)."""
    hit = detect(stub.apply_url or stub.url) or detect(stub.url)
    stub = stub.model_copy(update={"ats": hit[0] if hit else None})
    with db.begin() as s:
        deduper = Deduper(s)
        if (known := deduper.lookup(stub)) is not None and known.job_id is not None:
            job = s.get_one(Job, known.job_id)
            return _bring_back(s, job), job.id
        url, h, _ = deduper.register(stub)
        job = Job(source=SOURCE, url=url, title=stub.title, company=stub.company,
                  location=stub.location, description=stub.description, posted_at=stub.posted_at,
                  ats=stub.ats, dedupe_hash=h,
                  data={**_apply_data(stub), "manual": True})  # fmt: skip
        s.add(job)
        s.flush()
        s.add(JobEvent(job_id=job.id, to_state=JobState.discovered, message="you added this job",
                       code="added_by_you"))  # fmt: skip
        transition(s, job, JobState.enriched)
        return "added", job.id


def _bring_back(s: Session, job: Job) -> Status:
    """A stored copy: one a hard rule (or the off-title trash) dropped comes back as hand-added."""
    data: dict[str, Any] = job.data
    if (
        job.state != JobState.filtered_out
        or data.get("trash") in _KEPT_OUT
        or data.get("trust_filter")  # a scam / ghost: the user clears it with "not a scam"
    ):
        return "duplicate"
    job.data = {k: v for k, v in data.items() if k not in ("trash", "company_rule")} | {
        "manual": True
    }
    transition(s, job, JobState.enriched, "you added this job", code="added_by_you")
    return "brought_back"
