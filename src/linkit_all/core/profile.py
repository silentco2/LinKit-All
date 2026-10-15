"""Profile import (JSON) until the setup wizard exists."""

import shutil
from pathlib import Path

from pydantic import BaseModel, field_validator
from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.core.models import LockedFact, Profile


class ProfileIn(BaseModel):
    full_name: str
    email: str
    phone: str = ""
    location: str = ""
    skills: list[str] = []
    cv_path: Path
    locked_facts: list[str] = []

    @field_validator("cv_path")
    @classmethod
    def _docx(cls, v: Path) -> Path:
        if v.suffix.lower() != ".docx":
            raise ValueError("only DOCX CVs are supported for now")
        if not v.is_file():
            raise ValueError(f"file not found: {v}")
        return v


def import_profile(db: sessionmaker[Session], data: ProfileIn, data_dir: Path) -> Path:
    """Save the profile and copy the CV into the data dir. Returns the stored CV path."""
    cv = data_dir / "cvs" / data.cv_path.name
    cv.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(data.cv_path, cv)  # fresh mtime, so the base PDF gets re-rendered
    cv.with_suffix(".pdf").unlink(missing_ok=True)
    fields = data.model_dump(exclude={"cv_path", "locked_facts"})
    with db.begin() as s:
        s.merge(Profile(id=1, cv_path=str(cv), **fields))
        s.execute(delete(LockedFact))
        facts = dict.fromkeys(t for f in data.locked_facts if (t := f.strip()))
        s.add_all(LockedFact(text=t) for t in facts)
    return cv
