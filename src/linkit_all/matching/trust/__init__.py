"""Trust filter: offline, deterministic scoring of scam and ghost-job signals.

Pure functions only: no AI, no network, no database. Wiring into the rank stage lives elsewhere.
`Signal.code` is a stable key (UI translation key `trust.<code>`); `Verdict` is the result shape
shared by every trust scorer.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Signal:
    code: str  # stable, e.g. "upfront_fee"; used as i18n key trust.<code>
    weight: int  # signed points actually applied
    evidence: str  # short matched snippet (<= 80 chars), never full text


@dataclass(frozen=True)
class Verdict:
    score: int  # 0-100
    signals: tuple[Signal, ...]
    band: str  # "low" | "medium" | "high"
