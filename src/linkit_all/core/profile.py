"""The user's profile: form fields, locked facts, and the base CV file.

CVs arrive as DOCX, ODT, PDF or LaTeX. The base CV is a DOCX in `cvs/`: ODT is converted by
LibreOffice, PDF by pdf2docx (lossy, so the user must approve it before tailoring uses it).
A single-file .tex is its own base (no conversion). The original upload is kept in
`cvs/original/`.
"""

import io
import re
import zipfile
from datetime import date
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel, field_validator, model_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.apply.answers import ApplicationAnswers
from linkit_all.core import geo
from linkit_all.core.models import LockedFact, Profile

MAX_CV_BYTES = 10 * 1024 * 1024
CV_FORMATS = (".docx", ".odt", ".pdf", ".tex")
_CV_KINDS = "DOCX, ODT, PDF and LaTeX (.tex)"
_ODT_MIME = b"application/vnd.oasis.opendocument.text"


class ProfileFields(BaseModel):
    full_name: str = ""
    email: str = ""
    phone: str = ""  # international: "+" and digits; a number typed without "+" is kept as typed
    location: str = ""  # derived "City, State, Country" whenever home_city or home_country is set
    address: str = ""
    postal_code: str = ""
    home_city: str = ""
    home_state: str = ""  # state, governorate or province
    home_country: str = ""  # ISO2
    skills: list[str] = []
    locked_facts: list[str] = []

    @field_validator("phone")
    @classmethod
    def _international(cls, v: str) -> str:
        v = v.strip()
        return "+" + re.sub(r"\D", "", v) if v.startswith("+") else v

    @field_validator("home_country")
    @classmethod
    def _iso2(cls, v: str) -> str:
        v = v.strip().upper()
        if v and not re.fullmatch(r"[A-Z]{2}", v):
            raise ValueError("home_country must be a 2-letter code such as EG")
        return v

    @model_validator(mode="after")
    def _location(self) -> Self:
        if self.home_city.strip() or self.home_country:
            found = geo.country(self.home_country)
            country = (found.name if found else self.home_country) if self.home_country else ""
            self.location = ", ".join(
                x for x in (self.home_city.strip(), self.home_state.strip(), country) if x
            )
        return self


class ProfileIn(ProfileFields):
    """profile.json for `linkit profile import`: the fields plus a path to the CV."""

    full_name: str
    email: str
    cv_path: Path

    @field_validator("cv_path")
    @classmethod
    def _docx(cls, v: Path) -> Path:
        if v.suffix.lower() not in CV_FORMATS:
            raise ValueError(f"only {_CV_KINDS} CVs are supported")
        if not v.is_file():
            raise ValueError(f"file not found: {v}")
        return v


def _row(s: Session) -> Profile:
    row = s.get(Profile, 1)
    if row is None:
        row = Profile(id=1, full_name="", email="", cv_path="")
        s.add(row)
    return row


def load_fields(db: sessionmaker[Session]) -> tuple[ProfileFields, str]:
    """(fields, cv path or "")."""
    with db() as s:
        row = s.get(Profile, 1)
        facts = list(s.scalars(select(LockedFact.text)))
        if row is None:
            return ProfileFields(locked_facts=facts), ""
        fields = ProfileFields(
            full_name=row.full_name,
            email=row.email,
            phone=row.phone,
            location=row.location,
            address=row.address,
            postal_code=row.postal_code,
            home_city=row.home_city,
            home_state=row.home_state,
            home_country=row.home_country,
            skills=row.skills,
            locked_facts=facts,
        )
        return fields, row.cv_path


def save_fields(db: sessionmaker[Session], fields: ProfileFields) -> None:
    with db.begin() as s:
        row = _row(s)
        for key, value in fields.model_dump(
            include=set(ProfileFields.model_fields) - {"locked_facts"}
        ).items():
            setattr(row, key, value)
        s.execute(delete(LockedFact))
        facts = dict.fromkeys(t for f in fields.locked_facts if (t := f.strip()))
        s.add_all(LockedFact(text=t) for t in facts)


def load_answers(db: sessionmaker[Session]) -> ApplicationAnswers:
    with db() as s:
        row = s.get(Profile, 1)
        return ApplicationAnswers.model_validate(row.answers if row else {})


def save_answers(db: sessionmaker[Session], answers: ApplicationAnswers) -> None:
    """Also creates the profile row the answers live on."""
    with db.begin() as s:
        _row(s).answers = answers.model_dump()


def fill_from_cv(db: sessionmaker[Session], cv: Path) -> list[str]:
    """Write what the CV says into EMPTY profile and answer fields; return the keys written.

    Never overwrites a value, never writes a sensitive field (`authorized_countries` stays a
    suggestion). Employers, titles, degrees and schools join the locked facts."""
    from linkit_all.core.infer import cv_links, infer, read_cv
    from linkit_all.tailor.pipeline import cv_segments

    found = infer(read_cv([s.text for s in cv_segments(cv)], cv_links(cv)), date.today())
    fields, _ = load_fields(db)
    answers = load_answers(db)
    mine: dict[str, Any] = {"profile": fields.model_dump(), "answers": answers.model_dump()}
    written: list[str] = []
    for key, item in found.items():
        scope, _, name = key.partition(".")
        if scope not in mine or name not in _FILLABLE[scope] or mine[scope].get(name) not in _EMPTY:
            continue
        mine[scope][name] = item.value
        written.append(key)
    facts = found.get("profile.locked_facts")
    merged = list(dict.fromkeys([*fields.locked_facts, *(facts.value if facts else [])]))
    if not written and merged == fields.locked_facts:
        return []
    save_fields(db, ProfileFields.model_validate({**mine["profile"], "locked_facts": merged}))
    if any(k.startswith("answers.") for k in written):
        save_answers(db, ApplicationAnswers.model_validate(mine["answers"]))
    return written


