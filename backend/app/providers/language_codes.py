"""Language-code mapping tables. HAN uses lower-case BCP-47-ish codes (en, de, pt-br...).

Each provider adapter maps HAN codes to its native format here, and raises
`UnsupportedLanguage` for codes the provider cannot take. These tables reflect public
model documentation at the time of writing and MUST be re-verified against the live model
cards before a direction is promoted (see docs: language readiness).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional

# FLORES-200 codes used by NLLB-family models.
FLORES: Dict[str, str] = {
    "en": "eng_Latn", "de": "deu_Latn", "fr": "fra_Latn", "es": "spa_Latn", "pt": "por_Latn",
    "it": "ita_Latn", "nl": "nld_Latn", "pl": "pol_Latn", "ru": "rus_Cyrl", "uk": "ukr_Cyrl",
    "tr": "tur_Latn", "ar": "arb_Arab", "he": "heb_Hebr", "fa": "pes_Arab", "hi": "hin_Deva",
    "bn": "ben_Beng", "ur": "urd_Arab", "ta": "tam_Taml", "th": "tha_Thai", "vi": "vie_Latn",
    "id": "ind_Latn", "ms": "zsm_Latn", "tl": "tgl_Latn", "zh": "zho_Hans", "zh-hant": "zho_Hant",
    "ja": "jpn_Jpan", "ko": "kor_Hang",
    # Africa
    "sw": "swh_Latn", "yo": "yor_Latn", "ha": "hau_Latn", "ig": "ibo_Latn", "am": "amh_Ethi",
    "zu": "zul_Latn", "xh": "xho_Latn", "af": "afr_Latn", "so": "som_Latn", "rw": "kin_Latn",
    "ln": "lin_Latn", "lg": "lug_Latn", "wo": "wol_Latn", "om": "gaz_Latn", "ti": "tir_Ethi",
    "sn": "sna_Latn", "st": "sot_Latn", "tn": "tsn_Latn", "ny": "nya_Latn", "mg": "plt_Latn",
    # South America
    "qu": "quy_Latn", "gn": "grn_Latn", "ay": "ayr_Latn",
}

# African languages (plus common pivots) for the AfriNLLB family. Verify against the model card.
AFRINLLB_CODES = {
    "en", "fr", "pt", "ar", "sw", "yo", "ha", "ig", "am", "zu", "xh", "af", "so", "rw", "ln", "lg", "wo", "om",
    "ti", "sn", "st", "tn", "ny", "mg",
}

# MADLAD-400: the supported `<2xx>` tokens are read from the checkpoint itself (app/data/madlad_languages.json, produced by
# scripts/language_audit.py + scripts/build_language_data.py), never typed by hand. HAN codes are lower-case; aliases map the few
# HAN/ISO codes that differ from the checkpoint's token (tl -> fil, nb -> no, zh-hant -> zh_Hant ...).
_DATA = Path(__file__).resolve().parents[1] / "data" / "madlad_languages.json"


@lru_cache(maxsize=1)
def madlad_table() -> Dict[str, str]:
    """HAN code (lower-case) -> the exact MADLAD target token."""
    d = json.loads(_DATA.read_text())
    table = {t: t for t in d["plain"]}
    table.update({v.lower().replace("_", "-"): v for v in d["variants"] if "_" in v and v[0].islower()})
    table.update(d["aliases"])
    return table


def madlad_token(code: str) -> Optional[str]:
    return madlad_table().get(code.lower())


MADLAD_SUPPORTED = frozenset(madlad_table())

GOOGLE_EXCEPTIONS: Dict[str, str] = {
    "zh": "zh-CN", "zh-hans": "zh-CN", "zh-hant": "zh-TW", "tl": "fil", "he": "iw", "pt-br": "pt", "nb": "no",
}


def flores(code: str) -> Optional[str]:
    return FLORES.get(code.lower())
