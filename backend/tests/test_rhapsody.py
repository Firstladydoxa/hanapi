from __future__ import annotations

from io import BytesIO
from docx import Document

from app.api.rhapsody import _parse_docx, _parse_xliff


def test_docx_parser_groups_day_headings_and_keeps_run_formatting():
    doc = Document()
    doc.add_heading("Introduction", level=1)
    doc.add_paragraph("Welcome to this month's devotional.")
    doc.add_heading("Day 1", level=1)
    p = doc.add_paragraph()
    run = p.add_run("Christ ")
    run.bold = True
    p.add_run("is our life.")
    stream = BytesIO()
    doc.save(stream)

    sections, segments = _parse_docx(stream.getvalue())
    assert [s["stable_key"] for s in sections] == ["front-matter", "day-1"]
    assert len(segments) == 4
    assert segments[3]["section_key"] == "day-1"
    assert segments[3]["metadata"]["runs"][0]["bold"] is True


def test_xliff_parser_preserves_trans_unit_id_and_inline_markup():
    xml = b'''<?xml version="1.0" encoding="UTF-8"?>
    <xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">
      <file><body><trans-unit id="para-42"><source>God is <g id="1">love</g>.</source></trans-unit></body></file>
    </xliff>'''
    sections, segments = _parse_xliff(xml)
    assert sections[0]["stable_key"] == "xliff-content"
    assert segments[0]["metadata"]["trans_unit_id"] == "para-42"
    assert "God is love." == segments[0]["source_text"]
    assert 'id="1"' in segments[0]["source_markup"]
    assert "love" in segments[0]["source_markup"]


def _docx(*lines):
    doc = Document()
    for line in lines:
        doc.add_paragraph(line)
    stream = BytesIO()
    doc.save(stream)
    return stream.getvalue()


NOV = _docx(
    "SUNDAY 1", "NO ENCHANTMENT AGAINST YOU", "Surely there is no enchantment against Jacob (Numbers 23:23).",
    "Balak hired Balaam to curse Israel.", "Righteousness is a gift.", "PRAYER", "Blessed Father, thank you.", "FURTHER STUDY:", "Numbers 23:7-9",
    "1-YEAR BIBLE READING PLAN", "Luke 24:13-35", "2-YEAR BIBLE READING PLAN", "1 Corinthians 2:1-11",
    "MONDAY 2", "MEDITATE ON THE WORD", "“We look not at the things which are seen” (2 Corinthians 4:18).", "Meditate day and night.",
    "CONFESSION", "I am blessed.", "Psalm 1:1-3", "John 1:1-18", "1 Corinthians 3:1-9",
)
TEMPLATE = '''<?xml version="1.0" encoding="UTF-8"?><xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2"><file original="x.idml"><body>
<trans-unit id="1"><source xml:lang="en">May 2018 edition</source></trans-unit>
<trans-unit id="2"><source xml:lang="en">Copyright © 2018 by LoveWorld Publishing</source></trans-unit>
<trans-unit id="3"><source xml:lang="en">www.rhapsodyofrealities.org</source></trans-unit>
<trans-unit id="4"><source xml:lang="en">Introduction</source></trans-unit>
<trans-unit id="5"><source xml:lang="en">tuesday&lt;1/&gt; &lt;2/&gt;1</source></trans-unit>
<trans-unit id="6"><source xml:lang="en">SAMPLE TITLE</source></trans-unit>
<trans-unit id="7"><source xml:lang="en">PRAYER</source></trans-unit>
<trans-unit id="8"><source xml:lang="en">Sample prayer text here.</source></trans-unit>
<trans-unit id="9"><source xml:lang="en">Psalm 1</source></trans-unit>
<trans-unit id="10"><source xml:lang="en">Psalm 2</source></trans-unit>
<trans-unit id="11"><source xml:lang="en">Psalm 3</source></trans-unit>
<trans-unit id="12"><source xml:lang="en">Notes</source></trans-unit>
</body></file></xliff>'''.encode("utf-8")


