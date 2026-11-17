"""A scripted stand-in for the model, so the benchmark costs nothing and repeats exactly.

It does what a careful model would on the fake forms: maps every control it is shown, answers
every question it is asked. So it measures the code around the model (reading the page, filling,
paging, routing sensitive questions away from the AI), not a model's judgement. Everything it is
asked is kept in `asked`: a sensitive question showing up there is a leak.
"""

import hashlib
import json
import re
import warnings
from pathlib import Path
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.matching.score import CV_CHARS, JD_CHARS, ScoreBatch, tier_for
from linkit_all.providers.base import LLMProvider, render

_CONTROL = re.compile(r'^- id: (\w+) \| (\w+)((?: \| [^|\n]+)*)\n  name: (".*")$', re.M)
_QUESTION = re.compile(r"^- key: (\w+) \| (\w+).*\n  question: (.*)$", re.M)
_JOB = re.compile(r"=== job_id (\d+) ===")
_ITEM = re.compile(r"^\[(\d+)\]$", re.M)
_ITEM = re.compile(r"^\[(\d+)\]$", re.M)


class ScriptedAI(LLMProvider):
    name = "scripted"

    def __init__(self) -> None:
        super().__init__("scripted")
        self.calls = 0
        self.asked: list[str] = []  # question labels that reached an answer prompt
        self.patches: list[dict[str, Any]] = []  # what it proposes when asked to tailor a CV
        # A real model for the one judgement a script cannot fake: does an edit say more
        # than the CV does? None = the scripted answer, "no", so only the rules decide.
        self.checker: LLMProvider | None = None

    async def _call(self, prompt: str) -> str:
        self.calls += 1
        if ids := _JOB.findall(prompt):  # score stage: everything it is shown is a strong match
            results = [{"job_id": int(i), "score": 9, "reasons": ["scripted"]} for i in ids]
            return json.dumps({"results": results})
        if prompt.startswith("You check edits to a CV"):
            if self.checker is not None:
                return await self.checker._call(prompt)
            verdicts = [{"index": int(i), "adds": False} for i in _ITEM.findall(prompt)]
            return json.dumps({"verdicts": verdicts})
        if prompt.startswith("You check edits to a CV"):
            if self.checker is not None:
                return await self.checker._call(prompt)
            verdicts = [{"index": int(i), "adds": False} for i in _ITEM.findall(prompt)]
            return json.dumps({"verdicts": verdicts})
        if prompt.startswith("You tailor a CV"):
            return json.dumps({"patches": self.patches})
        if "You help fill in a job application form" in prompt:
            return json.dumps(self._map(prompt))
        if "Write a short cover letter" in prompt:
            return json.dumps({"text": "Dear Hiring Team,\nI build backend services.\nJane Doe"})
        out = []
        for key, kind, label in _QUESTION.findall(prompt):
            self.asked.append(label)
            opts = re.search(rf"- key: {key} .*\n  question: .*\n  options: (.*)", prompt)
            answer: Any = "I build and run backend services in Python."
            if opts and "long list" not in opts.group(1):
                first = opts.group(1).split(" || ")[0]
                answer = [first] if kind == "multi" else first
            elif kind == "checkbox":
                answer = True
            out.append({"key": key, "known": True, "answer": answer})
        return json.dumps({"answers": out})

    @staticmethod
    def _map(prompt: str) -> dict[str, Any]:
        fields, nxt, sub, apply = [], None, None, None
        for cid, kind, extra, quoted in _CONTROL.findall(prompt):
            name = json.loads(quoted)
            if kind == "link" or (kind == "button" and re.match(r"apply\b", name, re.I)):
                apply = apply or cid
            elif kind == "button":
                if re.search(r"next|continue", name, re.I):
                    nxt = cid
                elif re.search(r"submit|send", name, re.I):
                    sub = cid
            else:
                fields.append(
                    {"id": cid, "question": name, "kind": kind, "required": "required" in extra}
                )
        if apply and not fields and not sub:  # a job ad: only an Apply link
            return {"page_kind": "listing", "apply_button": apply, "dismiss_button": None}
        return {"page_kind": "form", "fields": fields, "next_button": nxt, "submit_button": sub}


