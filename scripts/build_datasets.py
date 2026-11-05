"""Build the small offline JSON files in src/linkit_all/data/ from public datasets.

    uv run python scripts/build_datasets.py            # download once into build/datasets/, build
    uv run python scripts/build_datasets.py --fresh    # download everything again

Sources (attribution is in NOTICE):
  GeoNames cities15000 + countryInfo (CC-BY 4.0), O*NET database "Job Titles" and "Sample of
  Reported Titles" (CC-BY 4.0), ExchangeRate-API open endpoint (one snapshot for fx.json).
The raw downloads stay in build/ (gitignored); only the compact JSON is committed.
"""

import argparse
import json
import re
import sys
import unicodedata
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "build" / "datasets"
OUT = ROOT / "src" / "linkit_all" / "data"

GEONAMES = "https://download.geonames.org/export/dump/"
ONET_VERSION = "31_0"  # bump when O*NET publishes a new release; v31 calls the file "Job Titles"
ONET_ZIP = f"https://www.onetcenter.org/dl_files/database/db_{ONET_VERSION}_text.zip"
FX_URL = "https://open.er-api.com/v6/latest/USD"

MAX_CITIES_BYTES = 2_000_000
MAX_TITLES_BYTES = 1_500_000

# Arab League (22): every city >= 15k there is kept whatever the size cap says.
ARAB_LEAGUE = {
    "DZ", "BH", "KM", "DJ", "EG", "IQ", "JO", "KW", "LB", "LY", "MR",
    "MA", "OM", "PS", "QA", "SA", "SO", "SD", "SY", "TN", "AE", "YE",
}  # fmt: skip
# GeoNames spells a few countries in ways nobody types.
RENAME = {"PS": "Palestine", "MK": "North Macedonia", "CZ": "Czechia", "CD": "DR Congo"}

# Hand-checked Arabic names: all Arab League countries plus major job markets. Others stay "".
COUNTRY_AR = {
    "DZ": "الجزائر", "BH": "البحرين", "KM": "جزر القمر", "DJ": "جيبوتي", "EG": "مصر",
    "IQ": "العراق", "JO": "الأردن", "KW": "الكويت", "LB": "لبنان", "LY": "ليبيا",
    "MR": "موريتانيا", "MA": "المغرب", "OM": "عُمان", "PS": "فلسطين", "QA": "قطر",
    "SA": "السعودية", "SO": "الصومال", "SD": "السودان", "SY": "سوريا", "TN": "تونس",
    "AE": "الإمارات", "YE": "اليمن",
    "US": "الولايات المتحدة", "GB": "المملكة المتحدة", "CA": "كندا", "AU": "أستراليا",
    "NZ": "نيوزيلندا", "DE": "ألمانيا", "FR": "فرنسا", "ES": "إسبانيا", "IT": "إيطاليا",
    "NL": "هولندا", "BE": "بلجيكا", "CH": "سويسرا", "AT": "النمسا", "SE": "السويد",
    "NO": "النرويج", "DK": "الدنمارك", "FI": "فنلندا", "IE": "أيرلندا", "PT": "البرتغال",
    "PL": "بولندا", "TR": "تركيا", "IN": "الهند", "PK": "باكستان", "BD": "بنغلاديش",
    "CN": "الصين", "JP": "اليابان", "KR": "كوريا الجنوبية", "SG": "سنغافورة",
    "MY": "ماليزيا", "ID": "إندونيسيا", "PH": "الفلبين", "TH": "تايلاند", "VN": "فيتنام",
    "BR": "البرازيل", "MX": "المكسيك", "AR": "الأرجنتين", "ZA": "جنوب أفريقيا",
    "NG": "نيجيريا", "KE": "كينيا", "RU": "روسيا", "UA": "أوكرانيا", "GR": "اليونان",
    "IL": "إسرائيل", "IR": "إيران", "CY": "قبرص", "RO": "رومانيا", "CZ": "التشيك",
    "HU": "المجر", "LU": "لوكسمبورغ", "HK": "هونغ كونغ", "TW": "تايوان",
}  # fmt: skip
# City names where the GeoNames alternatenames pick below is ambiguous; checked by hand.
CITY_AR = {
    ("Amman", "JO"): "عمان", ("Dubai", "AE"): "دبي", ("Jeddah", "SA"): "جدة",
    ("Mecca", "SA"): "مكة المكرمة", ("Medina", "SA"): "المدينة المنورة",
    ("Abu Dhabi", "AE"): "أبو ظبي", ("Muscat", "OM"): "مسقط", ("Doha", "QA"): "الدوحة",
    ("Cairo", "EG"): "القاهرة", ("Giza", "EG"): "الجيزة", ("Alexandria", "EG"): "الإسكندرية",
    ("Riyadh", "SA"): "الرياض", ("Casablanca", "MA"): "الدار البيضاء",
    ("Rabat", "MA"): "الرباط", ("Tunis", "TN"): "تونس", ("Baghdad", "IQ"): "بغداد",
    ("Kuwait City", "KW"): "مدينة الكويت", ("Manama", "BH"): "المنامة",
    ("Beirut", "LB"): "بيروت", ("Damascus", "SY"): "دمشق", ("Khartoum", "SD"): "الخرطوم",
    ("Algiers", "DZ"): "الجزائر", ("Tripoli", "LY"): "طرابلس", ("Sharjah", "AE"): "الشارقة",
    ("Dammam", "SA"): "الدمام", ("Alexandria", "US"): "",  # not the Egyptian city
}  # fmt: skip

