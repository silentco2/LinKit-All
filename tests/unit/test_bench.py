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
    assert {"scam", "ghost", "backend"} <= {j.family for j in jobs}
    seen: set[int] = set()
    for j in jobs:  # a repost always comes after the posting it repeats
        assert j.duplicate_of is None or j.duplicate_of in seen
        seen.add(j.uid)


def test_bench_runs_the_real_stages(tmp_path: Path) -> None:
    result = asyncio.run(run_bench(1000, 1, embed, tmp_path))
    c, q = result["counts"], result["quality"]
    assert c["errors"] == 0 and c["new"] + c["duplicates"] == 1000
    assert c["enriched"] == c["new"]  # half the descriptions came from the job pages
    # Regression floors, set a little under what the pipeline scores today.
    assert q["dedupe"]["precision"] == 1.0 and q["dedupe"]["recall"] >= 0.7
    assert q["scam"]["precision"] == 1.0 and q["scam"]["recall"] >= 0.7
    assert q["ghost"]["wrong"] == 0
    assert q["rank"]["precision_at_10"] >= 0.8
    assert q["rank"]["precision_at_10"] > 2 * q["rank"]["relevant_share"]
