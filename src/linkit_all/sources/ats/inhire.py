"""InHire careers API (api.inhire.app), the ATS behind a number of Brazilian company career sites:
the tenant goes in the X-Tenant header; the list has no description, so each post's body comes
from its own call. Logic adapted from freehire (MIT)."""

import re
import unicodedata
from collections.abc import AsyncIterator

from linkit_all.sources.ats._f13 import mode, name_from_slug
from linkit_all.sources.base import JobStub, Source, Task, from_iso
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

LIST = "https://api.inhire.app/job-posts/public/pages"
DETAIL = "https://api.inhire.app/job-posts/public/pages/{id}"
# The SPA routes /vagas/<id>/<slug> and renders blank without the slug, which is cosmetic.
VACANCY = "https://{board}.inhire.app/vagas/{id}/{slug}"
_URL = re.compile(r"//([\w-]+)\.inhire\.app/vagas/([\w-]+)", re.I)


def slugify(title: str) -> str:
    """ "Engenheiro Sênior" -> "engenheiro-senior"; "vaga" when nothing is left."""
    ascii_ = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-") or "vaga"


class Inhire(Source):
    """The board is the tenant slug: `contaazul` for contaazul.inhire.app."""

    name = "inhire"
    kind = "ats"
    url_patterns = (re.compile(r"(?<![\w.-])(?!api\.)([\w-]+)\.inhire\.app", re.I),)
    parallel = 2  # public JSON API; Http paces per host

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # the list is not paged
            return
        board = task.board
        data = await http.get_json(LIST, headers={"X-Tenant": board})
        stubs = []
        for p in data.get("jobsPage") or []:
            if not p.get("jobId"):
                continue
            title = (p.get("displayName") or "").strip()
            url = VACANCY.format(board=board, id=p["jobId"], slug=slugify(title))
            stubs.append(
                JobStub(
                    source=self.name,
                    url=url,
                    title=title,
                    company=name_from_slug(board),
                    location=p.get("location") or "",
                    ats=self.name,
                    apply_url=url,
                    remote=mode(p.get("workplaceType")),
                    extra={"board": board, "id": p["jobId"]},
                )
            )
        yield stubs

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _URL.search(stub.url)
        if not m or stub.description:
            return stub
        d = await http.get_json(DETAIL.format(id=m[2]), headers={"X-Tenant": m[1]})
        return stub.model_copy(
            update={
                "description": html_to_text(d.get("description") or "", escaped=True),
                "posted_at": from_iso(d.get("publishedAt") or d.get("createdAt")),
            }
        )