_TASHKEEL = re.compile("[ً-ٰٟـ]")
# Plain Arabic letters only: drops the Persian, Urdu, Kurdish and Uyghur spellings.
_PLAIN_AR = re.compile("^[ء-غف-ي]+(?:[ -][ء-غف-ي]+)*$")
# A "ة" inside a word is Kurdish spelling; "province / governorate of X" is not the city's name.
_NOT_A_NAME = re.compile("ة(?![ -]|$)|^(?:ولاية|استان|محافظة|شهر) ")


def fetch(url: str, dest: Path, fresh: bool) -> Path:
    if fresh or not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        print("downloading", url)
        with urllib.request.urlopen(url, timeout=120) as r:  # noqa: S310 (fixed https URLs)
            dest.write_bytes(r.read())
    return dest


def write_json(name: str, data: object) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    (OUT / name).write_text(text + "\n", encoding="utf-8")
    size = (OUT / name).stat().st_size
    count = len(data) if isinstance(data, list) else len(data["rates"])  # type: ignore[index]
    print(f"{name}: {count} rows, {size / 1e6:.2f} MB")
    return size


def jobspy_keys() -> dict[str, str]:
    """Every spelling jobspy accepts for a country -> the key it is stored under."""
    from jobspy.model import Country  # a runtime dependency of the app

    keys: dict[str, str] = {}
    for c in Country:
        names = str(c.value[0]).split(",")
        for n in names:
            keys[n.strip()] = names[0].strip()
    return keys


def build_countries(raw: Path) -> list[dict[str, str]]:
    from linkit_all.core.presets import country_preset

    spy = jobspy_keys()
    out = []
    for line in raw.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        f = line.split("\t")
        iso2, name, cur, phone = f[0], RENAME.get(f[0], f[4]), f[10], f[12]
        if not (phone := re.sub(r"\D", "", re.split(r"\s|,", phone.lstrip("+"))[0])):
            continue
        key = country_preset(name).jobspy or spy.get(name.lower(), "")
        out.append({"iso2": iso2, "name": name, "name_ar": COUNTRY_AR.get(iso2, ""),
                    "phone": phone, "currency": cur, "jobspy": key})  # fmt: skip
    return sorted(out, key=lambda c: c["name"])


def pick_arabic(alternates: list[str]) -> str:
    """First plausible Arabic-script name; plain Arabic letters, a leading "ال" and a final
    teh marbuta or yeh (not heh or alef maksura) are the tie-breakers GeoNames order cannot give."""
    best, best_score = "", -1
    for alt in alternates:
        alt = _TASHKEEL.sub("", alt).strip()
        if len(alt) < 2 or not _PLAIN_AR.match(alt) or _NOT_A_NAME.search(alt):
            continue
        score = 2 * alt.startswith("ال") + (alt[-1] not in "هى")
        if score > best_score:
            best, best_score = alt, score
    return best


def build_cities(raw: Path) -> list[dict[str, object]]:
    rows = []
    for line in zipfile.ZipFile(raw).read("cities15000.txt").decode("utf-8").splitlines():
        f = line.split("\t")
        name, cc, pop = f[1], f[8], int(f[14] or 0)
        ar = CITY_AR.get((name, cc))
        if ar is None:
            ar = pick_arabic(f[3].split(","))
        rows.append({"n": name, "ar": ar, "c": cc, "p": pop})
    rows.sort(key=lambda r: (-int(r["p"]), str(r["n"])))  # type: ignore[call-overload]
    # Size cap: drop the smallest non-Arab-League towns first.
    while (
        len(json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()) > MAX_CITIES_BYTES
    ):
        drop = next(i for i in range(len(rows) - 1, -1, -1) if rows[i]["c"] not in ARAB_LEAGUE)
        del rows[drop : drop + max(1, len(rows) // 100)]
    return rows


def build_titles(raw: Path) -> list[str]:
    z = zipfile.ZipFile(raw)
    root = f"db_{ONET_VERSION}_text/"

    def column(name: str) -> list[str]:
        lines = z.read(root + name).decode("utf-8").splitlines()[1:]
        return [unicodedata.normalize("NFC", ln.split("\t")[1]).strip() for ln in lines]

    seen: set[str] = set()
    out: list[str] = []
    for title in column("Sample of Reported Titles.txt") + column("Job Titles.txt"):
        key = title.casefold()
        if key in seen or len(title) > 50 or len(title.split()) > 5 or re.search(r"\d", title):
            continue
        seen.add(key)
        out.append(title)
    out.sort(key=lambda t: (len(t), t.casefold()))
    while (
        len(json.dumps(out, ensure_ascii=False, separators=(",", ":")).encode()) > MAX_TITLES_BYTES
    ):
        del out[-max(1, len(out) // 100) :]  # longest (most specific) titles go first
    return out


def build_fx(raw: Path) -> dict[str, object]:
    data = json.loads(raw.read_text("utf-8"))
    if data.get("result") != "success":
        sys.exit("exchange rate API did not return success")
    day = datetime.fromtimestamp(data["time_last_update_unix"], UTC).date().isoformat()
    return {"base": "USD", "date": day, "rates": data["rates"]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fresh", action="store_true", help="download every source again")
    fresh = ap.parse_args().fresh
    sys.path.insert(0, str(ROOT / "src"))
    write_json(
        "countries.json",
        build_countries(fetch(GEONAMES + "countryInfo.txt", RAW / "countryInfo.txt", fresh)),
    )
    write_json(
        "cities.json",
        build_cities(fetch(GEONAMES + "cities15000.zip", RAW / "cities15000.zip", fresh)),
    )
    write_json(
        "titles.json", build_titles(fetch(ONET_ZIP, RAW / f"db_{ONET_VERSION}_text.zip", fresh))
    )
    write_json("fx.json", build_fx(fetch(FX_URL, RAW / "fx_raw.json", fresh)))


if __name__ == "__main__":
    main()