def test_manuscript_articles_are_recognised_part_by_part():
    from app.rhapsody_layout import parse_manuscript

    articles = parse_manuscript(NOV, 2026, 11)
    assert [a["day"] for a in articles] == [1, 2]
    one = articles[0]
    assert one["title"] == "NO ENCHANTMENT AGAINST YOU"
    assert one["scripture"].startswith("Surely there is no enchantment") and one["scripture_ref"] == "Numbers 23:23"
    assert len(one["body"]) == 2 and one["closing_type"] == "prayer" and one["closing"] == "Blessed Father, thank you."
    assert (one["further"], one["plan1"], one["plan2"]) == ("Numbers 23:7-9", "Luke 24:13-35", "1 Corinthians 2:1-11")
    two = articles[1]
    assert two["closing_type"] == "confession" and two["scripture_ref"] == "2 Corinthians 4:18"
    assert (two["further"], two["plan1"], two["plan2"]) == ("Psalm 1:1-3", "John 1:1-18", "1 Corinthians 3:1-9")


def test_master_merges_articles_into_the_template_with_the_new_month():
    from app.rhapsody_layout import build_master, parse_manuscript, parse_template, validate_master

    units = parse_template(TEMPLATE)
    articles = parse_manuscript(NOV, 2026, 11)
    sections, segments, _ = build_master(2026, 11, articles, units)
    assert [s["stable_key"] for s in sections if s["section_type"] == "daily_article"] == ["day-1", "day-2"]
    texts = {s["stable_key"]: s["source_text"] for s in segments}
    assert texts["tpl-1"] == "November 2026 edition" and texts["tpl-2"].startswith("Copyright © 2026")
    assert "tpl-5" not in texts and "tpl-6" not in texts  # the sample article of the template is replaced by the month's articles
    assert texts["tpl-12"] == "Notes"  # back matter is kept
    assert next(s for s in segments if s["stable_key"] == "tpl-3")["metadata"]["locked"] is True
    assert next(s for s in segments if s["stable_key"] == "d1-title")["metadata"]["weekday"] == 6  # 1 November 2026 is a Sunday
    v = validate_master(2026, 11, articles, True)
    assert v["missing_days"][0] == 3 and not v["blocking_errors"]
    assert validate_master(2026, 11, [], True)["blocking_errors"]


