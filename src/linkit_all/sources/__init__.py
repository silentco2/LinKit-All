"""Job source plugins and the registry that finds them.

Adding a source = adding one module; no shared file is edited. Put it in one of
`linkit_all.sources.ats` (company job-board vendors), `.aggregators` (APIs that list many
employers), `.boards` (job sites), `.companies` (one employer); the flat modules in this
package are the older plugins. `registry()` imports every module there, so a module that
fails to import is logged and skipped; it never breaks the others.

A plugin module defines a `Source` subclass (see `base.py`) with:

- `name`: unique key, also the `Job.source` value and the name used in `sources.enabled`.
- `kind`: "ats", "aggregator", "board", "company" (or "jobspy", "regional", "careers",
  "telegram" for the older special cases). Always set it.
- `parallel`, `priority`: as documented on `Source`.
- ATS only: `url_patterns`, regexes whose groups form the board slug. `ats_detector` builds its
  table from them, and "name:slug" shorthand works for every ATS automatically.
- `search()` (and `fetch_details()` when the list has no description). Aggregators, boards and
  company plugins also implement `tasks(cfg)`; they are only asked when the user lists their
  `name` in `sources.enabled` (or `default_on = True`). ATS plugins run from the company list.

The constructor may take `provider`, `data_dir` and/or `keys`; they are filled in by name. `keys`
is `keys(provider_name) -> {field: value} | None`, the API keys saved in the vault (see
`core/api_keys.py`); it is looked up when asked, so a vault unlocked later still works. A
module that needs several instances (one per jobspy site) defines
`def sources(**ctx) -> list[Source]` instead, and the classes in it are not scanned.
"""

import importlib
import inspect
import pkgutil
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

from loguru import logger

from linkit_all.providers.base import LLMProvider
from linkit_all.sources.base import Source

PACKAGES = (
    "linkit_all.sources",
    "linkit_all.sources.ats",
    "linkit_all.sources.aggregators",
    "linkit_all.sources.boards",
    "linkit_all.sources.companies",
)


def _modules(packages: Iterable[str]) -> Iterator[ModuleType]:
    for package in packages:
        try:
            path = importlib.import_module(package).__path__
        except Exception as e:  # a broken package must not stop the others
            logger.warning("source package {} skipped: {}", package, e)
            continue
        for info in sorted(pkgutil.iter_modules(path), key=lambda i: i.name):
            if info.ispkg or info.name.startswith("_"):
                continue
            name = f"{package}.{info.name}"
            try:
                yield importlib.import_module(name)
            except Exception as e:
                logger.warning("source module {} skipped: {}", name, e)


def _declares_kind(cls: type[Source]) -> bool:
    return any("kind" in vars(c) for c in cls.__mro__ if c is not Source and issubclass(c, Source))


def _instances(mod: ModuleType, ctx: dict[str, Any]) -> list[Source]:
    hook = getattr(mod, "sources", None)
    if inspect.isfunction(hook) and hook.__module__ == mod.__name__:
        return list(hook(**ctx))
    out = []
    for _, cls in inspect.getmembers(mod, inspect.isclass):
        if (
            not issubclass(cls, Source)
            or cls.__module__ != mod.__name__
            or inspect.isabstract(cls)
            or not isinstance(getattr(cls, "name", None), str)
        ):
            continue
        if not _declares_kind(cls):
            logger.warning("source {} declares no `kind`; treating it as an ATS", cls.__name__)
        params = inspect.signature(cls).parameters
        out.append(cls(**{k: v for k, v in ctx.items() if k in params}))
    return out


KeyGetter = Callable[[str], dict[str, str] | None]


def no_keys(name: str) -> dict[str, str] | None:
    return None


def registry(
    provider: LLMProvider | None = None,
    data_dir: Path | None = None,
    keys: KeyGetter | None = None,
    *,
    extra_packages: Iterable[str] = (),
) -> dict[str, Source]:
    """Every source plugin by name. `extra_packages` adds more packages to scan (tests)."""
    ctx = {"provider": provider, "data_dir": data_dir, "keys": keys or no_keys}
    found: dict[str, Source] = {}
    for mod in _modules([*PACKAGES, *extra_packages]):
        try:
            sources = _instances(mod, ctx)
        except Exception as e:  # e.g. a constructor that needs other arguments
            logger.warning("source module {} skipped: {}", mod.__name__, e)
            continue
        for s in sources:
            if s.name in found:
                logger.warning("source {} in {} is a duplicate; skipped", s.name, mod.__name__)
            else:
                found[s.name] = s
    return found
