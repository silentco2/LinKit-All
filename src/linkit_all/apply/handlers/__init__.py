from linkit_all.apply.handlers.ashby import Ashby
from linkit_all.apply.handlers.base import Handler, JobInfo
from linkit_all.apply.handlers.greenhouse import Greenhouse
from linkit_all.apply.handlers.lever import Lever

HANDLERS: dict[str, Handler] = {h.ats: h for h in (Greenhouse(), Lever(), Ashby())}

__all__ = ["HANDLERS", "Handler", "JobInfo"]
