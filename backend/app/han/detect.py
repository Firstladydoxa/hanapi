"""Source-language detection so translators are not asked what language their text is in."""
from functools import lru_cache
from typing import Optional

MIN_CONFIDENCE = 0.5
MIN_CHARS = 5


@lru_cache(maxsize=1)
def _detector():
    from lingua import LanguageDetectorBuilder

    return LanguageDetectorBuilder.from_all_languages().build()


def detect_source(text: str, target: Optional[str] = None) -> Optional[str]:
    """Return an ISO 639-1 code when detection is confident, otherwise None (HAN then asks)."""
    text = (text or "").strip()
    if len(text) < MIN_CHARS:
        return None
    try:
        values = _detector().compute_language_confidence_values(text)
    except Exception:
        return None
    if not values:
        return None
    top = values[0]
    second = values[1].value if len(values) > 1 else 0.0
    # confidence is spread over many languages for short text, so also accept a clear lead
    if top.value < MIN_CONFIDENCE and not (top.value >= 0.15 and top.value >= 2 * second):
        return None
    return top.language.iso_code_639_1.name.lower()
