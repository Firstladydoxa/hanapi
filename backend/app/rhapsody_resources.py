"""Reads TNI's per-language "additional information" sheet (introduction, copyright page, Personal Information labels, months, weekdays,
Bible book names, salvation prayer, author biography and back text) into reusable publishing resources."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

KNOWN_LABELS = {"prayer": "prayer", "confession": "confession", "further study": "further-study",
                "1 year bible plan reading": "plan-1", "2 year bible plan reading": "plan-2", "note": "notes"}
FIELDS = ["name", "home address", "home telephone", "mobile", "e-mail address", "business address"]
ALIASES = {"Psalm": "Psalms", "Revelation": "Revelation of John", "Song of Songs": "Song of Solomon"}
ROMAN = {"I": "1", "II": "2", "III": "3"}
BULLET_LEAD = re.compile(r"^[\s·•\-–—\t]+")
COLUMNS = re.compile(r"\s{3,}|\t+\s*")


class ResourceSheetError(ValueError):
    pass


def _find(items: List[str], pred) -> Optional[int]:
    return next((i for i, t in enumerate(items) if pred(t.lower())), None)


def _pairs(items: List[str]) -> List[tuple[str, str]]:
    seq = [t for t in items if not t.strip().isdigit()]
    return list(zip(seq[0::2], seq[1::2]))


def _address_lines(lines: List[str]) -> List[str]:
    """The printed address block has two columns; HAN re-reads it block by block (left column, then right)."""
    out: List[str] = []
    left: List[str] = []
    right: List[str] = []

    def flush() -> None:
        out.extend(left + right)
        left.clear(); right.clear()

    for line in lines:
        cells = [c.strip() for c in COLUMNS.split(line.strip()) if c.strip()]
        if len(cells) >= 2:
            if cells[0].endswith(":") and cells[1].endswith(":"):
                flush()
            left.append(cells[0]); right.append(" ".join(cells[1:]))
        elif len(line) > 80:
            flush(); out.append(line.strip())
        elif cells and cells[0].endswith(":"):
            flush(); left.append(cells[0])
        elif cells and (left or right):
            left.append(cells[0])
        elif cells:
            out.append(cells[0])
    flush()
    return out


def parse_sheet(paragraphs: List[str]) -> Dict[str, Any]:
    p = [t.strip() for t in paragraphs if t and t.strip()]
    i_sn = _find(p, lambda t: t == "s/n")
    i_tr = _find(p, lambda t: t == "translation")
    i_months = _find(p, lambda t: t == "months of the year")
    if i_sn is None or i_tr is None or i_months is None:
        raise ResourceSheetError("This does not look like a TNI language information sheet (the S/N, TRANSLATION and Months of the Year parts were not found).")
    i_kindly = _find(p[i_tr:], lambda t: t.startswith("(kindly send the translated"))
    i_kindly = i_tr + i_kindly if i_kindly is not None else i_months
    i_mt = _find(p, lambda t: t.startswith("months of the year (translation"))
    i_dt = _find(p, lambda t: t.startswith("days of the week (translation"))
    i_books = _find(p, lambda t: "books of the bible" in t)
    i_back = _find(p, lambda t: t == "backtext")
    warnings: List[str] = []
    perm: Dict[str, List[str]] = {}

    intro = p[:i_sn]
    hi = next((i for i, t in enumerate(intro) if i > 0 and t.startswith("-") and t.rstrip().endswith("-") and len(t) < 140), None)
    perm["intro.heading"] = [intro[0]]
    if hi is None:
        perm["intro.paragraphs"] = intro[1:]
    else:
        perm["intro.paragraphs"] = intro[1:hi]
        perm["howto.heading"] = [intro[hi].strip("- \t")]
        tail = [BULLET_LEAD.sub("", t) for t in intro[hi + 1:]]
        if len(tail) >= 3:
            perm["howto.items"], perm["intro.closing"], perm["intro.signoff"] = tail[:-2], [tail[-2]], [tail[-1]]
        else:
            perm["howto.items"] = tail

    table = {en: tr for en, tr in _pairs(p[i_tr + 1:i_kindly])}
    lower = {k.lower(): v for k, v in table.items()}
    labels = {key: lower[name] for name, key in KNOWN_LABELS.items() if name in lower}
    if "rhapsody of realities" in lower:
        perm["title.name"] = [lower["rhapsody of realities"]]
    if "... a daily devotional" in lower:
        perm["title.sub"] = [lower["... a daily devotional"].lstrip("….").strip()]
    if "personal information" in lower:
        perm["personal.title"] = [lower["personal information"]]
    fields = [lower[f] for f in FIELDS if f in lower]
    if fields:
        perm["personal.fields"] = fields
    if "goals for the month" in lower:
        perm["personal.goals"] = [lower["goals for the month"]]
    perm["labels.table"] = [f"{en} = {tr}" for en, tr in table.items()]

    between = [t for t in p[i_kindly + 1:i_months] if not t.lower().startswith("(kindly")]
    heads = [i for i, t in enumerate(between) if t.isupper() and len(t) < 50 and not any(c.isdigit() for c in t)]
    cut = heads[0] if heads else len(between)
    perm["copyright.lines"] = _address_lines(between[:cut])
    if heads:
        perm["salvation.items"] = between[heads[0]:heads[1]] if len(heads) > 1 else between[heads[0]:]
    if len(heads) > 1:
        perm["authors.items"] = between[heads[1]:]
    else:
        warnings.append("The author biography was not found.")
    if i_back is not None:
        perm["backtext.items"] = p[i_back + 1:]

    months = [tr for _, tr in _pairs(p[i_mt + 1:i_mt + 25])] if i_mt is not None else []
    weekdays = [tr for _, tr in _pairs(p[i_dt + 1:i_dt + 15])] if i_dt is not None else []
    if len(months) != 12:
        warnings.append(f"Expected 12 months, found {len(months)}."); months = []
    if len(weekdays) != 7:
        warnings.append(f"Expected 7 weekdays, found {len(weekdays)}."); weekdays = []

    books: Dict[str, str] = {}
    if i_books is not None:
        seq = p[i_books + 1:i_back if i_back is not None else len(p)]
        for marker, count in (("old testament", 39), ("new testament", 27)):
            at = _find(seq, lambda t, m=marker: t == m)
            if at is None:
                warnings.append(f"The {marker.title()} book list was not found."); continue
            local, english = seq[at + 1:at + 1 + count], seq[at + 1 + count:at + 1 + 2 * count]
            if len(local) != count or len(english) != count:
                warnings.append(f"The {marker.title()} list has fewer than {count} books."); continue
            books.update(dict(zip(english, local)))
    else:
        warnings.append("No Bible book names were found.")

    year = re.findall(r"\b(20\d\d)\b", " ".join(perm["copyright.lines"]))
    if year:
        warnings.append(f"The copyright page mentions {', '.join(sorted(set(year)))}. Update the year to the edition being printed.")
    return {"labels": labels, "months": months, "weekdays": weekdays, "book_names": books, "permanent": perm, "warnings": warnings}


def _pattern(name: str) -> str:
    m = re.match(r"^(III|II|I)\s+(.+)$", name)
    if m:
        return rf"(?:{m.group(1)}|{ROMAN[m.group(1)]})\s*{re.escape(m.group(2))}"
    return "Psalms?" if name == "Psalms" else re.escape(name)


def localize_refs(text: str, book_names: Dict[str, str]) -> str:
    """Replaces English Bible book names in a reference line with the language's names ('1 Kings 3:5; Psalm 23' -> localized)."""
    if not text or not book_names:
        return text
    names = dict(book_names)
    for alias, target in ALIASES.items():
        if target in names:
            names.setdefault(alias, names[target])
    ordered = sorted(names, key=len, reverse=True)
    compiled = [(n, re.compile(_pattern(n))) for n in ordered]
    combined = re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(_pattern(n) for n in ordered) + r")(?![A-Za-z])")

    def swap(m: re.Match) -> str:
        for n, rx in compiled:
            if rx.fullmatch(m.group(0)):
                return names[n]
        return m.group(0)

    return combined.sub(swap, text)
