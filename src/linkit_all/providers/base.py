"""LLM provider interface. The model only decides; our code validates and executes."""

import asyncio
import hashlib
import json
import re
import shutil
from abc import ABC, abstractmethod
from typing import TypeVar

from jinja2 import Environment, PackageLoader, StrictUndefined
from loguru import logger
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.core.models import LLMCache

T = TypeVar("T", bound=BaseModel)
MAX_RETRIES = 2  # re-asks after invalid output (CLAUDE.md §5.1)

# Prompts are plain text, not HTML.
_env = Environment(  # noqa: S701
    loader=PackageLoader("linkit_all.providers", "prompts"),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
)


def render(template: str, **ctx: object) -> str:
    return _env.get_template(template).render(**ctx)


class ProviderError(RuntimeError):
    pass


class UsageLimitError(ProviderError):
    """Plan or quota limit hit: pause the run cleanly instead of failing jobs."""


_LIMIT = re.compile(r"(?i)usage.?limit|rate.?limit|quota|limit reached|too many requests|\b429\b")
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def classify(message: str) -> ProviderError:
    return (UsageLimitError if _LIMIT.search(message) else ProviderError)(message)


def extract_json(text: str) -> str:
    """Pull the JSON object out of an answer that may have fences or prose around it."""
    if m := _FENCE.search(text):
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else text.strip()


class Ping(BaseModel):
    ok: bool


class LLMProvider(ABC):
    name: str

    def __init__(
        self,
        model: str | None = None,
        *,
        concurrency: int = 1,
        timeout_s: float = 300,
        cache: sessionmaker[Session] | None = None,
    ) -> None:
        self.model = model
        self.timeout_s = timeout_s
        self._sem = asyncio.Semaphore(concurrency)
        self._cache = cache

    @abstractmethod
    async def _call(self, prompt: str) -> str:
        """Send one prompt and return the model's raw text answer."""

    async def complete(self, prompt: str, schema: type[T], *, use_cache: bool = True) -> T:
        full = render(
            "json_output.j2", prompt=prompt, schema=json.dumps(schema.model_json_schema())
        )
        key = hashlib.sha256(f"{self.name}\0{self.model}\0{full}".encode()).hexdigest()
        if use_cache and (hit := self._cache_get(key)) is not None:
            try:
                return schema.model_validate_json(hit)
            except ValidationError:
                pass  # schema changed since cached; ask again

        ask = full
        for attempt in range(1, MAX_RETRIES + 2):
            async with self._sem:
                raw = await self._call(ask)
            try:
                result = schema.model_validate_json(extract_json(raw))
            except ValidationError as e:
                # Never log `raw`: it may echo CV text.
                logger.warning("{}: invalid output, attempt {}", self.name, attempt)
                ask = render("json_retry.j2", prompt=full, error=str(e))
                continue
            if use_cache:
                self._cache_put(key, result.model_dump_json())
            return result
        raise ProviderError(f"{self.name}: invalid output after {MAX_RETRIES + 1} attempts")

    async def check(self) -> str:
        """Tiny round trip proving the provider is reachable and signed in."""
        if not (await self.complete(render("ping.j2"), Ping, use_cache=False)).ok:
            raise ProviderError(f"{self.name}: test prompt answered ok=false")
        return f"{self.name} ({self.model or 'default model'}) ok"

    def _cache_get(self, key: str) -> str | None:
        if self._cache is None:
            return None
        with self._cache() as s:
            row = s.get(LLMCache, key)
            return row.response if row else None

    def _cache_put(self, key: str, response: str) -> None:
        if self._cache is not None:
            with self._cache.begin() as s:
                s.merge(LLMCache(key=key, model=self.model or self.name, response=response))


async def run_cli(cmd: list[str], stdin: str, cwd: str, timeout_s: float) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(stdin.encode()), timeout_s)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise ProviderError(f"{cmd[0]} timed out after {timeout_s:.0f}s") from None
    return proc.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


class CLIProvider(LLMProvider):
    """Subscription CLI run in an empty temp dir with its own tools disabled."""

    binary: str

    def path(self) -> str:
        if found := shutil.which(self.binary):
            return found
        raise ProviderError(f"`{self.binary}` not found on PATH")

    async def check(self) -> str:
        _, out, err = await run_cli([self.path(), "--version"], "", ".", 30)
        return f"{await super().check()}, {(out or err).strip()}"
