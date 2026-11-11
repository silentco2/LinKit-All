"""A scripted stand-in for the model, so the benchmark costs nothing and repeats exactly.

It does what a careful model would on the fake forms: maps every control it is shown, answers
every question it is asked. So it measures the code around the model (reading the page, filling,
paging, routing sensitive questions away from the AI), not a model's judgement. Everything it is
asked is kept in `asked`: a sensitive question showing up there is a leak.
"""

import json
import re
from typing import Any

from linkit_all.providers.base import LLMProvider

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
