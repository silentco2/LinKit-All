# ruff: noqa: F811
"""Action Center batch tools: retry by park code, grouped questions, one answer for many items."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_api import SAME_ORIGIN, client, mem_keyring  # noqa: F401  (fixtures)

from linkit_all.core.models import (
    ActionItem,
    ActionKind,
    ActionStatus,
    AnswerEntry,
    Job,
    JobState,
    Profile,
)
from linkit_all.core.state import transition


def q(label: str, required: bool = True, **kw: Any) -> dict[str, Any]:
    return {"label": label, "kind": "text", "options": [], "required": required,
            "reason": "unknown", "sensitive": False, **kw}  # fmt: skip


def park(
    client: TestClient,
    kind: ActionKind = ActionKind.unknown_question,
    questions: list[dict[str, Any]] | None = None,
    code: str | None = None,
) -> tuple[int, int]:
    db = client.app.state.db  # type: ignore[attr-defined]
    with db.begin() as s:
        n = s.query(Job).count()
        job = Job(source="lever", url=f"https://x/{n}", title="Dev", company=f"Co{n}",
                  dedupe_hash=f"h{n}", state=JobState.applying)  # fmt: skip
        s.add(job)
        s.flush()
        transition(s, job, JobState.needs_user)
        item = ActionItem(job_id=job.id, kind=kind, questions=questions or [], code=code)
        s.add(item)
        s.flush()
        return job.id, item.id


def state(client: TestClient, job_id: int) -> JobState:
    with client.app.state.db() as s:  # type: ignore[attr-defined]
        return s.get_one(Job, job_id).state


def item_row(client: TestClient, item_id: int) -> ActionItem:
    with client.app.state.db() as s:  # type: ignore[attr-defined]
        item = s.get_one(ActionItem, item_id)
        s.expunge(item)
        return item


def bank(client: TestClient) -> list[AnswerEntry]:
    with client.app.state.db() as s:  # type: ignore[attr-defined]
        return list(s.query(AnswerEntry))


def post(client: TestClient, url: str, body: dict[str, Any]) -> Any:
    return client.post(url, json=body, headers=SAME_ORIGIN)


def save_profile(client: TestClient) -> None:
    client.put("/api/profile", json={"full_name": "Jane", "email": "j@x.io"}, headers=SAME_ORIGIN)
    with client.app.state.db.begin() as s:  # type: ignore[attr-defined]
        assert s.get(Profile, 1) is not None


def test_retry_code_requeues_only_open_items_with_that_code(client: TestClient) -> None:
    j1, i1 = park(client, ActionKind.login_issue, code="needs_email")
    j2, i2 = park(client, ActionKind.login_issue, code="email_not_connected")  # the old code
    j3, i3 = park(client, ActionKind.login_issue, code="needs_vault")
    j4, i4 = park(client, ActionKind.login_issue, code="needs_email")
    assert post(client, f"/api/actions/{i4}", {"decision": "skip"}).status_code == 200

    r = post(client, "/api/actions/retry-code", {"code": "needs_email"})
    assert r.status_code == 200 and r.json() == {"count": 2}
    assert (state(client, j1), state(client, j2)) == (JobState.queued_apply, JobState.queued_apply)
    assert state(client, j3) == JobState.needs_user  # another code: untouched
    assert state(client, j4) == JobState.skipped  # closed item: untouched
    assert item_row(client, i1).status == item_row(client, i2).status == ActionStatus.resolved
    assert item_row(client, i3).status == ActionStatus.open
    assert post(client, "/api/actions/retry-code", {"code": "needs_email"}).json() == {"count": 0}
    assert post(client, "/api/actions/retry-code", {"code": ""}).status_code == 422


def test_groups_merge_same_wording_and_keep_different_questions_apart(client: TestClient) -> None:
    _, a = park(client, questions=[q("Notice period*"), q("Salary expectation", sensitive=True)])
    _, b = park(client, questions=[q("notice   period?")])
    _, c = park(client, questions=[q("Notice period :"), q("Salary expectation")])
    _, d = park(client, questions=[q("Notice period", kind="select", options=["1 month", "2"])])
    park(client, ActionKind.captcha, [q("Notice period")])  # not an unknown_question item
    groups = client.get("/api/actions/groups").json()
    by = {g["label"]: g for g in groups}
    assert [g["count"] for g in groups] == [3, 2, 1]  # sorted by count, desc
    notice = by["Notice period*"]
    assert notice["item_ids"] == [a, b, c] and notice["kind"] == "text"
    salary = by["Salary expectation"]
    assert salary["item_ids"] == [a, c] and salary["sensitive"] is True
    select = next(g for g in groups if g["kind"] == "select")  # other kind/options: its own group
    assert select["item_ids"] == [d] and select["options"] == ["1 month", "2"]


def test_groups_skip_questions_already_answered_in_that_item(client: TestClient) -> None:
    _, a = park(client, questions=[q("Notice period"), q("Why us?")])
    _, b = park(client, questions=[q("Notice period")])
    post(
        client,
        "/api/actions/answer-group",
        {"item_ids": [a], "label": "Notice period", "value": "1 month"},
    )
    groups = client.get("/api/actions/groups").json()
    notice = next(g for g in groups if g["label"] == "Notice period")
    assert notice["item_ids"] == [b]
    assert any(g["label"] == "Why us?" and g["item_ids"] == [a] for g in groups)


def test_answer_group_resolves_finished_items_and_keeps_others_open(client: TestClient) -> None:
    j1, a = park(client, questions=[q("Notice period*")])  # only this was missing
    j2, b = park(client, questions=[q("notice period?"), q("Why us?")])  # one more required
    j3, c = park(client, questions=[q("Notice period"), q("Cover note", required=False)])
    j4, other = park(client, questions=[q("Salary expectation")])  # does not ask it
    r = post(client, "/api/actions/answer-group",
             {"item_ids": [a, b, c, other, 999, a], "label": "Notice period", "value": " 1 month "})  # fmt: skip
    assert r.status_code == 200
    assert r.json() == {"resolved": 2, "still_open": 1, "skipped": 2}
    assert (state(client, j1), state(client, j3)) == (JobState.queued_apply, JobState.queued_apply)
    assert state(client, j2) == JobState.needs_user and state(client, j4) == JobState.needs_user
    kept = item_row(client, b)
    assert kept.status == ActionStatus.open and kept.answers == {"notice period?": "1 month"}
    assert item_row(client, a).status == ActionStatus.resolved
    entries = bank(client)
    assert [(e.question, e.answer, e.source, e.sensitive) for e in entries] == [
        ("Notice period", "1 month", "user", False)
    ]  # saved once, not per item

    # the single-answer card for the partly answered item only needs what is still missing
    r = post(client, f"/api/actions/{b}", {"decision": "answer", "answers": {"Why us?": "Growth"}})
    assert r.json() == {"job_state": "queued_apply"}


def test_answer_group_allows_sensitive_and_validates(client: TestClient) -> None:
    _, a = park(
        client, questions=[q("Do you need visa sponsorship?", kind="yesno", sensitive=True)]
    )
    _, b = park(client, questions=[q("do you need visa sponsorship", kind="yesno", sensitive=True)])
    url = "/api/actions/answer-group"
    body = {"item_ids": [a, b], "label": "Do you need visa sponsorship?"}
    assert post(client, url, {**body, "value": "  "}).status_code == 422
    assert post(client, url, {**body, "item_ids": []}).status_code == 422
    assert post(client, url, {**body, "value": False}).json()["resolved"] == 2
    (entry,) = bank(client)
    assert (entry.answer, entry.sensitive) == (False, True)


def test_remember_writes_only_allowed_keys(client: TestClient) -> None:
    save_profile(client)
    _, a = park(client, questions=[q("Do you accept the privacy notice?")])
    label = "Do you accept the privacy notice?"

    for bad in ({"needs_sponsorship": True}, {"salary_expectation": "9"}, {"full_name": "x"}):
        r = post(
            client,
            f"/api/actions/{a}",
            {"decision": "answer", "answers": {label: "Yes"}, "remember": bad},
        )
        assert r.status_code == 422, bad
    assert post(client, f"/api/actions/{a}", {"decision": "answer", "answers": {label: "Yes"},
                                              "remember": {"willing_to_relocate": "maybe"}}).status_code == 422  # fmt: skip
    assert item_row(client, a).status == ActionStatus.open and bank(client) == []  # nothing written

    r = post(client, f"/api/actions/{a}", {"decision": "answer", "answers": {label: "Yes"},
                                           "remember": {"acknowledge_privacy": True, "notice_period": "1 month"}})  # fmt: skip
    assert r.status_code == 200
    got = client.get("/api/profile/answers").json()
    assert got["acknowledge_privacy"] is True and got["notice_period"] == "1 month"
    assert got["needs_sponsorship"] is None and got["acknowledge_legal"] is None

    _, b = park(client, questions=[q("Notice period")])
    body = {"item_ids": [b], "label": "Notice period", "value": "2 months"}
    assert (
        post(
            client, "/api/actions/answer-group", {**body, "remember": {"salary_currency": "USD"}}
        ).status_code
        == 422
    )
    assert (
        post(
            client, "/api/actions/answer-group", {**body, "remember": {"eeo_gender": "decline"}}
        ).status_code
        == 200
    )
    assert client.get("/api/profile/answers").json()["eeo_gender"] == "decline"


@pytest.mark.parametrize("decision", ["answer", "retry"])
def test_resolve_on_a_closed_item_writes_nothing(client: TestClient, decision: str) -> None:
    save_profile(client)
    _, a = park(client, questions=[q("Notice period")])
    assert post(client, f"/api/actions/{a}", {"decision": "skip"}).status_code == 200
    r = post(client, f"/api/actions/{a}",
             {"decision": decision, "answers": {"Notice period": "1 month"},
              "remember": {"notice_period": "1 month"}})  # fmt: skip
    assert r.status_code == 404
    assert bank(client) == []
    assert client.get("/api/profile/answers").json()["notice_period"] == ""


def test_sensitive_questions_group_and_match_on_exact_label_only(client: TestClient) -> None:
    us, uk = (
        "Are you legally authorized to work in the US?",
        "Are you legally authorized to work in the UK?",
    )
    _, a = park(client, questions=[q(us, kind="yesno", sensitive=True)])
    _, b = park(
        client, questions=[q(uk, kind="yesno")]
    )  # not flagged: the sensitive-category rule still catches it
    _, c = park(
        client, questions=[q("are you legally authorized to work in the us", kind="yesno")]
    )  # same label
    soft_us, soft_uk = (
        "Describe your experience working in the US",
        "Describe your experience working in the UK",
    )
    _, d = park(client, questions=[q(soft_us)])
    _, e = park(client, questions=[q(soft_uk)])

    by = {g["label"]: g["item_ids"] for g in client.get("/api/actions/groups").json()}
    assert by[us] == [a, c] and by[uk] == [b]  # US and UK never merge
    assert by[soft_us] == [d, e]  # non-sensitive: still fuzzy

    r = post(
        client, "/api/actions/answer-group", {"item_ids": [a, b, c], "label": us, "value": True}
    )
    assert r.json() == {"resolved": 2, "still_open": 0, "skipped": 1}
    assert item_row(client, b).status == ActionStatus.open  # the UK item was not touched
    r = post(
        client,
        "/api/actions/answer-group",
        {"item_ids": [d, e], "label": soft_us, "value": "5 years"},
    )
    assert r.json()["resolved"] == 2
