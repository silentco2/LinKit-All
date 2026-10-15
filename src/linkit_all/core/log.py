"""loguru setup with secret redaction (CLAUDE.md §2: never log passwords or tokens)."""

import re
import sys
from typing import TYPE_CHECKING

from loguru import logger

from linkit_all.core.config import Settings

if TYPE_CHECKING:
    from loguru import Record

# ponytail: pattern-based, catches key=value / Bearer / sk- style secrets; CV text must
# simply never be passed to the logger (log ids and lengths instead).
_SECRET = re.compile(
    r"(?i)((?:api[_-]?key|token|secret|password|passwd|authorization)[\"']?\s*[:=]\s*[\"']?(?:bearer\s+)?)[^\s\"',}]+"
    r"|(bearer\s+)\S+"
    r"|\b(sk-|ghp_|xox[bp]-)[A-Za-z0-9_\-]{8,}"
)


def redact(text: str) -> str:
    return _SECRET.sub(lambda m: (m.group(1) or m.group(2) or m.group(3)) + "***", text)


def _patch(record: "Record") -> None:
    record["message"] = redact(record["message"])


def setup_logging(settings: Settings) -> None:
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.configure(patcher=_patch)
    logger.add(sys.stderr, level=settings.log_level)
    logger.add(settings.log_dir / "linkit.log", level="DEBUG", rotation="10 MB", retention=5)