_EMPTY: tuple[Any, ...] = ("", None, [])
_FILLABLE = {  # the non-sensitive fields a CV may fill
    "profile": {
        "full_name", "email", "phone", "location", "home_city", "home_state", "home_country",
        "skills",
    },
    "answers": {
        "city", "country", "current_company", "current_title",
        "linkedin", "github", "portfolio", "years_experience",
    },
}  # fmt: skip


def _check_cv(ext: str, content: bytes) -> None:
    if ext == ".tex":
        from linkit_all.tailor.latex import load_segments

        try:
            source = content.decode("utf-8")
        except UnicodeDecodeError as e:
            raise ValueError(
                "this LaTeX file is not UTF-8; save it as UTF-8 and upload again"
            ) from e
        if "\\documentclass" not in source or "\\begin{document}" not in source:
            raise ValueError("this is not a complete LaTeX document (needs \\documentclass)")
        if not any(s.text.strip() for s in load_segments(source)):  # also rejects \\input
            raise ValueError("no text found in this LaTeX file")
        return
    if ext == ".pdf":
        if not content.startswith(b"%PDF-"):
            raise ValueError("this file is not a PDF")
        return
    member = "word/document.xml" if ext == ".docx" else "content.xml"
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            names = z.namelist()
            ok = member in names
            if ok and ext == ".odt" and "mimetype" in names:
                ok = z.read("mimetype").strip() == _ODT_MIME
    except zipfile.BadZipFile:
        ok = False
    if not ok:
        raise ValueError(f"this file is not a {'Word' if ext == '.docx' else 'OpenDocument'} file")


def _convert_to_docx(src: Path, out_dir: Path) -> Path:
    """ODT via LibreOffice, PDF via pdf2docx. The result must contain text."""
    from docx import Document
    from pdf2docx import Converter

    from linkit_all.tailor.docx.segments import load_segments
    from linkit_all.tailor.render.libreoffice import RenderError, convert

    try:
        if src.suffix.lower() == ".odt":
            docx = convert(src, "docx", out_dir)
        else:
            docx = out_dir / f"{src.stem}.docx"
            cv = Converter(str(src))
            try:
                cv.convert(str(docx))
            finally:
                cv.close()
        has_text = any(s.text.strip() for s in load_segments(Document(str(docx))))
    except RenderError as e:
        raise ValueError(str(e)) from e
    except Exception as e:
        raise ValueError(f"could not read this file ({type(e).__name__})") from e
    if not has_text:
        raise ValueError("no text found in this CV (a scanned image?); upload a text-based file")
    return docx


def save_cv(db: sessionmaker[Session], data_dir: Path, filename: str, content: bytes) -> Path:
    """Store an uploaded CV and return the base path (a DOCX, or the .tex itself).

    Raises ValueError for bad files.

    DOCX, ODT and LaTeX are approved at once; a converted PDF waits for `approve_cv`."""
    name = re.sub(r"[^\w.\- ]", "_", Path(filename).name)
    ext = Path(name).suffix.lower()
    if ext not in CV_FORMATS or len(name) <= len(ext) + 1:
        raise ValueError(f"only {_CV_KINDS} CVs are supported")
    if len(content) > MAX_CV_BYTES:
        raise ValueError("CV file is larger than 10 MB")
    _check_cv(ext, content)
    cv = data_dir / "cvs" / f"{Path(name).stem}{'.tex' if ext == '.tex' else '.docx'}"
    cv.parent.mkdir(parents=True, exist_ok=True)
    if ext in (".docx", ".tex"):
        cv.write_bytes(content)  # fresh mtime, so the base PDF gets re-rendered
    else:
        original = cv.parent / "original" / name
        original.parent.mkdir(exist_ok=True)
        original.write_bytes(content)
        try:
            _convert_to_docx(original, cv.parent)
        except ValueError:
            original.unlink(missing_ok=True)
            raise
    cv.with_suffix(".pdf").unlink(missing_ok=True)
    with db.begin() as s:
        row = _row(s)
        row.cv_path = str(cv)
        row.cv_source_format = ext[1:]
        row.cv_approved = ext != ".pdf"  # LaTeX is used as uploaded
    return cv


def cv_state(db: sessionmaker[Session]) -> tuple[str, bool]:
    """(source format, approved) of the base CV."""
    with db() as s:
        row = s.get(Profile, 1)
        return (row.cv_source_format, row.cv_approved) if row else ("docx", True)


def approve_cv(db: sessionmaker[Session]) -> bool:
    """The user checked the converted CV. False when there is no CV yet."""
    with db.begin() as s:
        row = s.get(Profile, 1)
        if row is None or not row.cv_path:
            return False
        row.cv_approved = True
        return True


def import_profile(db: sessionmaker[Session], data: ProfileIn, data_dir: Path) -> Path:
    cv = save_cv(db, data_dir, data.cv_path.name, data.cv_path.read_bytes())
    save_fields(db, data)
    return cv
