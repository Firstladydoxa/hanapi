"""Terminology compliance: approved target term present, forbidden alternatives absent."""
from __future__ import annotations

from typing import List

from ..terminology.terminology import contains_term
from . import QAContext, warn


def check(ctx: QAContext) -> List[dict]:
    out: List[dict] = []
    for e in ctx.terms:
        if not contains_term(ctx.target_text, e.target_term):
            out.append(warn("terminology", f"The approved term for \u201c{e.source_term}\u201d is \u201c{e.target_term}\u201d, "
                            "which does not appear in the translation. I\u2019m not fully confident about this term in the "
                            "given context. I\u2019ve highlighted it for your review."))
        for bad in (e.forbidden_alternatives or []):
            if contains_term(ctx.target_text, bad):
                out.append(warn("terminology", f"\u201c{bad}\u201d is listed as not to be used for \u201c{e.source_term}\u201d. "
                                f"The approved term is \u201c{e.target_term}\u201d."))
    return out
