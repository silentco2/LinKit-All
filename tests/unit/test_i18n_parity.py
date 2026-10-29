"""en.ts and ar.ts must have the same keys; Arabic may add the extra CLDR plural forms (.zero/.two/.few/.many)."""

import re
from pathlib import Path

I18N = Path(__file__).resolve().parents[2] / "frontend" / "src" / "app" / "i18n"
KEY = re.compile(r"^\s*'([^']+)':", re.MULTILINE)
EXTRA = (".zero", ".two", ".few", ".many")
AR_FORMS = ("zero", "one", "two", "few", "many", "other")


def keys(name: str) -> set[str]:
    return set(KEY.findall((I18N / f"{name}.ts").read_text(encoding="utf-8")))


def test_ar_matches_en_except_plural_forms() -> None:
    en, ar = keys("en"), keys("ar")
    assert len(en) > 500  # the parser found the dictionary
    assert not en - ar, f"missing in ar.ts: {sorted(en - ar)}"
    extra = ar - en
    bad = sorted(k for k in extra if not k.endswith(EXTRA))
    assert not bad, f"only .zero/.two/.few/.many may be Arabic-only: {bad}"
    orphans = sorted(k for k in extra if k.rsplit(".", 1)[0] + ".other" not in en)
    assert not orphans, f"plural form without an English base: {orphans}"


def test_arabic_plurals_have_all_six_forms() -> None:
    ar = keys("ar")
    bases = {k.rsplit(".", 1)[0] for k in ar if k.endswith(EXTRA)}
    assert len(bases) >= 14
    for base in bases:
        missing = [f for f in AR_FORMS if f"{base}.{f}" not in ar]
        assert not missing, f"{base} lacks Arabic forms {missing}"
