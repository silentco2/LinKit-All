from linkit_all.providers.base import LLMProvider
from linkit_all.sources.ashby import Ashby
from linkit_all.sources.base import Source
from linkit_all.sources.careers import Careers
from linkit_all.sources.greenhouse import Greenhouse
from linkit_all.sources.jobspy_sites import jobspy_sources
from linkit_all.sources.lever import Lever
from linkit_all.sources.recruitee import Recruitee
from linkit_all.sources.smartrecruiters import SmartRecruiters
from linkit_all.sources.workable import Workable
from linkit_all.sources.workday import Workday
from linkit_all.sources.wuzzuf import Wuzzuf


def registry(provider: LLMProvider | None = None) -> dict[str, Source]:
    sources: list[Source] = [
        Greenhouse(),
        Lever(),
        Ashby(),
        SmartRecruiters(),
        Recruitee(),
        Workable(),
        Workday(),
        *jobspy_sources(),
        Wuzzuf(),
        Careers(provider),  # the AI fallback for pages without JSON-LD
    ]
    return {s.name: s for s in sources}
