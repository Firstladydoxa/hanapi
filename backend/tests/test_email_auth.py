from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import email as mail
from app.database import SessionLocal
from app.models.db import EmailAuthChallenge, User
from app.security import auth as sec


def test_registration_requires_email_verification_and_code_is_single_use(anon, monkeypatch):
    sent = []
    monkeypatch.setattr(mail, "send_code", lambda email, name, code, purpose, minutes: sent.append((email, code, purpose)) or True)
    r = anon.post("/v1/auth/register", {"email": "new@example.test", "display_name": "New User", "password": "correct-horse-battery-staple", "expertise_language": "fr"})
    assert r.status_code == 202, r.text
    assert sent[0][2] == "verify_email"
    login = anon.post("/v1/auth/login", {"email": "new@example.test", "password": "correct-horse-battery-staple"}, csrf=False)
    assert login.status_code == 403
    assert login.json()["detail"]["code"] == "email_not_verified"
    assert len(sent) == 1  # the live code is inside the resend cooldown, so no second email is sent
    verified = anon.post("/v1/auth/verify-email", {"email": "new@example.test", "code": sent[-1][1]}, csrf=False)
    assert verified.status_code == 200, verified.text
    replay = anon.post("/v1/auth/verify-email", {"email": "new@example.test", "code": sent[-1][1]}, csrf=False)
    assert replay.status_code == 400
    login2 = anon.post("/v1/auth/login", {"email": "new@example.test", "password": "correct-horse-battery-staple"}, csrf=False)
    assert login2.status_code == 200


def test_password_reset_revokes_existing_sessions(anon, world, monkeypatch):
    sent = []
    monkeypatch.setattr(mail, "send_code", lambda email, name, code, purpose, minutes: sent.append((code, purpose)) or True)
    login = anon.post("/v1/auth/login", {"email": "alice@example.test", "password": "correct-horse-battery-staple"}, csrf=False)
    assert login.status_code == 200
    requested = anon.post("/v1/auth/password-reset/request", {"email": "alice@example.test"}, csrf=False)
    assert requested.status_code == 200
    assert sent[0][1] == "reset_password"
    reset = anon.post("/v1/auth/password-reset/confirm", {"email": "alice@example.test", "code": sent[0][0], "new_password": "a-new-correct-horse-battery"}, csrf=False)
    assert reset.status_code == 200, reset.text
    old_login = anon.post("/v1/auth/login", {"email": "alice@example.test", "password": "correct-horse-battery-staple"}, csrf=False)
    assert old_login.status_code == 401
    new_login = anon.post("/v1/auth/login", {"email": "alice@example.test", "password": "a-new-correct-horse-battery"}, csrf=False)
    assert new_login.status_code == 200


def test_wrong_code_is_limited_and_resend_invalidates_previous_code(anon, monkeypatch):
    sent = []
    monkeypatch.setattr(mail, "send_code", lambda email, name, code, purpose, minutes: sent.append(code) or True)
    anon.post("/v1/auth/register", {"email": "codes@example.test", "display_name": "Codes", "password": "correct-horse-battery-staple", "expertise_language": "fr"})
    with SessionLocal() as db:
        user = db.query(User).filter_by(email="codes@example.test").one()
        challenge = db.query(EmailAuthChallenge).filter_by(user_id=user.id).one()
        challenge.created_at = datetime.now(timezone.utc) - timedelta(minutes=2)
        db.commit()
    resent = anon.post("/v1/auth/resend-verification", {"email": "codes@example.test"}, csrf=False)
    assert resent.status_code == 200
    assert len(sent) == 2
    old = anon.post("/v1/auth/verify-email", {"email": "codes@example.test", "code": sent[0]}, csrf=False)
    assert old.status_code == 400
    new = anon.post("/v1/auth/verify-email", {"email": "codes@example.test", "code": sent[1]}, csrf=False)
    assert new.status_code == 200


def test_due_incomplete_registration_reminder_sends_recovery_link(anon, monkeypatch):
    from app.api.auth import send_due_registration_reminders
    from app.models.db import RegistrationReminder
    links = []
    monkeypatch.setattr(mail, "send_code", lambda *args: True)
    monkeypatch.setattr(mail, "send_registration_reminder", lambda email, name, link: links.append(link) or True)
    anon.post("/v1/auth/register", {"email": "reminder@example.test", "display_name": "Reminder", "password": "correct-horse-battery-staple", "expertise_language": "fr"})
    with SessionLocal() as db:
        reminder = db.query(RegistrationReminder).filter(RegistrationReminder.sent_at.is_(None)).one()
        reminder.due_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
        assert send_due_registration_reminders(db) == 1
    assert len(links) == 1
    assert "/verify-email?recovery=" in links[0]
    response = anon.post("/v1/auth/registration/recovery-link", {"token": links[0].split("recovery=")[1]}, csrf=False)
    assert response.status_code == 200


def test_login_of_unverified_account_sends_fresh_code_after_cooldown(anon, monkeypatch):
    sent = []
    monkeypatch.setattr(mail, "send_code", lambda email, name, code, purpose, minutes: sent.append(code) or True)
    anon.post("/v1/auth/register", {"email": "late@example.test", "display_name": "Late", "password": "correct-horse-battery-staple", "expertise_language": "fr"})
    with SessionLocal() as db:
        user = db.query(User).filter_by(email="late@example.test").one()
        db.query(EmailAuthChallenge).filter_by(user_id=user.id).update({"created_at": datetime.now(timezone.utc) - timedelta(minutes=5)})
        db.commit()
    login = anon.post("/v1/auth/login", {"email": "late@example.test", "password": "correct-horse-battery-staple"}, csrf=False)
    assert login.status_code == 403 and login.json()["detail"]["code"] == "email_not_verified"
    assert len(sent) == 2
    wrong_pw = anon.post("/v1/auth/login", {"email": "late@example.test", "password": "wrong-password-entirely"}, csrf=False)
    assert wrong_pw.status_code == 401 and len(sent) == 2  # no code without the right password


def test_reregistering_unverified_email_restarts_registration(anon, monkeypatch):
    sent = []
    monkeypatch.setattr(mail, "send_code", lambda email, name, code, purpose, minutes: sent.append(code) or True)
    body = {"email": "again@example.test", "display_name": "Again", "password": "correct-horse-battery-staple", "expertise_language": "fr"}
    assert anon.post("/v1/auth/register", body).status_code == 202
    again = anon.post("/v1/auth/register", {**body, "password": "another-long-password-1"})
    assert again.status_code == 202 and len(sent) == 2
    assert anon.post("/v1/auth/verify-email", {"email": body["email"], "code": sent[0]}, csrf=False).status_code == 400
    assert anon.post("/v1/auth/verify-email", {"email": body["email"], "code": sent[1]}, csrf=False).status_code == 200
    assert anon.post("/v1/auth/login", {"email": body["email"], "password": "another-long-password-1"}, csrf=False).status_code == 200


def test_expired_code_is_rejected(anon, monkeypatch):
    sent = []
    monkeypatch.setattr(mail, "send_code", lambda email, name, code, purpose, minutes: sent.append(code) or True)
    anon.post("/v1/auth/register", {"email": "exp@example.test", "display_name": "Exp", "password": "correct-horse-battery-staple", "expertise_language": "fr"})
    with SessionLocal() as db:
        db.query(EmailAuthChallenge).update({"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)})
        db.commit()
    assert anon.post("/v1/auth/verify-email", {"email": "exp@example.test", "code": sent[0]}, csrf=False).status_code == 400
