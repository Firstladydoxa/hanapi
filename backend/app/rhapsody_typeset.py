"""Typesets a Rhapsody of Realities master (English or translated) into a print-style PDF.

It reproduces what the admins do by hand in InDesign: a cover, copyright/Bible-key page, introduction, personal-information page,
then one article per day (weekday + date header, title, opening scripture box, body with drop cap, prayer, further study and the
1-year / 2-year reading plan bars), a Notes page each week, and the inserts and back matter from the template. The trim size is
140 x 220 mm like the printed book. Text reflows, so longer languages repaginate by themselves.
"""
from __future__ import annotations

import re
from html import escape
from typing import Any, Dict, List, Optional

TAG = re.compile(r"<\d+/>|\[\[[A-Za-z]+/\]\]")
BULLET = "[[bullet/]]"

DEFAULT_LABELS = {"further-study": "FURTHER STUDY:", "plan-1": "1-YEAR BIBLE READING PLAN", "plan-2": "2-YEAR BIBLE READING PLAN",
                  "prayer": "PRAYER", "confession": "CONFESSION", "notes": "Notes"}
WEEKDAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]

HEADING_STACK = "'Myriad Pro','Lato','Nimbus Sans','DejaVu Sans',sans-serif"
BODY_STACK = "'Optimum','Lato','Nimbus Sans','DejaVu Sans',sans-serif"
SCRIPT_STACK = "'Lato','Nimbus Sans','DejaVu Sans',sans-serif"
COVER_STACK = "'URW Chancery L','Z003','Nimbus Roman',serif"

_FRONT_MARKERS = {"cover": "rhapsody", "bible_key": "unless otherwise", "intro": "introduction", "personal": "personal information"}


def clean(value: Any) -> str:
    return escape(TAG.sub("", str(value or "").replace(BULLET, "• ")))


def _plain(value: Any) -> str:
    return TAG.sub("", str(value or "")).strip()


def split_front_matter(texts: List[str]) -> Dict[str, List[str]]:
    """Partitions the flat front-matter units into cover, copyright, introduction and personal-information pages."""
    pages: Dict[str, List[str]] = {"cover": [], "copyright": [], "intro": [], "personal": [], "tail": []}
    current: Optional[str] = None
    for raw in texts:
        low = _plain(raw).lower()
        if current is None:
            if low == "rhapsody":
                current = "cover"
            else:
                continue
        elif current == "cover" and low.startswith("unless otherwise"):
            current = "copyright"
        elif current == "copyright" and low == "introduction":
            current = "intro"
        elif current == "intro" and low == "personal information":
            current = "personal"
        elif current == "personal" and low == "rhapsody":
            current = "tail"
        pages[current].append(raw)
    return pages


