"""Maintainer rule: job details stay in their original language; no prompt may ask to translate."""

import json
import re
from pathlib import Path
from typing import Any

import pytest

import linkit_all.providers as providers

PROMPTS = sorted((Path(providers.__file__).parent / "prompts").glob("*.j2"))
# "never translate", "do not translate", "don't translate", "without translating", "not translated"
_NEGATED = re.compile(r"\b(never|not|don't|dont|without|no)\b[^.]{0,40}\btranslat", re.I)
VERBATIM = re.compile(r"verbatim.{0,80}language of the (page|post)", re.I | re.S)
EXTRACTION = ["extract_job.j2", "extract_linkedin_post.j2", "extract_telegram.j2"]


def test_prompts_found() -> None:
    assert {p.name for p in PROMPTS} >= set(EXTRACTION)


@pytest.mark.parametrize("path", PROMPTS, ids=lambda p: p.name)
def test_translate_only_in_do_not_translate(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for m in re.finditer(r"translat", text, re.I):
        line_start = text.rfind(".", 0, m.start()) + 1  # the sentence up to the match
        assert _NEGATED.search(text[line_start : m.end() + 1]), (
            f"{path.name}: {text[line_start : m.end() + 20]!r}"
        )


@pytest.mark.parametrize("name", EXTRACTION)
def test_extraction_prompts_keep_original_language(name: str) -> None:
    text = (PROMPTS[0].parent / name).read_text(encoding="utf-8")
    assert VERBATIM.search(text), f"{name} must say: verbatim, in the language of the page/post"
    assert re.search(r"never\s+translate", text, re.I)


PROSE = ["cover_letter.j2", "application_email.j2", "answer.j2", "score.j2", "tailor.j2"]


@pytest.mark.parametrize("name", PROSE)
def test_prose_prompts_demand_english(name: str) -> None:
    text = (PROMPTS[0].parent / name).read_text(encoding="utf-8")
    assert re.search(r"Write in English, even when", text), f"{name} must say: Write in English"


def test_tailor_prompt_only_patches_english_segments() -> None:
    text = (PROMPTS[0].parent / "tailor.j2").read_text(encoding="utf-8")
    assert "Only patch segments written in English" in text


# --- code guards: the AI never writes Arabic ---------------------------------------------------

AR = "مطور برمجيات"  # "software developer"


def test_tailoring_rejects_arabic_new_text_and_arabic_segments() -> None:
    from linkit_all.tailor.patches import Patch, Rules, plan_patches

    segs = {0: "Built backend services", 1: f"{AR} في شركة"}
    rules = Rules(locked_facts=[], allowed_terms={"built", "backend", "services"}, max_growth=5)
    plan = plan_patches(
        segs,
        [
            Patch(segment_id=0, old_text="Built", new_text=AR),
            Patch(segment_id=1, old_text="في", new_text="at"),
            Patch(segment_id=0, old_text="Built", new_text="Created"),
        ],
        rules,
    )
    assert [p.new_text for p in plan.accepted] == ["Created"]
    assert "Arabic" in plan.rejected[0][1] and "Arabic" in plan.rejected[1][1]


def test_ai_draft_with_arabic_is_discarded() -> None:
    import asyncio
    import json

    from linkit_all.apply.answers import Question
    from linkit_all.apply.assist import ai_drafts
    from linkit_all.providers.base import LLMProvider

    class Fake(LLMProvider):
        name = "fake"

        def __init__(self) -> None:
            super().__init__("fake")

        async def _call(self, prompt: str) -> str:
            return json.dumps(
                {
                    "answers": [
                        {"key": "a", "known": True, "answer": f"أنا {AR}"},
                        {"key": "b", "known": True, "answer": "I build APIs."},
                    ]
                }
            )

    qs = [Question("a", "لماذا تريد هذه الوظيفة؟", "textarea", True),
          Question("b", "Why us?", "textarea", True)]  # fmt: skip
    assert asyncio.run(
        ai_drafts(Fake(), qs, "cv", "profile", {"title": "Dev", "company": "Acme"})
    ) == {"b": "I build APIs."}


def _letter_provider(arabic_calls: int) -> Any:
    from linkit_all.providers.base import LLMProvider

    class Fake(LLMProvider):
        name = "fake"

        def __init__(self) -> None:
            super().__init__("fake")
            self.calls = 0

        async def _call(self, prompt: str) -> str:
            self.calls += 1
            text = f"السلام عليكم {AR}" if self.calls <= arabic_calls else "Dear Hiring Team, hi."
            return json.dumps({"text": text})

    return Fake()


def _run_letter(tmp_path: Path, ai: Any, required: bool) -> Any:
    import asyncio

    from test_answers import ctx
    from test_matching import fake_embed

    from linkit_all.apply.answers import Question
    from linkit_all.apply.assist import AnswerBank, answer_questions
    from linkit_all.core.db import init_db

    q = Question("q11", "Cover Letter", "textarea", required, name="cover_letter_text")
    bank = AnswerBank(init_db(tmp_path / "t.db"), fake_embed)
    return asyncio.run(
        answer_questions([q], ctx(), bank, ai, "cv", "profile", {"title": "Dev", "company": "A"}, tmp_path)
    )  # fmt: skip


def test_arabic_cover_letter_is_retried_once_then_accepted(tmp_path: Path) -> None:
    ai = _letter_provider(arabic_calls=1)
    r = _run_letter(tmp_path, ai, required=True)
    assert ai.calls == 2 and r.answers["q11"].startswith("Dear Hiring Team") and not r.missing


@pytest.mark.parametrize("required", [False, True])
def test_arabic_cover_letter_twice_is_dropped(tmp_path: Path, required: bool) -> None:
    ai = _letter_provider(arabic_calls=9)
    r = _run_letter(tmp_path, ai, required=required)
    assert ai.calls == 2  # one retry, no answers-draft fallback that could write the letter
    assert "q11" not in r.answers  # nothing Arabic is ever filled
    if required:
        assert [m.reason for m in r.missing] == [
            "The AI wrote the cover letter in Arabic; write it yourself or retry"
        ]
    else:
        assert not r.missing
