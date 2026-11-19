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


def test_rhapsody_full_admin_to_translator_to_review_flow(world, login, tmp_path, monkeypatch):
    from app.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "rhapsody_storage_dir", str(tmp_path))

    admin = login("tina")
    created = admin.post("/v1/rhapsody/editions", {"month": 11, "year": 2026})
    assert created.status_code == 201, created.text
    edition_id = created.json()["id"]

    doc = Document()
    doc.add_heading("Day 1", level=1)
    doc.add_paragraph("Christ is our life.")
    stream = BytesIO()
    doc.save(stream)
    uploaded = admin.client.post(
        f"/v1/rhapsody/editions/{edition_id}/sources",
        files={"file": ("november.docx", stream.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        headers=admin._h(),
    )
    assert uploaded.status_code == 201, uploaded.text
    source_id = uploaded.json()["id"]

    ingested = admin.client.post(
        f"/v1/rhapsody/editions/{edition_id}/ingest",
        data={"source_file_id": source_id},
        headers=admin._h(),
    )
    assert ingested.status_code == 200, ingested.text
    master_id = ingested.json()["master_version_id"]

    activated = admin.post(f"/v1/rhapsody/editions/{edition_id}/activate?master_version_id={master_id}", {})
    assert activated.status_code == 200, activated.text

    assigned = admin.post("/v1/rhapsody/assignments", {
        "master_version_id": master_id,
        "target_language": "fr",
        "translator_id": str(world.users["alice"].id),
        "reviewer_id": str(world.users["rita"].id),
    })
    assert assigned.status_code == 201, assigned.text
    assignment_id = assigned.json()["id"]

    translator = login("alice")
    detail = translator.get(f"/v1/rhapsody/assignments/{assignment_id}")
    assert detail.status_code == 200, detail.text
    segment = detail.json()["segments"][0]
    saved = translator.put(
        f"/v1/rhapsody/assignments/{assignment_id}/segments/{segment['id']}",
        {"target_text": "Christ est notre vie."},
    )
    assert saved.status_code == 200, saved.text
    stale = translator.put(
        f"/v1/rhapsody/assignments/{assignment_id}/segments/{segment['id']}",
        {"target_text": "stale edit", "expected_version_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert stale.status_code == 409
    submitted = translator.post(f"/v1/rhapsody/assignments/{assignment_id}/submit", {})
    assert submitted.status_code == 200, submitted.text

    reviewer = login("rita")
    decision = reviewer.post(f"/v1/rhapsody/assignments/{assignment_id}/review", {"decision": "approved", "note": "Reviewed."})
    assert decision.status_code == 200, decision.text
    assert decision.json()["status"] == "approved"