def _css(page_w: float, page_h: float, margin: float, direction: str, font_css: str, roles: Dict[str, str], body_pt: float) -> str:
    head, body, script = roles.get("heading", HEADING_STACK), roles.get("body", BODY_STACK), roles.get("scripture", SCRIPT_STACK)
    align = "right" if direction == "rtl" else "left"
    return font_css + f"""
@page {{ size:{page_w}mm {page_h}mm; margin:{margin}mm {margin}mm {margin + 4}mm {margin}mm;
  @bottom-center {{ content: counter(page); font:7.5pt {head}; color:#444; }} }}
@page plain {{ margin:{margin}mm; @bottom-center {{ content:none; }} }}
html {{ direction:{direction}; }}
body {{ font:{body_pt}pt/1.38 {body}; color:#111; margin:0; }}
p {{ margin:0 0 2.2mm; orphans:2; widows:2; text-align:justify; hyphens:auto; }}
.plain {{ page:plain; break-before:page; }}
.cover {{ page:plain; text-align:center; padding-top:34mm; }}
.cover .t1 {{ font:italic 44pt/1.0 {COVER_STACK}; margin:0 0 3mm; }}
.cover .t2 {{ font:italic 44pt/1.0 {COVER_STACK}; margin:0 0 6mm; }}
.cover .sub {{ font:700 9pt {head}; letter-spacing:.5mm; margin:0 0 70mm; }}
.cover .by {{ font:italic 28pt {COVER_STACK}; }}
.cover .month {{ font:700 10pt {head}; margin-top:14mm; letter-spacing:.4mm; }}
.small {{ column-count:2; column-gap:5mm; }}
.small p {{ font-size:6.2pt; line-height:1.25; margin:0 0 .8mm; text-align:{align}; hyphens:none; }}
.small p.k {{ font-weight:700; margin-top:1.6mm; }}
.intro h1, .personal h1 {{ font:700 12pt {head}; text-align:center; margin:0 0 4mm; text-transform:uppercase; }}
.personal h1 {{ background:#222; color:#fff; padding:1.4mm 0; }}
.personal .line {{ border-bottom:.3mm solid #555; height:7mm; font:7.5pt {head}; }}
.day {{ break-before:page; }}
.day .head {{ display:flex; justify-content:space-between; align-items:baseline; background:#e4e4e4; padding:1.6mm 3mm; margin:0 0 3mm;
  font:700 8.5pt {head}; letter-spacing:.2mm; }}
.day .head .n {{ font-size:13pt; }}
.day h2 {{ font:800 13pt/1.2 {head}; text-align:center; text-transform:uppercase; margin:0 0 3.5mm; break-after:avoid; }}
.scripture {{ background:#e9e9e9; border-{('right' if direction == 'rtl' else 'left')}:1.2mm solid #888; padding:2.4mm 3.4mm; margin:0 0 4mm;
  font:italic 700 9pt/1.35 {script}; text-align:{align}; }}
.day .b:first-of-type::first-letter {{ font:700 27pt/0.85 {head}; float:{align}; padding:.8mm 1.2mm 0 0; }}
.rule {{ font:800 11.5pt {head}; text-align:center; text-transform:uppercase; margin:4mm 0 1.6mm; break-after:avoid; }}
.end {{ break-inside:avoid; }}
.closing {{ font-weight:700; text-align:center; }}
.refs {{ text-align:center; font-size:{body_pt - 0.5}pt; }}
.bar {{ background:#bdbdbd; font:800 8.4pt {head}; text-align:center; padding:1.2mm 0; margin:2.4mm 0 1.4mm; text-transform:uppercase; }}
.notes {{ break-before:page; }}
.notes h3 {{ font:italic 14pt {COVER_STACK}; text-align:center; color:#888; margin:0 0 3mm; }}
.notes .line {{ border-bottom:.25mm solid #999; height:7.6mm; }}
.insert, .back {{ break-before:page; }}
.insert p, .back p {{ text-align:{align}; }}
"""