def _setup_active_master(admin, tmp_path, monkeypatch, with_template=True):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "rhapsody_storage_dir", str(tmp_path))
    edition_id = admin.post("/v1/rhapsody/editions", {"month": 11, "year": 2026}).json()["id"]

    def upload(name, data, mime):
        r = admin.client.post(f"/v1/rhapsody/editions/{edition_id}/sources", files={"file": (name, data, mime)}, headers=admin._h())
        assert r.status_code == 201, r.text
        return r.json()["id"]

    docx_id = upload("november.docx", NOV, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    data = {"source_file_id": docx_id}
    if with_template:
        data["template_file_id"] = upload("layout.xliff", TEMPLATE, "application/xliff+xml")
    ingested = admin.client.post(f"/v1/rhapsody/editions/{edition_id}/ingest", data=data, headers=admin._h())
    assert ingested.status_code == 200, ingested.text
    master_id = ingested.json()["master_version_id"]
    assert admin.post(f"/v1/rhapsody/editions/{edition_id}/activate?master_version_id={master_id}", {}).status_code == 200
    return edition_id, master_id, ingested.json()["validation"]


def test_rhapsody_full_admin_to_translator_to_review_flow(world, login, tmp_path, monkeypatch):
    admin = login("tina")
    edition_id, master_id, validation = _setup_active_master(admin, tmp_path, monkeypatch)
    assert validation["articles"] == 2 and validation["locked_segments"] >= 1

    assigned = admin.post("/v1/rhapsody/assignments", {"master_version_id": master_id, "target_language": "fr",
                                                       "translator_id": str(world.users["alice"].id), "reviewer_id": str(world.users["rita"].id)})
    assert assigned.status_code == 201, assigned.text
    assignment_id = assigned.json()["id"]

    translator = login("alice")
    detail = translator.get(f"/v1/rhapsody/assignments/{assignment_id}").json()
    locked = [s for s in detail["segments"] if s["metadata"].get("locked")]
    assert locked and all(s["target_text"] == s["source_text"] for s in locked)
    open_segments = [s for s in detail["segments"] if not s["metadata"].get("locked")]
    assert translator.post(f"/v1/rhapsody/assignments/{assignment_id}/submit", {}).status_code == 409  # nothing translated yet

    for seg in open_segments:
        saved = translator.put(f"/v1/rhapsody/assignments/{assignment_id}/segments/{seg['id']}", {"target_text": "Texte traduit " + seg["stable_key"]})
        assert saved.status_code == 200, saved.text
    stale = translator.put(f"/v1/rhapsody/assignments/{assignment_id}/segments/{open_segments[0]['id']}",
                           {"target_text": "stale edit", "expected_version_id": "00000000-0000-0000-0000-000000000000"})
    assert stale.status_code == 409
    submitted = translator.post(f"/v1/rhapsody/assignments/{assignment_id}/submit", {})
    assert submitted.status_code == 200, submitted.text

    reviewer = login("rita")
    decision = reviewer.post(f"/v1/rhapsody/assignments/{assignment_id}/review", {"decision": "approved", "note": "Reviewed."})
    assert decision.status_code == 200, decision.text
    assert decision.json()["status"] == "approved"
    assert reviewer.get(f"/v1/rhapsody/assignments/{assignment_id}/export.docx").status_code == 200


def test_translator_starts_translation_and_han_drafts_every_paragraph_for_review(world, login, tmp_path, monkeypatch):
    admin = login("tina")
    edition_id, master_id, _ = _setup_active_master(admin, tmp_path, monkeypatch)
    translator = login("alice")
    assert [e["id"] for e in translator.get("/v1/rhapsody/editions").json()] == [edition_id]

    started = translator.post(f"/v1/rhapsody/editions/{edition_id}/start", {"language": "fr"})
    assert started.status_code == 201, started.text
    assignment_id = started.json()["id"]
    detail = translator.get(f"/v1/rhapsody/assignments/{assignment_id}").json()
    assert detail["draft"]["status"] == "done", detail["draft"]
    assert all(s["target_text"] for s in detail["segments"])
    drafts = [s for s in detail["segments"] if s["origin"] == "ai"]
    assert drafts, "HAN should have drafted the translatable paragraphs"
    assert translator.post(f"/v1/rhapsody/assignments/{assignment_id}/submit", {}).status_code == 409  # unreviewed drafts block submission

    seg = drafts[0]
    confirmed = translator.put(f"/v1/rhapsody/assignments/{assignment_id}/segments/{seg['id']}",
                               {"target_text": seg["target_text"], "expected_version_id": seg["current_version_id"]})
    assert confirmed.status_code == 200 and confirmed.json()["origin"] == "human"
    again = translator.post(f"/v1/rhapsody/editions/{edition_id}/start", {"language": "fr"})
    assert again.json()["id"] == assignment_id and again.json()["created"] is False


def test_han_chat_lays_out_and_starts_rhapsody_translation(world, login, tmp_path, monkeypatch):
    admin = login("tina")
    edition_id = admin.post("/v1/rhapsody/editions", {"month": 11, "year": 2026}).json()["id"]
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "rhapsody_storage_dir", str(tmp_path))
    up = admin.client.post(f"/v1/rhapsody/editions/{edition_id}/sources", files={"file": ("n.docx", NOV, "application/octet-stream")}, headers=admin._h())
    assert up.status_code == 201, up.text

    pid = str(world.projects["p1"].id)
    from app.database import SessionLocal
    from app.models.db import ProjectMember
    with SessionLocal() as db:
        db.add(ProjectMember(project_id=world.projects["p1"].id, user_id=world.users["tina"].id, role="project_manager", can_approve=True))
        db.commit()
    body = {"message": "Han, start the layout of Rhapsody for the month of November 2026 using the word document I uploaded", "project_id": pid}
    reply = admin.post("/v1/chat", body)
    assert reply.status_code == 200, reply.text
    assert "2 of 30 articles" in reply.json()["reply"]
    assert reply.json()["actions"][0]["path"] == f"/rhapsody/editions/{edition_id}"

    translator = login("alice")
    tbody = {"message": "Han, start the translation of Rhapsody in French for the month of November", "project_id": pid}
    assert "No activated English master" in translator.post("/v1/chat", tbody).json()["reply"]
    ed = admin.get(f"/v1/rhapsody/editions/{edition_id}").json()
    admin.post(f"/v1/rhapsody/editions/{edition_id}/activate?master_version_id={ed['master_versions'][0]['id']}", {})
    started = translator.post("/v1/chat", tbody).json()
    assert started["actions"][0]["path"].startswith("/rhapsody/translate/"), started