# --- golden score set: 20 made-up job + CV pairs with the tier a person expects (plan D4) ------
# The model's answers are recorded once, so the set runs offline and free in CI. After a change
# to the score prompt, record again with a real model and look at what moved:
#   uv run python -m linkit_all.bench.ai tests/fixtures/golden
GoldenSet = dict[str, Any]  # cases.json: {"cvs": {key: {cv, prefs}}, "cases": [...]}


def golden_prompts(golden: GoldenSet) -> dict[int, str]:
    """The score prompt each case is asked with: one job per prompt, as the score stage builds
    it (`matching/score.py`)."""
    out = {}
    for c in golden["cases"]:
        person = golden["cvs"][c["cv"]]
        job = {k: c.get(k) for k in ("id", "title", "company", "location", "remote")}
        job["description"] = c["description"][:JD_CHARS]
        out[c["id"]] = render(
            "score.j2", cv=person["cv"][:CV_CHARS], prefs=person["prefs"], jobs=[job]
        )
    return out


def prompt_sha(golden: GoldenSet) -> str:
    return hashlib.sha256("\0".join(golden_prompts(golden).values()).encode()).hexdigest()


class RecordedAI(LLMProvider):
    """Replays one recorded answer per golden case, found by the job_id in the prompt."""

    name = "recorded"

    def __init__(self, answers: dict[str, str]) -> None:
        super().__init__("recorded")
        self.answers = answers

    async def _call(self, prompt: str) -> str:
        ids = _JOB.findall(prompt)
        return self.answers.get(ids[0], '{"results": []}') if ids else '{"results": []}'


async def golden_tiers(
    golden: GoldenSet, provider: LLMProvider, cfg: SearchConfig | None = None
) -> dict[int, str]:
    """Each case's tier as the score stage would set it; "none" when the model skipped it."""
    cfg = cfg or SearchConfig()
    tiers = {}
    for cid, prompt in golden_prompts(golden).items():
        batch = await provider.complete(prompt, ScoreBatch, use_cache=False)
        score = next((r.score for r in batch.results if r.job_id == cid), None)
        tiers[cid] = "none" if score is None else str(tier_for(score, cfg))
    return tiers


def moved(golden: GoldenSet, tiers: dict[int, str]) -> list[str]:
    """The cases whose tier is not the one expected, as "id title: expected -> got"."""
    return [
        f"{c['id']} {c['title']}: {c['expected']} -> {tiers.get(c['id'], 'none')}"
        for c in golden["cases"]
        if tiers.get(c["id"]) != c["expected"]
    ]


def load_golden(folder: Path) -> tuple[GoldenSet, RecordedAI]:
    golden = json.loads((folder / "cases.json").read_text("utf-8"))
    recorded = json.loads((folder / "recorded.json").read_text("utf-8"))
    if recorded.get("prompt_sha") != prompt_sha(golden):
        warnings.warn(
            "the golden answers were recorded with another score prompt: record them again "
            "(python -m linkit_all.bench.ai tests/fixtures/golden)",
            stacklevel=2,
        )
    return golden, RecordedAI(recorded["answers"])


async def record_golden(folder: Path, provider: LLMProvider) -> list[str]:
    """Ask a real model every golden case, save its answers and return the cases that moved."""
    golden = json.loads((folder / "cases.json").read_text("utf-8"))
    answers = {}
    for cid, prompt in golden_prompts(golden).items():
        batch = await provider.complete(prompt, ScoreBatch, use_cache=False)
        answers[str(cid)] = batch.model_dump_json(
            include={"results": {"__all__": {"job_id", "score", "reasons", "missing_skills"}}}
        )
    (folder / "recorded.json").write_text(
        json.dumps({"prompt_sha": prompt_sha(golden), "answers": answers}, indent=1) + "\n",
        "utf-8",
    )
    return moved(golden, await golden_tiers(golden, RecordedAI(answers)))


if __name__ == "__main__":
    import asyncio
    import sys

    from linkit_all.core.config import Settings
    from linkit_all.providers import get_provider

    for line in asyncio.run(record_golden(Path(sys.argv[1]), get_provider(Settings()))):
        print("moved:", line)
