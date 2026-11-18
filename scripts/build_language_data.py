"""Generate backend/app/data/{madlad_languages,language_catalog}.json from the checkpoint audit and the probe results.

Inputs : docs/reports/madlad-audit/checkpoint.json and probe-results.json (made by scripts/language_audit.py).
Outputs: backend/app/data/madlad_languages.json  (which `<2xx>` tokens the checkpoint really has, plus HAN aliases)
         backend/app/data/language_catalog.json  (one entry per language: English name, optional native name and script, probe evidence)
English names come from pycountry (ISO 639); native names and scripts are curated for major languages only and are left empty otherwise.
Run:  ~/.han-venvs/han/bin/python scripts/build_language_data.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pycountry

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "docs" / "reports" / "madlad-audit"
OUT = ROOT / "backend" / "app" / "data"

# HAN code -> MADLAD token, only where HAN's public code differs from the checkpoint's token (verified present in the token set).
ALIASES = {"tl": "fil", "nb": "no", "jw": "jv", "iw": "he", "zh-hans": "zh", "zh-hant": "zh_Hant", "pt-br": "pt", "pt-pt": "pt", "fr-ca": "fr_CA",
           "sr-latn": "sr", "mo": "ro", "in": "id"}

NATIVE = {  # curated: native name, script
    "en": ("English", "Latn"), "de": ("Deutsch", "Latn"), "fr": ("Français", "Latn"), "es": ("Español", "Latn"), "pt": ("Português", "Latn"),
    "it": ("Italiano", "Latn"), "nl": ("Nederlands", "Latn"), "pl": ("Polski", "Latn"), "ru": ("Русский", "Cyrl"), "uk": ("Українська", "Cyrl"),
    "tr": ("Türkçe", "Latn"), "ar": ("العربية", "Arab"), "he": ("עברית", "Hebr"), "fa": ("فارسی", "Arab"), "hi": ("हिन्दी", "Deva"),
    "bn": ("বাংলা", "Beng"), "ur": ("اردو", "Arab"), "ta": ("தமிழ்", "Taml"), "te": ("తెలుగు", "Telu"), "th": ("ไทย", "Thai"),
    "vi": ("Tiếng Việt", "Latn"), "id": ("Bahasa Indonesia", "Latn"), "ms": ("Bahasa Melayu", "Latn"), "fil": ("Filipino", "Latn"),
    "zh": ("中文", "Hans"), "ja": ("日本語", "Jpan"), "ko": ("한국어", "Kore"), "sw": ("Kiswahili", "Latn"), "yo": ("Yorùbá", "Latn"),
    "ha": ("Hausa", "Latn"), "ig": ("Igbo", "Latn"), "am": ("አማርኛ", "Ethi"), "zu": ("isiZulu", "Latn"), "xh": ("isiXhosa", "Latn"),
    "af": ("Afrikaans", "Latn"), "so": ("Soomaali", "Latn"), "rw": ("Ikinyarwanda", "Latn"), "ln": ("Lingála", "Latn"), "lg": ("Luganda", "Latn"),
    "wo": ("Wolof", "Latn"), "om": ("Afaan Oromoo", "Latn"), "ti": ("ትግርኛ", "Ethi"), "sn": ("chiShona", "Latn"), "st": ("Sesotho", "Latn"),
    "tn": ("Setswana", "Latn"), "ny": ("Chichewa", "Latn"), "mg": ("Malagasy", "Latn"), "qu": ("Runasimi", "Latn"), "gn": ("Avañe'ẽ", "Latn"),
    "ay": ("Aymar aru", "Latn"), "el": ("Ελληνικά", "Grek"), "ro": ("Română", "Latn"), "sv": ("Svenska", "Latn"), "da": ("Dansk", "Latn"),
    "no": ("Norsk", "Latn"), "fi": ("Suomi", "Latn"), "cs": ("Čeština", "Latn"), "hu": ("Magyar", "Latn"), "bg": ("Български", "Cyrl"),
    "sr": ("Српски", "Cyrl"), "hr": ("Hrvatski", "Latn"), "ka": ("ქართული", "Geor"), "hy": ("Հայերեն", "Armn"), "ne": ("नेपाली", "Deva"),
    "mr": ("मराठी", "Deva"), "gu": ("ગુજરાતી", "Gujr"), "kn": ("ಕನ್ನಡ", "Knda"), "ml": ("മലയാളം", "Mlym"), "pa": ("ਪੰਜਾਬੀ", "Guru"),
    "si": ("සිංහල", "Sinh"), "km": ("ខ្មែរ", "Khmr"), "my": ("မြန်မာ", "Mymr"), "lo": ("ລາວ", "Laoo"), "ht": ("Kreyòl ayisyen", "Latn"),
    "jv": ("Basa Jawa", "Latn"), "la": ("Latina", "Latn"), "ca": ("Català", "Latn"),
}
RTL = {"Arab", "Hebr", "Thaa"}


def name_for(code: str) -> tuple[str, bool]:
    rec = pycountry.languages.get(alpha_2=code) or pycountry.languages.get(alpha_3=code)
    if rec:
        return getattr(rec, "common_name", None) or rec.name, True
    return code, False  # no ISO name found: an administrator should review this entry


def main() -> None:
    ck = json.loads((AUDIT / "checkpoint.json").read_text())
    tokens = ck["language_tokens"]
    plain, variants = sorted(tokens["plain"]), sorted(tokens["variants"])
    for alias, target in ALIASES.items():
        assert target in plain or target in variants, f"alias {alias}->{target} is not a token in the checkpoint"
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "madlad_languages.json").write_text(json.dumps({
        "checkpoint": {"repository": ck["repository"], "revision": ck["revision"], "licence": ck["licence_from_model_card"], "audited_at": ck["generated_at"]},
        "plain": plain, "variants": variants, "aliases": ALIASES}, indent=1, ensure_ascii=False) + "\n")
    probe = json.loads((AUDIT / "probe-results.json").read_text())
    catalog = {}
    for code in plain:
        nm, known = name_for(code)
        native, script = NATIVE.get(code, (None, None))
        ev = probe["results"].get(code)
        catalog[code] = {"name": nm, "name_reviewed": known, "native_name": native, "script": script, "rtl": script in RTL,
                         "probe": None if not ev else {"status": ev["status"], "similarity": ev.get("roundtrip_similarity"), "flags": ev.get("flags", [])}}
    (OUT / "language_catalog.json").write_text(json.dumps({"probe_text": probe["probe_text"], "probed_at": probe["updated_at"], "languages": catalog},
                                                         indent=1, ensure_ascii=False) + "\n")
    print(f"{len(plain)} languages, {len(variants)} variants, {sum(1 for v in catalog.values() if not v['name_reviewed'])} without an ISO name")


if __name__ == "__main__":
    main()
