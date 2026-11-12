"""Fail CI when `linkit bench` quality drops below the floors measured on 2026-11-12.

Usage: python scripts/bench_gate.py bench.json
Timing is not gated: CI machines vary too much.
"""

import json
import sys
from typing import Any

FLOORS = {  # (section, metric): lowest accepted value; 1,000 jobs, seed 1 gave all 1.0, scam 0.9
    ("dedupe", "precision"): 0.95,
    ("dedupe", "recall"): 0.95,
    ("scam", "precision"): 0.95,
    ("scam", "recall"): 0.85,
    ("ghost", "precision"): 0.9,
    ("ghost", "recall"): 0.9,
    ("rank", "precision_at_50"): 0.9,
}


def problems(result: dict[str, Any]) -> list[str]:
    q = result["quality"]
    out = [
        f"{sec} {name} {q[sec][name]:.2f} < {floor}"
        for (sec, name), floor in FLOORS.items()
        if q[sec][name] < floor
    ]
    if result["counts"]["errors"]:
        out.append(f"{result['counts']['errors']} errors while finding jobs")
    tailor = result["tailor"]
    if tailor["honest_refused"]:
        out.append(f"honest CV edits refused: {tailor['honest_refused']}")
    refused, total = map(int, tailor["invented_refused"].split("/"))
    if refused < total - 2:  # two known gaps today (bench.json lists them)
        out.append(f"invented CV edits refused only {refused}/{total}")
    if not tailor["layout"]["ok"]:
        out.append("tailoring changed the CV layout")
    sent = result.get("apply", {}).get("sensitive_sent_to_ai", [])
    if sent:
        out.append(f"sensitive questions sent to the AI: {sent}")
    return out


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as f:
        found = problems(json.load(f))
    print("\n".join(found) or "bench: all floors met")
    sys.exit(1 if found else 0)
