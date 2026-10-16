"""Pure parts of the generic form agent: the model's field map is never trusted."""

from linkit_all.apply.agent import (
    Control,
    FieldMap,
    FieldSpec,
    clean_map,
    pick_button,
    to_questions,
)
from linkit_all.apply.answers import sensitive_category


def test_clean_map_drops_unknown_ids_and_never_both_buttons() -> None:
    controls = [
        Control("a0", "text", "Name"),
        Control("a1", "button", "Next", type="button"),
        Control("a2", "button", "Send", type="submit"),
    ]
    fmap = FieldMap(
        fields=[
            FieldSpec(id="a0", question="Name", kind="text"),
            FieldSpec(id="a0", question="Dup", kind="text"),
            FieldSpec(id="zz", question="Ghost", kind="text"),
            FieldSpec(id="a1", question="A button", kind="text"),
        ],
        next_button="a1",
        submit_button="a1",
    )
    out = clean_map(fmap, controls)
    assert [f.id for f in out.fields] == ["a0"]
    assert (out.next_button, out.submit_button) == (None, "a1")  # one button is never both
    assert (
        clean_map(FieldMap(next_button="nope", submit_button="a0"), controls).submit_button is None
    )


def test_to_questions_keeps_the_pages_own_text_for_sensitive_rules() -> None:
    controls = [
        Control(
            "a0", "radio", "Are you legally authorized to work in the US?", True, ["Yes", "No"]
        ),
        Control("a1", "text", "Nickname"),  # optional and not mapped: left alone
        Control("a2", "text", "Phone", True, html_name="phone"),
    ]
    fmap = FieldMap(
        fields=[
            FieldSpec(id="a0", question="Tell us more", kind="text"),
            FieldSpec(id="a2", question="Mobile", kind="tel"),
        ]
    )
    qs = to_questions(controls, fmap)
    assert [q.key for q in qs] == ["a0", "a2"]
    assert qs[0].kind == "radio"  # the page decides structure, not the model
    assert sensitive_category(qs[0]) == "work_authorization"
    assert (qs[1].kind, qs[1].name) == ("tel", "phone")


def test_pick_button_treats_a_submit_looking_next_as_submit() -> None:
    nxt = Control("a1", "button", "Continue", type="button")
    send = Control("a2", "button", "Submit application", type="submit")
    assert pick_button([nxt, send], FieldMap(next_button="a1")) == ("next", nxt)
    assert pick_button([nxt, send], FieldMap(next_button="a2")) == ("submit", send)
    assert pick_button([nxt, send], FieldMap()) == ("submit", send)  # lone submit-looking button
    assert pick_button([nxt], FieldMap()) == ("stop", None)
    saving = Control("a3", "button", "Save and continue", type="submit")
    assert not saving.submit_like and pick_button([saving], FieldMap(next_button="a3"))[0] == "next"
