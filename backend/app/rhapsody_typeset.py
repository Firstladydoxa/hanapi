"""Typesets a Rhapsody of Realities master (English or translated) into a print-style PDF.

It reproduces what the admins do by hand in InDesign: a cover, copyright/Bible-key page, introduction, personal-information page,
then one article per day (weekday + date header, title, opening scripture box, body with drop cap, prayer, further study and the
1-year / 2-year reading plan bars), a Notes page each week, and the inserts and back matter from the template. The trim size is
140 x 220 mm like the printed book. Text reflows, so longer languages repaginate by themselves.
"""
from __future__ import annotations

import re
import base64
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

BIBLE_SVG = ('<svg viewBox="0 0 24 24"><path d="M2 5c3-1.5 7-1.5 10 1v14c-3-2.5-7-2.5-10-1z" fill="#555"/>'
             '<path d="M22 5c-3-1.5-7-1.5-10 1v14c3-2.5 7-2.5 10-1z" fill="#777"/></svg>')
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
        elif current == "personal" and low == "rhapsody of realities":
            current = "tail"
        pages[current].append(raw)
    return pages


def _css(page_w: float, page_h: float, margin: float, direction: str, font_css: str, roles: Dict[str, str], body_pt: float,
         title_pt: float = 13.0, scripture_pt: float = 9.0) -> str:
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
.day {{ page:art; break-before:left; }}
.banner {{ height:38mm; margin:-{margin}mm -{margin}mm 4mm -{margin}mm; background:#8a8f94 center/cover no-repeat; position:relative; }}
.banner .ph {{ position:absolute; left:{margin}mm; top:14mm; color:#fff; font:italic 8pt {head}; opacity:.8; }}
.banner .tab {{ position:absolute; right:{margin}mm; bottom:0; background:#e4e4e4; padding:1.2mm 4mm; font:600 7.5pt {head}; letter-spacing:.3mm; }}
.banner .tab b {{ font-size:13pt; margin-left:1.5mm; }}
.day h2 {{ font:800 {title_pt}pt/1.2 {head}; text-align:center; text-transform:uppercase; margin:0 0 3.5mm; break-after:avoid; }}
.scripture {{ display:flex; background:#e4e4e4; margin:0 0 4mm; padding:2.4mm 0 2.4mm 2.4mm; }}
.scripture svg {{ flex:none; width:9mm; height:9mm; margin-right:2.6mm; }}
.scripture .tx {{ flex:1; font:italic 700 {scripture_pt}pt/1.35 {script}; text-align:{align}; }}
.scripture .bar2 {{ flex:none; width:3mm; background:#9a9a9a; margin:-2.4mm 0; margin-left:2.4mm; }}
.day .b:first-of-type::first-letter {{ font:700 27pt/0.85 {head}; float:{align}; padding:.8mm 1.2mm 0 0; }}
.rule {{ font:800 11.5pt {head}; text-align:center; text-transform:uppercase; margin:4mm 0 0; padding-bottom:1mm; break-after:avoid;
  border-bottom:.2mm solid #777; }}
.rule + p {{ margin-top:1.6mm; }}
.end {{ break-inside:avoid; }}
.closing {{ font-weight:700; }}
.refs {{ text-align:center; font-size:{body_pt - 0.5}pt; }}
.bar {{ background:#bdbdbd; font:800 8.4pt {head}; text-align:center; padding:1.2mm 0; margin:2.4mm 0 1.4mm; text-transform:uppercase; }}
.notes {{ break-before:page; }}
.notes h3 {{ font:italic 14pt {COVER_STACK}; text-align:center; color:#888; margin:0 0 3mm; }}
.notes .line {{ border-bottom:.25mm solid #999; height:7.6mm; }}
.tail {{ text-align:center; padding-top:70mm; }}
.tail .a {{ font:italic 20pt {COVER_STACK}; }}
.tail .b2 {{ font:700 8pt {head}; letter-spacing:.4mm; margin:2mm 0 8mm; }}
.tail .c {{ font:8pt {head}; }}
.intro .banner2 {{ background:#222; color:#fff; border-radius:3mm; padding:2.4mm 0; text-align:center; font:italic 22pt {COVER_STACK}; margin:0 0 4mm; }}
.intro .strip {{ text-align:center; font:700 8pt {head}; margin:3mm 0; }}
.intro .panel {{ background:#222; color:#fff; border-radius:3mm; padding:3mm 4mm; margin:0 0 3mm; }}
.intro .panel p {{ text-align:{align}; margin:0 0 1.8mm; }}
.intro p.dc:first-of-type::first-letter {{ font:italic 30pt/0.85 {COVER_STACK}; float:{align}; padding:0 1.2mm 0 0; }}
@page art {{ margin:{margin}mm {margin}mm {margin + 4}mm {margin}mm; @bottom-center {{ content:none; }} }}
@page art:left {{ @bottom-left {{ content:counter(page); font:700 7pt {head}; color:#fff; background:#111; border-radius:50%; width:5.5mm; line-height:5.5mm; text-align:center; }} }}
@page art:right {{ @bottom-right {{ content:counter(page); font:700 7pt {head}; color:#fff; background:#111; border-radius:50%; width:5.5mm; line-height:5.5mm; text-align:center; }} }}
.insert, .back {{ break-before:page; }}
.insert p, .back p {{ text-align:{align}; }}
"""


def typeset_pdf(sections: List[Dict[str, Any]], blocks: List[Dict[str, Any]], *, title: str, year: int, month: int,
                direction: str = "ltr", lang: str = "en", page_mm: tuple = (140.0, 220.0), margin_mm: float = 12.0,
                body_pt: float = 9.6, font_css: str = "", role_fonts: Optional[Dict[str, str]] = None,
                month_label: Optional[str] = None, images: Optional[Dict[int, bytes]] = None,
                localization: Optional[Dict[str, Any]] = None, title_pt: float = 13.0, scripture_pt: float = 9.0) -> bytes:
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

    loc = localization or {}
    for i, w in enumerate((loc.get("weekdays") or [])[:7]):
        if str(w).strip():
            weekdays[i] = str(w).strip().upper()
    for k, v in (loc.get("labels") or {}).items():
        if str(v).strip():
            labels[k] = str(v).strip()
    months = loc.get("months") or []
    if len(months) == 12 and str(months[month - 1]).strip():
        month_label = f"{str(months[month - 1]).strip().upper()} {year}"

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
        hi = next((i for i, t in enumerate(rest) if "how to use" in _plain(t).lower()), None)
        if hi is None:
            intro_html = "".join(f"<p>{clean(t)}</p>" for t in rest)
        else:
            lead, strip, tail_p = rest[:hi], rest[hi], rest[hi + 1:]
            cut = max(len(tail_p) - 2, 0)
            items, after = tail_p[:cut], tail_p[cut:]
            intro_html = ("".join(f'<p class="dc">{clean(t)}</p>' for t in lead) + f'<div class="strip">{clean(strip)}</div>'
                          f'<div class="panel">{"".join(f"<p>• {clean(t)}</p>" for t in items)}</div>' + "".join(f"<p>{clean(t)}</p>" for t in after))
        out.append(f'<div class="plain intro"><div class="banner2">{clean(head)}</div>{intro_html}</div>')
    if pages["personal"]:
        head, *rest = pages["personal"]
        gi = next((i for i, t in enumerate(rest) if _plain(t).lower().startswith("goals")), len(rest) - 1)
        goals = rest[gi:gi + 1]
        rows = "".join(f'<div class="line">{clean(t)}</div>' for t in rest[:gi])
        extra = "".join('<div class="line"></div>' for _ in range(8))
        out.append(f'<div class="plain personal"><h1>{clean(head)}</h1>{rows}'
                   f'<p class="rule">{clean(goals[0]) if goals else ""}</p>{extra}</div>')

    if pages["tail"]:
        t = [_plain(x) for x in pages["tail"]]
        out.append(f'<div class="plain tail"><div class="a">{clean(t[0])}</div><div class="b2">{clean(t[1] if len(t) > 1 else "")}</div>'
                   f'<div class="c">{clean(t[2] if len(t) > 2 else "")}</div></div>')

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
            img = (images or {}).get(int(s.get("day") or 0)) if str(s.get("day") or "").isdigit() else None
            style = f' style="background-image:url(data:image/jpeg;base64,{base64.b64encode(img).decode()})"' if img else ""
            ph = "" if img else f'<span class="ph">{clean(labels.get("image", "Article image"))}</span>'
            wlabel = clean(weekdays[wd]) if isinstance(wd, int) and 0 <= wd < 7 else ""
            html_day = [f'<div class="day"><div class="banner"{style}>{ph}<div class="tab">{wlabel}<b>{clean(day)}</b></div></div>',
                        f'<h2>{clean(roles.get("title"))}</h2>']
            if scripture:
                html_day.append(f'<div class="scripture">{BIBLE_SVG}<div class="tx">{scripture}{f" ({escape(ref)})" if ref else ""}</div><div class="bar2"></div></div>')
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
        elif s["type"] in {"insert", "back_matter"} and items:
            cls = "insert" if s["type"] == "insert" else "back"
            inner = "".join("<p>" + clean(b["text"]) + "</p>" for b in items)
            out.append(f'<div class="{cls}">{inner}</div>')
            if s["type"] == "insert":
                out.append(notes_page)
    css = _css(page_mm[0], page_mm[1], margin_mm, direction, font_css, role_fonts or {}, body_pt, title_pt, scripture_pt)
    document = (f"<!doctype html><html lang='{escape(lang)}' dir='{direction}'><head><meta charset='utf-8'><title>{escape(title)}</title>"
                f"<style>{css}</style></head><body>{''.join(out)}</body></html>")
    return HTML(string=document, base_url=None).write_pdf()
