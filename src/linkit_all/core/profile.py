"""The user's profile: form fields, locked facts, and the base CV file.

CVs arrive as DOCX, ODT or PDF. The base CV is always a DOCX in `cvs/`: ODT is converted by
LibreOffice, PDF by pdf2docx (lossy, so the user must approve it before tailoring uses it).
The original upload is kept in `cvs/original/`.
"""

import io
import re
import zipfile
from pathlib import Path

from pydantic import BaseModel, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.core.models import LockedFact, Profile

MAX_CV_BYTES = 10 * 1024 * 1024
CV_FORMATS = (".docx", ".odt", ".pdf")
_ODT_MIME = b"application/vnd.oasis.opendocument.text"


class ProfileFields(BaseModel):
    full_name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    skills: list[str] = []
    locked_facts: list[str] = []


class ProfileIn(ProfileFields):
    """profile.json for `linkit profile import`: the fields plus a path to the CV."""

    full_name: str
    email: str
    cv_path: Path

    @field_validator("cv_path")
    @classmethod
    def _docx(cls, v: Path) -> Path:
        if v.suffix.lower() not in CV_FORMATS:
            raise ValueError("only DOCX, ODT and PDF CVs are supported")
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


def _check_cv(ext: str, content: bytes) -> None:
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
    """Store an uploaded CV and return the base DOCX path. Raises ValueError for bad files.

    DOCX and ODT are approved at once; a converted PDF waits for `approve_cv`."""
    name = re.sub(r"[^\w.\- ]", "_", Path(filename).name)
    ext = Path(name).suffix.lower()
    if ext not in CV_FORMATS or len(name) <= len(ext) + 1:
        raise ValueError("only DOCX, ODT and PDF CVs are supported")
    if len(content) > MAX_CV_BYTES:
        raise ValueError("CV file is larger than 10 MB")
    _check_cv(ext, content)
    cv = data_dir / "cvs" / f"{Path(name).stem}.docx"
    cv.parent.mkdir(parents=True, exist_ok=True)
    if ext == ".docx":
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
        row.cv_approved = ext != ".pdf"
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
