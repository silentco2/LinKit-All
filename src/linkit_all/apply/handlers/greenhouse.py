"""Greenhouse: the embeddable application form works even when a company hides the hosted
board behind its own careers site. Dropdown options come from the public questions API."""

import re

import httpx
from playwright.async_api import Page

from linkit_all.apply.answers import Question
from linkit_all.apply.handlers.base import Handler, JobInfo

QUESTIONS_API = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{id}?questions=true"


class Greenhouse(Handler):
    ats = "greenhouse"
    container = ".field-wrapper, .phone-input__country, .phone-input__phone"
    label = ".upload-label, label, legend"
    description = ".question-description"
    ignore = "[class*=requiredInput], .iti__search-input"
    submit_button = "button[type=submit]"
    confirmation = re.compile(
        r"thank you for (applying|your application)|application (has been )?(submitted|received)|"
        r"we.ve received your application"
    )

    def form_url(self, job: JobInfo) -> str:
        return f"https://boards.greenhouse.io/embed/job_app?for={job.extra['board']}&token={job.extra['id']}"

    async def questions(self, page: Page, job: JobInfo) -> list[Question]:
        found = await super().questions(page, job)
        api = QUESTIONS_API.format(board=job.extra["board"], id=job.extra["id"])
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                data = (await client.get(api)).json()
        except (httpx.HTTPError, ValueError):
            return found
        schema = {
            f["name"]: (q["required"], [v["label"] for v in f.get("values", [])])
            for q in data.get("questions", [])
            + (data.get("demographic_questions") or {}).get("questions", [])
            for f in q.get("fields", [])
        }
        for q in found:
            required, options = schema.get(
                q.name.removesuffix("[]"), schema.get(q.name, (q.required, []))
            )
            q.required = q.required or required
            if q.kind == "combobox" and options:
                q.options = options
        return found
