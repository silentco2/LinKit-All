"""The fake-board benchmark: also the CI smoke run of discover -> enrich -> rank end to end."""

import asyncio
import re
import zlib
from pathlib import Path
from typing import Any

import numpy as np

from linkit_all.bench.data import generate
from linkit_all.bench.run import run_bench


def embed(texts: list[str]) -> np.ndarray[Any, np.dtype[np.float64]]:
    """Bag of words; crc32 because the built-in hash() changes between processes."""
    rows = []
    for t in texts:
        v = np.zeros(256)
        for w in re.findall(r"\w+", t.lower()):
            v[zlib.crc32(w.encode()) % 256] += 1
        rows.append(v / (np.linalg.norm(v) or 1))
    return np.array(rows)


def test_generate_is_seeded_and_mixed() -> None:
    jobs = generate(1000, seed=7)
    assert jobs == generate(1000, seed=7) != generate(1000, seed=8)
    assert len(jobs) == 1000 and len({j.uid for j in jobs}) == 1000
    assert sum(j.duplicate_of is not None for j in jobs) == 80
    # the same title at one company in two cities is two jobs, never the same city twice
    keys = [(j.company, j.title, j.location) for j in jobs if j.duplicate_of is None]
    assert len(keys) == len(set(keys)) == 920
    assert {"scam", "ghost", "decoy", "backend", "backend_plain"} <= {j.family for j in jobs}
    seen: set[int] = set()
    for j in jobs:  # a repost always comes after the posting it repeats
        assert j.duplicate_of is None or j.duplicate_of in seen
        seen.add(j.uid)


def test_bench_runs_the_real_stages(tmp_path: Path) -> None:
    result = asyncio.run(run_bench(1000, 1, embed, tmp_path))
    c, q = result["counts"], result["quality"]
    assert c["errors"] == 0 and c["new"] + c["duplicates"] == 1000
    assert c["enriched"] == c["new"]  # half the descriptions came from the job pages
    # Regression floors, a little under today's scores. Known and left on purpose:
    # - scam: a screening fee paid by the candidate is flagged but not filtered on its own
    #   (schools and hospitals really do charge for background checks)
    # - rank: other jobs that name the CV's tools (recruiter, instructor) still outrank matches
    #   that name none; the AI score stage is where those are told apart
    assert q["dedupe"]["precision"] == 1.0 and q["dedupe"]["recall"] >= 0.95
    assert q["scam"]["precision"] == 1.0 and q["scam"]["recall"] >= 0.85
    assert q["ghost"]["precision"] == 1.0 and q["ghost"]["recall"] >= 0.95
    assert q["rank"]["bad_ranked"] == 0
    assert q["rank"]["precision_at_10"] >= 0.8
    assert q["rank"]["precision_at_r"] > 1.5 * q["rank"]["relevant_share"]


def test_tailoring_guard_on_honest_and_invented_patches(tmp_path: Path) -> None:
    from linkit_all.bench.tailor import run_tailor
    from linkit_all.core.config import Settings

    t = asyncio.run(run_tailor(tmp_path, Settings(data_dir=tmp_path / "data")))
    assert t["honest_accepted"] == "6/6" and t["honest_refused"] == []
    assert t["layout"]["ok"] and t["structure_kept"]
    # Known gaps the benchmark found; nothing else may get through. When one is closed, take
    # it off this list.
    known = {"unlisted tool the lexicon does not know", "bigger role in other words"}
    assert {line.split(":")[0] for line in t["invented_accepted"]} <= known
    assert "changes locked fact 'Acme'" in t["refusals"].values()