def typeset_pdf(sections: List[Dict[str, Any]], blocks: List[Dict[str, Any]], *, title: str, year: int, month: int,
                direction: str = "ltr", lang: str = "en", page_mm: tuple = (140.0, 220.0), margin_mm: float = 12.0,
                body_pt: float = 9.6, font_css: str = "", role_fonts: Optional[Dict[str, str]] = None,
                month_label: Optional[str] = None) -> bytes:
    """`sections`: dicts with id/key/type/day/formatting. `blocks`: dicts with section_id/key/role/text/meta, text already in the target language."""
    from weasyprint import HTML

    by_section: Dict[str, List[Dict[str, Any]]] = {}
    for b in blocks:
        by_section.setdefault(b["section_id"], []).append(b)
    labels = dict(DEFAULT_LABELS)
    weekdays = list(WEEKDAYS)
    for s in sections:
        if s["type"] == "labels":
            for b in by_section.get(s["id"], []):
                key = b["key"]
                if key.startswith("label-weekday-"):
                    weekdays[int(key.rsplit("-", 1)[1])] = _plain(b["text"]).upper()
                elif key.startswith("label-"):
                    labels[key[6:]] = _plain(b["text"])

    out: List[str] = []
    front = next((s for s in sections if s["type"] == "front_matter"), None)
    texts = [b["text"] for b in by_section.get(front["id"], [])] if front else []
    pages = split_front_matter(texts)
    cover = [_plain(t) for t in pages["cover"]]
    edition_line = month_label or f"{month:02d}/{year}"
    if cover:
        out.append(f'<div class="cover"><div class="t1">{clean(cover[0])}</div><div class="t2">{clean(cover[1] if len(cover) > 1 else "")}</div>'
                   f'<div class="sub">{clean(cover[2] if len(cover) > 2 else "")}</div>'
                   f'<div class="by">{clean(cover[3] if len(cover) > 3 else "")}</div><div class="month">{clean(edition_line)}</div></div>')
    else:
        out.append(f'<div class="cover"><div class="t1">Rhapsody</div><div class="t2">of Realities</div><div class="month">{clean(edition_line)}</div></div>')
    if pages["copyright"]:
        paras = []
        merged: List[str] = []
        for t in pages["copyright"]:
            if _plain(t).startswith("-") and merged:
                merged[-1] = f"{merged[-1]}  {t}"
            else:
                merged.append(t)
        for t in merged:
            p = _plain(t)
            key = len(p) < 8 and p.isupper() or p.endswith(":") or p.lower() in {"united kingdom:", "south africa:", "usa:", "canada:", "nigeria:"}
            paras.append(f'<p class="{"k" if key else ""}">{clean(t)}</p>')
        out.append(f'<div class="plain small">{"".join(paras)}</div>')
    if pages["intro"]:
        head, *rest = pages["intro"]
        out.append(f'<div class="plain intro"><h1>{clean(head)}</h1>{"".join(f"<p>{clean(t)}</p>" for t in rest)}</div>')
    if pages["personal"]:
        head, *rest = pages["personal"]
        gi = next((i for i, t in enumerate(rest) if _plain(t).lower().startswith("goals")), len(rest) - 1)
        goals = rest[gi:gi + 1]
        rows = "".join(f'<div class="line">{clean(t)}</div>' for t in rest[:gi])
        extra = "".join('<div class="line"></div>' for _ in range(8))
        out.append(f'<div class="plain personal"><h1>{clean(head)}</h1>{rows}'
                   f'<p class="rule">{clean(goals[0]) if goals else ""}</p>{extra}</div>')

    note_lines = '<div class="line"></div>' * 24
    notes_page = f'<div class="notes"><h3>{clean(labels["notes"])}</h3>{note_lines}</div>'
    for s in sections:
        items = by_section.get(s["id"], [])
        if s["type"] == "daily_article":
            roles = {b["role"]: b["text"] for b in items if b["role"] != "body"}
            meta = s.get("formatting") or {}
            wd = meta.get("weekday")
            day = s.get("day") or ""
            body = "".join(f'<p class="b">{clean(b["text"])}</p>' for b in items if b["role"] == "body")
            ref = _plain(roles.get("scripture_ref"))
            scripture = clean(roles.get("scripture"))
            closing_kind = next((b.get("meta", {}).get("closing_type") for b in items if b["role"] == "closing"), None) or "prayer"
            closing_label = labels.get("confession" if closing_kind == "confession" else "prayer", "PRAYER")
            html_day = [f'<div class="day"><div class="head"><span>{clean(weekdays[wd]) if isinstance(wd, int) and 0 <= wd < 7 else ""}</span>'
                        f'<span class="n">{clean(day)}</span></div>', f'<h2>{clean(roles.get("title"))}</h2>']
            if scripture:
                html_day.append(f'<div class="scripture">{scripture}{f" ({escape(ref)})" if ref else ""}</div>')
            html_day.append(body)
            html_day.append('<div class="end">')
            if roles.get("closing"):
                html_day.append(f'<div class="rule">{clean(closing_label)}</div><p class="closing">{clean(roles["closing"])}</p>')
            if roles.get("further_study"):
                html_day.append(f'<div class="rule">{clean(labels["further-study"].rstrip(":") + ":")}</div><p class="refs">{clean(roles["further_study"])}</p>')
            for rk, lk in (("plan1", "plan-1"), ("plan2", "plan-2")):
                if roles.get(rk):
                    html_day.append(f'<div class="bar">{clean(labels[lk])}</div><p class="refs">{clean(roles[rk])}</p>')
            html_day.append("</div></div>")
            out.append("".join(html_day))
            if isinstance(wd, int) and wd == 6:
                out.append(notes_page)
        elif s["type"] in {"insert", "back_matter"} and items:
            cls = "insert" if s["type"] == "insert" else "back"
            inner = "".join("<p>" + clean(b["text"]) + "</p>" for b in items)
            out.append(f'<div class="{cls}">{inner}</div>')
    out.append(notes_page)

    css = _css(page_mm[0], page_mm[1], margin_mm, direction, font_css, role_fonts or {}, body_pt)
    document = (f"<!doctype html><html lang='{escape(lang)}' dir='{direction}'><head><meta charset='utf-8'><title>{escape(title)}</title>"
                f"<style>{css}</style></head><body>{''.join(out)}</body></html>")
    return HTML(string=document, base_url=None).write_pdf()
