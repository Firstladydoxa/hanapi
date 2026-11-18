"""Basic QA rules. Each rule takes a QAContext and returns a list of warning dicts
({type, severity, message, span}). Messages are linguistic/actionable and never assert certainty."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

NON_LATIN_SCRIPTS = {"Cyrillic", "Arabic", "Hebrew", "Devanagari", "Bengali", "Tamil", "Thai", "Han", "Japanese", "Hangul", "Ethiopic",
                     "Han (Simplified)", "Han (Traditional)", "Greek"}


@dataclass
class QAContext:
    source_text: str
    target_text: str
    source_language: str
    target_language: str
    target_script: Optional[str] = None
    terms: List[Any] = field(default_factory=list)  # approved TerminologyEntry rows found in source
    prior_translations: List[Any] = field(default_factory=list)  # approved TM exact rows for the same source (same project)


def warn(type_: str, message: str, severity: str = "warning", span: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    return {"type": type_, "severity": severity, "message": message, "span": span}
