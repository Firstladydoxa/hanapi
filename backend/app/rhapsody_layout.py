"""Rhapsody of Realities layout intelligence: recognises the monthly articles in a manuscript and merges them into the master template.

The master is the InDesign layout exported as XLIFF (static front matter, labels, inserts, back matter, with its inline tags) plus the
month's daily articles taken from the Word manuscript. Everything here is deterministic and testable; no model is involved.
"""
from __future__ import annotations

import html
import re
from calendar import month_name, monthrange
from datetime import date
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTHS = [month_name[i] for i in range(1, 13)]
TAG = re.compile(r"<\d+/>|\[\[[A-Za-z]+/\]\]")
_WD = r"(?:mon|tues?|wed(?:nes)?|thu(?:rs?)?|fri|sat(?:ur)?|sun)(?:day)?"
_MN = "|".join(m.lower() for m in MONTHS)
DAY_LABEL = re.compile(rf"^\W*(?:(?P<wd>{_WD})\W*)?(?:(?P<mn>{_MN})\W+)?(?:day\s+)?(?P<n>\d{{1,2}})(?:st|nd|rd|th)?"
                       rf"(?:\W+(?:of\s+)?(?P<mn2>{_MN}))?(?:\W+\d{{4}})?\W*$", re.I)
CLOSING_LABEL = re.compile(r"^\W*(prayer|confession|prayer\s+points?|declaration)\W*$", re.I)
CLOSING_INLINE = re.compile(r"^\W*(prayer|confession)\s*[:\-–—]\s*(.+)$", re.I | re.S)
FURTHER = re.compile(r"^\W*further\s+stud(?:y|ies)\W*(.*)$", re.I | re.S)
PLAN1 = re.compile(r"^\W*1\s*[- ]?\s*year\b.*?plan\W*(.*)$", re.I | re.S)
PLAN2 = re.compile(r"^\W*2\s*[- ]?\s*year\b.*?plan\W*(.*)$", re.I | re.S)
SCRIPTURE_REF_ONLY = re.compile(r"^\W*\(?[1-3]?\s?[A-Za-z][A-Za-z .]+\d+[:\d,\-–& ]*\)?\W*$")
REFERENCE_LIKE = re.compile(r"^[1-3]?\s?[A-Za-z][A-Za-z .]*\s\d+(?:[:\d,;\-–& ]|\s[1-3]?\s?[A-Za-z][A-Za-z .]*\s\d+)*\W*$")


def strip_tags(text: str) -> str:
    return TAG.sub("", text)


def tags_in(text: str) -> List[str]:
    return TAG.findall(text or "")


def tags_preserved(source: str, target: str) -> bool:
    return sorted(tags_in(source)) == sorted(tags_in(target))