def test_chat_attachment_creates_edition_and_projectless_conversation_lays_out(world, login, tmp_path, monkeypatch):
    admin = login("tina")
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "rhapsody_storage_dir", str(tmp_path))
    msg = "Han, start the layout of Rhapsody for the month of November 2026 using the word document I uploaded"
    bad = admin.client.post("/v1/rhapsody/chat-attachment", files={"file": ("n.docx", NOV, "application/octet-stream")}, data={"message": "hello"}, headers=admin._h())
    assert bad.status_code == 422
    up = admin.client.post("/v1/rhapsody/chat-attachment", files={"file": ("n.docx", NOV, "application/octet-stream")}, data={"message": msg}, headers=admin._h())
    assert up.status_code == 201, up.text
    conv = admin.post("/v1/conversations", {}).json()["id"]
    reply = admin.post(f"/v1/conversations/{conv}/messages", {"message": msg})
    assert reply.status_code == 200, reply.text
    assert "articles recognised" in reply.json()["reply"]
    assert login("alice").client.post("/v1/rhapsody/chat-attachment", files={"file": ("n.docx", NOV, "application/octet-stream")}, data={"message": msg}, headers=login("alice")._h()).status_code == 403


def test_manuscript_with_running_headers_and_unlabelled_days():
    """Real manuscripts have no "SUNDAY 1" headings: articles are split by the running header ("2  Pastor Chris")."""
    from io import BytesIO

    from docx import Document

    from app.rhapsody_layout import parse_manuscript

    doc = Document()

    def para(text, bold=False, italic=False):
        run = doc.add_paragraph().add_run(text)
        run.bold, run.italic = bold, italic

    for day in (1, 2):
        para("Pastor Chris" if day == 1 else f"{day}\t\t\tPastor Chris", bold=True)
        para("The Power Of “Epignosis”" if day == 1 else "Second Title", bold=True)
        para(f"“Grace and peace be multiplied” (2 Peter 1:{day}).", italic=True)
        para("Body paragraph one.")
        para("Body paragraph two.")
        para("Prayer" if day == 1 else "Confession", bold=True)
        para("Dear Father, thank you. Amen.")
        para("Further Study", bold=True)
        for ref in ("James 4:6", "Romans 5:17"):
            para(ref)
    buf = BytesIO()
    doc.save(buf)
    arts = parse_manuscript(buf.getvalue(), 2026, 11)
    assert [a["day"] for a in arts] == [1, 2]
    assert arts[0]["title"] == "The Power Of “Epignosis”" and arts[0]["scripture_ref"] == "2 Peter 1:1"
    assert len(arts[0]["body"]) == 2 and arts[1]["closing_type"] == "confession"
    assert arts[0]["further"] == "James 4:6; Romans 5:17"
