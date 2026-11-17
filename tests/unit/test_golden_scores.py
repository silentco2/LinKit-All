"""D4: 20 made-up job + CV pairs keep the tier a person expects (at most 2 may move).

The model's answers are recorded in tests/fixtures/golden/recorded.json; after a change to the
score prompt, record them again with a real model (see `linkit_all.bench.ai`)."""

import asyncio
import json
from pathlib import Path

import pytest

from linkit_all.bench.ai import RecordedAI, golden_tiers, load_golden, moved, prompt_sha
from linkit_all.core.search import SearchConfig

GOLDEN = Path(__file__).parents[1] / "fixtures" / "golden"
MAX_MOVED = 2


def test_golden_set_keeps_its_tiers() -> None:
    golden, ai = load_golden(GOLDEN)
    assert len(golden["cases"]) == 20
    assert {c["expected"] for c in golden["cases"]} == {"high", "mid", "low"}
    off = moved(golden, asyncio.run(golden_tiers(golden, ai)))
    assert len(off) <= MAX_MOVED, "more than 2 of 20 golden jobs changed tier:\n" + "\n".join(off)


def test_the_set_catches_a_change_that_moves_tiers() -> None:
    golden, ai = load_golden(GOLDEN)
    stricter = SearchConfig.model_validate({"matching": {"tier_high": 10, "tier_mid": 8}})
    assert len(moved(golden, asyncio.run(golden_tiers(golden, ai, stricter)))) > MAX_MOVED


def test_a_skipped_case_counts_as_moved() -> None:
    golden, ai = load_golden(GOLDEN)
    tiers = asyncio.run(golden_tiers(golden, RecordedAI({**ai.answers, "1": '{"results": []}'})))
    assert tiers[1] == "none" and any(m.startswith("1 ") for m in moved(golden, tiers))


def test_a_recording_from_another_prompt_warns(tmp_path: Path) -> None:
    for name in ("cases.json", "recorded.json"):
        (tmp_path / name).write_bytes((GOLDEN / name).read_bytes())
    recorded = json.loads((tmp_path / "recorded.json").read_text("utf-8"))
    golden = json.loads((tmp_path / "cases.json").read_text("utf-8"))
    assert recorded["prompt_sha"] == prompt_sha(golden)  # the fixture matches today's prompt
    (tmp_path / "recorded.json").write_text(json.dumps({**recorded, "prompt_sha": "old"}), "utf-8")
    with pytest.warns(UserWarning, match="record them again"):
        load_golden(tmp_path)