# ------------------------------------------------------------------------------------------------- DOCX manuscript
def _is_upper(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return len(letters) >= 3 and all(c.isupper() for c in letters)


def _paragraphs(data: bytes) -> List[Dict[str, Any]]:
    """Paragraphs of the manuscript in reading order, with table cells flattened in place."""
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(BytesIO(data))
    out: List[Dict[str, Any]] = []

    def add(p: Paragraph) -> None:
        text = p.text.replace("\u00a0", " ").strip()
        if not text:
            return
        style = p.style.name if p.style is not None else ""
        runs = [{"text": r.text, "bold": bool(r.bold), "italic": bool(r.italic)} for r in p.runs if r.text]
        out.append({"text": re.sub(r"[ \t]+", " ", text), "style": style, "runs": runs})

    def walk(parent: Any) -> None:
        for child in parent.iterchildren():
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                add(Paragraph(child, doc))
            elif tag == "tbl":
                for row in Table(child, doc).rows:
                    seen = set()
                    for cell in row.cells:
                        if id(cell._tc) in seen:
                            continue
                        seen.add(id(cell._tc))
                        for p in cell.paragraphs:
                            add(p)

    walk(doc.element.body)
    return out


def _day_number(text: str, year: int, month: int, last: int) -> Optional[int]:
    """The article day when `text` is a day heading ("SUNDAY 1", "November 1", "Day 1"), else None. Days must run forward."""
    if len(text) > 40 or text.endswith((".", ",")):
        return None
    m = DAY_LABEL.match(text)
    if not m:
        return None
    n = int(m.group("n"))
    named = m.group("mn") or m.group("mn2")
    if named and MONTHS.index(named.capitalize()) + 1 != month:
        return None
    last_day = monthrange(year, month)[1]
    if n < 1 or n > last_day or n <= last:
        return None
    if m.group("wd"):
        expected = date(year, month, n).weekday()
        if not WEEKDAYS[expected].lower().startswith(m.group("wd").lower()[:3]):
            return None
    elif not (named or re.match(r"^\W*day\b", text, re.I)):
        return None
    return n


def parse_manuscript(data: bytes, year: int, month: int) -> List[Dict[str, Any]]:
    """Split the Word manuscript into the month's daily articles and recognise each part of an article."""
    paras = _paragraphs(data)
    starts: List[Tuple[int, int]] = []
    last = 0
    for i, p in enumerate(paras):
        n = _day_number(p["text"], year, month, last)
        if n is not None:
            starts.append((i, n))
            last = n
    articles = []
    for k, (i, n) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else len(paras)
        articles.append(_parse_article(n, year, month, paras[i + 1:end]))
    return articles


def _parse_article(day: int, year: int, month: int, paras: List[Dict[str, Any]]) -> Dict[str, Any]:
    rest = list(paras)
    art: Dict[str, Any] = {"day": day, "title": "", "scripture": "", "scripture_ref": "", "body": [], "closing_type": None,
                           "closing": "", "further": "", "plan1": "", "plan2": "", "runs": {}, "issues": []}

    title: List[str] = []
    while rest and (_is_upper(rest[0]["text"]) or (not title and len(rest[0]["text"]) < 120 and not rest[0]["text"].endswith((".", "”", '"'))
                                                  and "heading" in rest[0]["style"].lower())) and len(title) < 3:
        if CLOSING_LABEL.match(rest[0]["text"]):
            break
        title.append(rest.pop(0)["text"])
    if not title and rest and len(rest[0]["text"]) < 90 and not rest[0]["text"].endswith((".", "”", '"')):
        title.append(rest.pop(0)["text"])
    art["title"] = " ".join(title)

    # the reference block: labelled lines (value inline or on the next line), else positional lines at the end
    labelled = {"further": False, "plan1": False, "plan2": False}
    first = next((j for j, p in enumerate(rest) if any(rx.match(p["text"]) for rx in (FURTHER, PLAN1, PLAN2))), None)
    if first is not None:
        block, rest = rest[first:], rest[:first]
        current = None
        for p in block:
            for key, rx in (("further", FURTHER), ("plan1", PLAN1), ("plan2", PLAN2)):
                m = rx.match(p["text"])
                if m:
                    current, art[key], labelled[key] = key, m.group(1).strip(), True
                    break
            else:
                if current:
                    art[current] = f"{art[current]} {p['text']}".strip()
    if not all(labelled.values()):
        # unlabelled trailing reference lines map positionally to further study, 1-year and 2-year plans
        refs: List[str] = []
        while rest and len(refs) < 3 and len(rest[-1]["text"]) < 160 and REFERENCE_LIKE.match(rest[-1]["text"]) and not CLOSING_LABEL.match(rest[-1]["text"]):
            refs.insert(0, rest.pop()["text"])
        slots = [k for k in ("further", "plan1", "plan2") if not art[k]]
        for key, value in zip(slots[-len(refs):] if refs else [], refs):
            art[key] = value

    closing_at = next((j for j in range(len(rest) - 1, -1, -1) if CLOSING_LABEL.match(rest[j]["text"]) or CLOSING_INLINE.match(rest[j]["text"])), None)
    if closing_at is not None:
        head = rest[closing_at]["text"]
        inline = CLOSING_INLINE.match(head)
        art["closing_type"] = (inline.group(1) if inline else CLOSING_LABEL.match(head).group(1)).strip().lower().split()[0]  # type: ignore[union-attr]
        art["closing"] = inline.group(2).strip() if inline else " ".join(p["text"] for p in rest[closing_at + 1:])
        rest = rest[:closing_at]

    if rest:
        first = rest[0]["text"]
        inline_ref = re.search(r"\(\s*([1-3]?\s?[A-Za-z][A-Za-z .]+\d+[:\d,\-–& ]*)\)\W*$", first)
        looks_like_scripture = (first[:1] in "“\"‘'" or inline_ref is not None or (len(rest) > 1 and SCRIPTURE_REF_ONLY.match(rest[1]["text"]) is not None)
                                or any(r["italic"] for r in rest[0]["runs"]))
        if looks_like_scripture:
            scripture = rest.pop(0)
            text = scripture["text"]
            if len(rest) and SCRIPTURE_REF_ONLY.match(rest[0]["text"]) and len(rest[0]["text"]) < 60:
                art["scripture_ref"] = rest.pop(0)["text"].strip().strip("().; ")
            elif inline_ref:
                art["scripture_ref"] = inline_ref.group(1).strip()
                text = text[:inline_ref.start()].rstrip()
            art["scripture"] = text
    art["body"] = [{"text": p["text"], "runs": p["runs"]} for p in rest]

    for field, label in (("title", "title"), ("scripture", "opening scripture"), ("closing", "prayer or confession"),
                         ("further", "further study"), ("plan1", "1-year reading plan"), ("plan2", "2-year reading plan")):
        if not art[field]:
            art["issues"].append(f"Day {day}: no {label} was recognised")
    if not art["body"]:
        art["issues"].append(f"Day {day}: no body paragraphs were recognised")
    return art


# ------------------------------------------------------------------------------------------------- XLIFF template
def _text_of(el: ET.Element) -> str:
    return html.unescape("".join(el.itertext())).replace("\u00a0", " ").strip()


def parse_template(data: bytes) -> List[Dict[str, Any]]:
    """Ordered translation units of the InDesign layout (inline tags such as <1/> are kept inside the text)."""
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("unsafe XML")
    root = ET.fromstring(data)
    units = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1].lower() != "trans-unit":
            continue
        src = next((c for c in node if c.tag.rsplit("}", 1)[-1].lower() == "source"), None)
        if src is None:
            continue
        text = _text_of(src)
        if text:
            units.append({"id": node.attrib.get("id") or str(len(units) + 1), "text": text})
    return units


