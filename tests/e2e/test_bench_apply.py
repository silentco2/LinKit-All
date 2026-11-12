"""`linkit bench --apply`: the fake application forms, filled by the real form agent in a real
browser. Practice mode, a local fake board, a scripted AI: nothing leaves the machine and nothing
is submitted. Needs Chrome, Edge or Brave installed."""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "unit"))
from test_bench import embed

from linkit_all.bench.ai import ScriptedAI
from linkit_all.bench.board import FORMS, form_kind
from linkit_all.bench.run import run_bench
from linkit_all.core.tools import browser_path

pytestmark = pytest.mark.skipif(browser_path() is None, reason="no Chrome, Edge or Brave installed")


def test_every_form_kind_ends_as_it_should(tmp_path: Path) -> None:
    a = asyncio.run(run_bench(300, 1, embed, tmp_path, apply=6))["apply"]
    assert a["attempted"] == a["scored_high"] == a["right_outcome"] == 6
    assert set(a["by_form"]) == set(FORMS)  # the six best jobs cover all three forms
    assert a["outcomes"]["failed"] == a["outcomes"]["applied"] == 0  # practice mode
    # salary and gender are not in the profile: those forms wait for the user, unanswered
    assert a["by_form"]["sensitive"] == {"waits: unknown_question": 3}
    assert a["sensitive_sent_to_ai"] == []
    filled = a["outcomes"]["dry_run"]
    assert a["fields_right"] == f"{3 * filled}/{3 * filled}"
    assert a["cv_attached"] == "1/1" and a["traps_left_empty"] == "2/2"


def test_form_kinds_are_spread_by_job_number() -> None:
    assert [form_kind(u) for u in range(3)] == list(FORMS)


def test_scripted_ai_scores_and_maps() -> None:
    ai = ScriptedAI()
    scored = asyncio.run(ai._call("=== job_id 7 ===\nBackend Engineer at Acme"))
    assert '"job_id": 7' in scored and '"score": 9' in scored
    prompt = (
        "You help fill in a job application form.\n"
        '- id: a1 | text | required\n  name: "Full name"\n'
        '- id: a2 | button\n  name: "Submit application"\n'
    )
    mapped = asyncio.run(ai._call(prompt))
    assert '"submit_button": "a2"' in mapped and '"question": "Full name"' in mapped
    assert ai.calls == 2 and ai.asked == []
