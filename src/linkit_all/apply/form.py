"""Read an application form's questions from the page and fill answers back in.

Each ATS handler names its question container and label selectors; one script tags every
container with data-lk="<key>" and describes its controls. Filling uses those keys.
"""

from typing import Any

from playwright.async_api import Page

from linkit_all.apply.answers import Question

_EXTRACT = r"""
({container, label, description, ignore}) => {
  const clean = (t) => (t || '').replace(/[*✱]/g, '').replace(/\s+/g, ' ').trim();
  // File, radio and checkbox inputs are often visually hidden behind custom styling.
  const visible = (el) => ['file', 'radio', 'checkbox'].includes(el.type) || !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const optionText = (el) => {
    const byFor = el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
    return clean((byFor || el.closest('label') || el.parentElement).innerText) || el.value;
  };
  const out = [];
  let n = 0;
  for (const box of document.querySelectorAll(container)) {
    if (box.parentElement && box.parentElement.closest('[data-lk]')) continue;  // nested container
    const controls = [...box.querySelectorAll('input, select, textarea, button[type=button], button[aria-pressed], [role=combobox]')]
      .filter((c) => c.type !== 'hidden' && !(c.type === 'submit' && !c.hasAttribute('aria-pressed'))
        && c.name !== 'g-recaptcha-response'
        && !(ignore && c.matches(ignore)) && visible(c));
    if (!controls.length) continue;
    const kinds = controls.map((c) =>
      c.tagName === 'SELECT' ? 'select' : c.tagName === 'TEXTAREA' ? 'textarea'
        : (c.getAttribute('role') === 'combobox' || c.classList.contains('select__input')) ? 'combobox'
        : c.tagName === 'BUTTON' ? 'button' : (c.type || 'text'));
    const labelEl = box.querySelector(label);
    const raw = labelEl ? labelEl.innerText : '';
    let kind = kinds[0], options = [];
    if (kinds.includes('file')) kind = 'file';
    else if (kinds.includes('select')) {
      kind = 'select';
      options = [...box.querySelector('select').options].map((o) => clean(o.text))
        .filter((t, i) => t && !(i === 0 && /^(select|choose|please|--|click here)/i.test(t)));
    } else if (kinds.includes('combobox')) kind = 'combobox';
    else if (kinds.includes('radio')) { kind = 'radio'; options = controls.filter((c) => c.type === 'radio').map(optionText); }
    else if (kinds.includes('button') && controls.filter((c) => c.tagName === 'BUTTON').every((b) => /^(yes|no)$/i.test(clean(b.innerText)))) {
      kind = 'yesno'; options = controls.filter((c) => c.tagName === 'BUTTON').map((b) => clean(b.innerText));
    }
    else if (kinds.filter((k) => k === 'checkbox').length > 1) { kind = 'multi'; options = controls.filter((c) => c.type === 'checkbox').map(optionText); }
    else if (kinds.includes('checkbox')) { kind = 'checkbox'; options = [optionText(controls.find((c) => c.type === 'checkbox'))]; }
    else if (kinds.every((k) => k === 'button')) { kind = 'yesno'; options = controls.map((c) => clean(c.innerText)); }
    else if (kind === 'button') kind = 'text';
    const key = 'lk' + (n++);
    box.setAttribute('data-lk', key);
    const first = (kind === 'file' && controls.find((c) => c.type === 'file')) || controls[0];
    first.setAttribute('data-lk-input', key);  // the exact control to fill (not a widget's search box)
    out.push({
      key, kind, options,
      label: clean(raw) || (kind === 'checkbox' ? optionText(controls.find((c) => c.type === 'checkbox')) : ''),
      // "*" or "✱" in the text, the required attribute, or a CSS-drawn marker (Ashby: class _required_x)
      required: /[*✱]/.test(raw) || /required/i.test(labelEl?.className || '')
        || controls.some((c) => c.required || c.getAttribute('aria-required') === 'true'),
      name: first.name || first.id || '',
      description: description ? clean(box.querySelector(description)?.innerText) : '',
    });
  }
  return out;
}
"""


class FillError(RuntimeError):
    pass


async def extract(
    page: Page, container: str, label: str, description: str = "", ignore: str = ""
) -> list[Question]:
    raw: list[dict[str, Any]] = await page.evaluate(
        _EXTRACT,
        {"container": container, "label": label, "description": description, "ignore": ignore},
    )
    return [Question(**q) for q in raw if q["label"] or q["kind"] == "file"]


async def fill(page: Page, q: Question, value: Any) -> None:
    """Put `value` into the question's controls. Raises FillError if the page refuses it."""
    box = page.locator(f'[data-lk="{q.key}"]')
    try:
        match q.kind:
            case "file":
                await box.locator("input[type=file]").first.set_input_files(str(value))
            case "select":
                await page.locator(f'[data-lk-input="{q.key}"]').select_option(label=str(value))
            case "radio":
                await _choose(page, box, str(value), "radio")
            case "multi":
                for v in value:
                    await _choose(page, box, str(v), "checkbox")
            case "checkbox":
                if value:
                    await box.locator("input[type=checkbox]").first.check()
            case "yesno":
                await box.get_by_role("button", name=str(value), exact=True).click()
            case "combobox":
                await _combobox(page, box, str(value), exact=bool(q.options))
            case _:
                await page.locator(f'[data-lk-input="{q.key}"]').fill(str(value))
    except FillError:
        raise
    except Exception as e:  # Playwright timeouts etc.: report which question failed
        raise FillError(f"could not fill {q.label!r}: {e}") from e


async def _choose(page: Page, box: Any, text: str, role: str) -> None:
    control = box.get_by_role(role, name=text, exact=True)
    if await control.count():
        await control.first.check()
        return
    label = box.locator("label").filter(has_text=text)  # custom-styled inputs: click the label
    if not await label.count():
        raise FillError(f"option {text!r} not found")
    await label.first.click()


async def _combobox(page: Page, box: Any, text: str, exact: bool) -> None:
    """React-select style: type, then pick the option from the opened list."""
    field = box.locator("[data-lk-input]")
    await field.click()
    await field.fill(text)
    options = (
        page.get_by_role("option", name=text, exact=True) if exact else page.get_by_role("option")
    )
    try:
        await options.first.click(timeout=8000)
    except Exception as e:
        raise FillError(f"no option {text!r} in the list") from e


_TEXT_KINDS = {"text", "textarea", "email", "tel", "number", "url", "date"}


async def lost_values(
    page: Page, questions: list[Question], answers: dict[str, Any]
) -> list[Question]:
    """Text fields whose value did not stick (React forms can reset fields while hydrating)."""
    lost = []
    for q in questions:
        if q.kind in _TEXT_KINDS and q.key in answers:
            current = await page.locator(f'[data-lk-input="{q.key}"]').input_value()
            if current.strip() != str(answers[q.key]).strip():
                lost.append(q)
    return lost
