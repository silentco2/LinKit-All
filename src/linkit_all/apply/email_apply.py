"""Compose an application email for a job whose apply link is `mailto:` (LinkedIn hiring posts).

The model writes only the middle of the email; greeting and signature are built here from
profile data, so nothing sensitive or invented can slip in there. Sending lives in
`apply.email_send`; the runner decides when (dry run, confirm, caps)."""

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from pydantic import BaseModel, field_validator

from linkit_all.apply.email_send import valid_address
from linkit_all.providers.base import LLMProvider, render

MAX_BODY_WORDS = 180
MAX_SUFFIX = 60
_DASH = "\u2013"

# Words that make a LinkedIn "author" a company page or a team, not a person to greet.
_ORG_WORDS = re.compile(
    r"(?i)\b(inc|ltd|llc|gmbh|co|corp|company|group|recruit\w*|careers?|jobs?|hiring|hr|team|"
    r"talent|staffing|agency|solutions|technologies|systems|consult\w*|services|international|"
    r"holding|bank|university|studio|labs?|network)\b"
)
_NAME_WORD = re.compile(r"^[^\W\d_]+(?:[-'\u2019][^\W\d_]+)*\.?$")


class ApplicationEmail(BaseModel):
    """What the model returns: the email's middle part and an optional subject reference."""

    subject_suffix: str | None = None
    body: str

    @field_validator("body")
    @classmethod
    def _body(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("body is empty")
        if len(v.split()) > MAX_BODY_WORDS:
            raise ValueError(f"body is longer than {MAX_BODY_WORDS} words")
        return v

    @field_validator("subject_suffix")
    @classmethod
    def _suffix(cls, v: str | None) -> str | None:
        v = " ".join((v or "").split())
        if len(v) > MAX_SUFFIX:
            raise ValueError(f"subject_suffix is longer than {MAX_SUFFIX} characters")
        return v or None


@dataclass
class Draft:
    to: str
    subject: str
    body: str


def mailto_address(url: str | None) -> str | None:
    """The one address of a `mailto:` link; None for anything else (lists, bad addresses)."""
    parts = urlparse((url or "").strip())
    if parts.scheme.lower() != "mailto":
        return None
    addr = unquote(parts.path).strip()
    return addr if valid_address(addr) else None


def is_mailto(url: str | None) -> bool:
    return (url or "").strip().lower().startswith("mailto:")


def greeting(author: str | None) -> str:
    """ "Hello Sara," when the post author looks like a person; else "Hello,"."""
    words = (author or "").replace(",", " ").split()
    if (
        1 < len(words) <= 4
        and all(_NAME_WORD.match(w) for w in words)
        and not _ORG_WORDS.search(" ".join(words))
    ):
        return f"Hello {words[0].rstrip('.')},"
    return "Hello,"


def subject_for(title: str, full_name: str, suffix: str | None = None) -> str:
    title, full_name = " ".join(title.split()), " ".join(full_name.split())
    base = (
        f"Application: {title} {_DASH} {full_name}" if title else f"Application {_DASH} {full_name}"
    )
    return f"{base} ({suffix})" if suffix else base


def signature(full_name: str, phone: str, linkedin: str) -> str:
    return "\n".join(["Best regards,", full_name, *(x for x in (phone, linkedin) if x.strip())])


async def compose(
    provider: LLMProvider,
    *,
    to: str,
    job: dict[str, str],
    cv: str,
    profile_facts: str,
    full_name: str,
    phone: str,
    linkedin: str,
    author: str | None,
) -> Draft:
    """Subject and body. `profile_facts` must be the non-sensitive summary (profile_summary)."""
    brief = {**job, "description": job.get("description", "")[:4000]}
    prompt = render("application_email.j2", cv=cv[:6000], profile=profile_facts, job=brief)
    mail = await provider.complete(prompt, ApplicationEmail)
    body = f"{greeting(author)}\n\n{mail.body}\n\n{signature(full_name, phone, linkedin)}"
    return Draft(to, subject_for(job.get("title", ""), full_name, mail.subject_suffix), body)


def attachment_copy(src: str | Path, out_dir: Path, full_name: str) -> Path:
    """The tailored PDF under a name fit for a recruiter's inbox ("Jane Doe - CV.pdf")."""
    safe = re.sub(r"[^\w .-]", "", full_name).strip() or "Candidate"
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / f"{safe} - CV.pdf"
    shutil.copyfile(src, dst)
    return dst
