"""The user's profile: form fields, locked facts, and the base CV file."""

import io
import re
import zipfile
from pathlib import Path

from pydantic import BaseModel, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.core.models import LockedFact, Profile

MAX_CV_BYTES = 10 * 1024 * 1024


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
        if v.suffix.lower() != ".docx":
            raise ValueError("only DOCX CVs are supported for now")
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


def save_cv(db: sessionmaker[Session], data_dir: Path, filename: str, content: bytes) -> Path:
    """Store an uploaded DOCX as the base CV. Raises ValueError for anything else."""
    name = re.sub(r"[^\w.\- ]", "_", Path(filename).name)
    if not name.lower().endswith(".docx") or len(name) < 6:
        raise ValueError("only DOCX CVs are supported for now")
    if len(content) > MAX_CV_BYTES:
        raise ValueError("CV file is larger than 10 MB")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            if "word/document.xml" not in z.namelist():
                raise ValueError("this file is not a Word document")
    except zipfile.BadZipFile as e:
        raise ValueError("this file is not a Word document") from e
    cv = data_dir / "cvs" / name
    cv.parent.mkdir(parents=True, exist_ok=True)
    cv.write_bytes(content)  # fresh mtime, so the base PDF gets re-rendered
    cv.with_suffix(".pdf").unlink(missing_ok=True)
    with db.begin() as s:
        _row(s).cv_path = str(cv)
    return cv


def import_profile(db: sessionmaker[Session], data: ProfileIn, data_dir: Path) -> Path:
    cv = save_cv(db, data_dir, data.cv_path.name, data.cv_path.read_bytes())
    save_fields(db, data)
    return cv
