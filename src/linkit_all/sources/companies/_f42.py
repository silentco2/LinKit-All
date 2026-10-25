"""Helper private to the F4.2 company plugins (the underscore keeps it out of the registry)."""

from linkit_all.sources.base import Remote, remote_from_text

_RU_REMOTE = ("удалён", "удален", "дистанц")  # remote in Russian: удалённо, удалённая, дистанционно


def remote_ru(*texts: str | None) -> Remote | None:
    """Remote mode from English or Russian words (a city line like "Удалённо")."""
    joined = " ".join(t for t in texts if t).lower()
    return "remote" if any(w in joined for w in _RU_REMOTE) else remote_from_text(joined)