def is_untranslatable(text: str) -> bool:
    """Phone numbers, e-mail and web addresses, ISSN and Bible-version codes are carried over unchanged."""
    t = strip_tags(text).strip()
    if not t or "@" in t or re.match(r"(?i)^(www\.|https?://)", t) or re.match(r"(?i)^issn\b", t):
        return True
    if re.fullmatch(r"[A-Z0-9]{2,8}", t) and not re.fullmatch(r"\d+", t):
        return True
    return not re.search(r"[A-Za-z]{4,}", re.sub(r"(?i)\b(tel|fax|phone|mobile|email|e-mail)\b", "", t))


def _label_of(text: str) -> Optional[int]:
    """Weekday index of a template day label such as "tuesday<1/> <2/>8", else None."""
    t = strip_tags(text).strip()
    m = re.match(rf"^({_WD})\W*(\d{{1,2}})$", t, re.I)
    if not m:
        return None
    for i, name in enumerate(WEEKDAYS):
        if name.lower().startswith(m.group(1).lower()[:3]):
            return i
    return None


def classify_template(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    """front matter, article sample units, inserts between articles, back matter."""
    labels = [i for i, u in enumerate(units) if _label_of(u["text"]) is not None]
    if not labels:
        return {"front": units, "inserts": [], "back": [], "articles": 0, "labels": {}}
    front = units[:labels[0]]
    inserts: List[Dict[str, Any]] = []
    back: List[Dict[str, Any]] = []
    for k, start in enumerate(labels):
        stop = labels[k + 1] if k + 1 < len(labels) else len(units)
        block = units[start:stop]
        closing = next((j for j, u in enumerate(block) if CLOSING_LABEL.match(strip_tags(u["text"]))), None)
        extra = block[closing + 5:] if closing is not None else []  # closing label, its text and three reference lines (5 units) end the article
        if extra:
            (back if k + 1 == len(labels) else inserts).append({"after_article": k + 1, "units": extra})
    labels_text = {}
    for u in units:
        t = strip_tags(u["text"]).strip().rstrip(":").lower()
        if t in {"further study", "1-year bible reading plan", "2-year bible reading plan", "prayer", "confession"}:
            labels_text[t] = u
    return {"front": front, "inserts": inserts, "back": back, "articles": len(labels), "labels": labels_text}


def localise_month(text: str, old: Optional[Tuple[str, str]], year: int, month: int) -> str:
    """Re-date the template: "May 2018 edition" -> "November 2026 edition", "Copyright © 2018" -> "Copyright © 2026"."""
    if not old:
        return text
    old_month, old_year = old
    text = re.sub(rf"\b{old_month}\s+{old_year}\b", f"{MONTHS[month - 1]} {year}", text, flags=re.I)
    return re.sub(rf"\b{old_year}\b", str(year), text)


def template_period(units: List[Dict[str, Any]]) -> Optional[Tuple[str, str]]:
    for u in units:
        m = re.search(rf"\b({'|'.join(MONTHS)})\s+(\d{{4}})\s+edition", u["text"], re.I)
        if m:
            return m.group(1), m.group(2)
    return None


# ------------------------------------------------------------------------------------------------- the master
def build_master(year: int, month: int, articles: List[Dict[str, Any]], template: Optional[List[Dict[str, Any]]]) -> Tuple[List[dict], List[dict], Dict[str, Any]]:
    """Merge the month's articles into the template. Returns (sections, segments, info) in the PR's structure format."""
    sections: List[dict] = []
    segments: List[dict] = []
    info: Dict[str, Any] = {"template_units": len(template or []), "locked": 0}

    def section(key: str, kind: str, title: str, day: Optional[int] = None, formatting: Optional[dict] = None) -> str:
        sections.append({"stable_key": key, "section_type": kind, "title": title[:500], "sequence": len(sections), "day_number": day,
                         "formatting": formatting or {}})
        return key

    def seg(section_key: str, key: str, text: str, role: str, **meta: Any) -> None:
        text = text.strip()
        if not text:
            return
        locked = role in {"static", "insert"} and is_untranslatable(text)
        info["locked"] += 1 if locked else 0
        segments.append({"stable_key": key, "source_text": text, "source_markup": None, "sequence": len(segments), "section_key": section_key,
                         "metadata": {"role": role, "locked": locked, **meta}})

    period = template_period(template or [])
    cls = classify_template(template or []) if template else {"front": [], "inserts": [], "back": [], "articles": 0, "labels": {}}

    def add_units(units: List[Dict[str, Any]], key: str, kind: str, title: str, role: str) -> None:
        if not units:
            return
        sk = section(key, kind, title)
        for u in units:
            seg(sk, f"tpl-{u['id']}", localise_month(u["text"], period, year, month), role, trans_unit_id=u["id"])

    add_units(cls["front"], "front-matter", "front_matter", "Cover, copyright and introduction", "static")

    sk = section("labels", "labels", "Recurring labels")
    fixed = [("further-study", "FURTHER STUDY:"), ("plan-1", "1-YEAR BIBLE READING PLAN"), ("plan-2", "2-YEAR BIBLE READING PLAN"),
             ("prayer", "PRAYER"), ("confession", "CONFESSION")]
    for key, text in fixed:
        found = next((u for t, u in cls["labels"].items() if t == text.lower().rstrip(":")), None)
        seg(sk, f"label-{key}", strip_tags(found["text"]) if found else text, "label", label=key)
    for i, name in enumerate(WEEKDAYS):
        seg(sk, f"label-weekday-{i}", name.upper(), "label", label=f"weekday-{i}")

    inserts = {i["after_article"]: i["units"] for i in cls["inserts"]}
    for art in articles:
        n = art["day"]
        d = date(year, month, n)
        weekday = d.weekday()
        sk = section(f"day-{n}", "daily_article", art["title"] or f"Day {n}", n, {"weekday": weekday, "date": d.isoformat()})
        base = {"day": n, "weekday": weekday, "date": d.isoformat()}
        seg(sk, f"d{n}-title", art["title"], "title", **base)
        seg(sk, f"d{n}-scripture", art["scripture"], "scripture", **base)
        seg(sk, f"d{n}-scripture-ref", art["scripture_ref"], "scripture_ref", **base)
        for k, p in enumerate(art["body"], 1):
            seg(sk, f"d{n}-body-{k}", p["text"], "body", runs=p["runs"][:40], **base)
        seg(sk, f"d{n}-closing", art["closing"], "closing", closing_type=art["closing_type"] or "prayer", **base)
        seg(sk, f"d{n}-further", art["further"], "further_study", **base)
        seg(sk, f"d{n}-plan1", art["plan1"], "plan1", **base)
        seg(sk, f"d{n}-plan2", art["plan2"], "plan2", **base)
        if n in inserts:
            add_units(inserts[n], f"insert-after-{n}", "insert", f"Insert after day {n}", "insert")
    tail = [u for b in cls["back"] for u in b["units"]]
    add_units(tail, "back-matter", "back_matter", "Back matter", "insert")
    return sections, segments, info


def validate_master(year: int, month: int, articles: List[Dict[str, Any]], has_template: bool) -> Dict[str, Any]:
    expected = monthrange(year, month)[1]
    found = [a["day"] for a in articles]
    missing = [d for d in range(1, expected + 1) if d not in found]
    warnings: List[str] = []
    blocking: List[str] = []
    if not articles:
        blocking.append("No daily articles were recognised. Each article must start with a day heading such as \"SUNDAY 1\", \"November 1\" or \"Day 1\".")
    elif missing:
        warnings.append(f"The manuscript has {len(articles)} of {expected} articles. Missing days: " + ", ".join(map(str, missing)))
    for a in articles:
        warnings.extend(a["issues"])
    if not has_template:
        warnings.append("No layout template (InDesign XLIFF) was supplied or found, so the cover, introduction and back matter are not included.")
    return {"articles": len(articles), "expected_articles": expected, "missing_days": missing, "warnings": warnings, "blocking_errors": blocking}
