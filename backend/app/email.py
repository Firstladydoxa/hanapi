"""Transactional email delivery through Brevo. Secrets are read only from server env."""
from __future__ import annotations

import logging
from html import escape
from typing import Optional

import httpx

from .config import get_settings

log = logging.getLogger("han.email")
BREVO_URL = "https://api.brevo.com/v3/smtp/email"


def send_email(to_email: str, subject: str, html: str, text: str) -> bool:
    settings = get_settings()
    if not settings.brevo_api_key or not settings.brevo_sender_email:
        log.warning("email_delivery_not_configured")
        return False
    payload = {
        "sender": {"email": settings.brevo_sender_email, "name": settings.brevo_sender_name},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html,
        "textContent": text,
    }
    try:
        response = httpx.post(BREVO_URL, headers={"api-key": settings.brevo_api_key, "accept": "application/json",
            "content-type": "application/json"}, json=payload, timeout=12.0)
        response.raise_for_status()
        return True
    except (httpx.HTTPError, ValueError):
        log.exception("transactional_email_delivery_failed")
        return False


def send_code(to_email: str, name: str, code: str, purpose: str, minutes: int) -> bool:
    if purpose == "verify_email":
        subject, heading, intro = "Verify your HAN email address", "Complete your HAN registration", "Enter this verification code to confirm your email address:"
    else:
        subject, heading, intro = "Your HAN password reset code", "Reset your HAN password", "Enter this code to continue resetting your password:"
    safe_name = escape(name)
    html = f"<div style='font-family:Arial,sans-serif;max-width:560px;margin:auto;color:#17152a'><h2>{heading}</h2><p>Hello {safe_name},</p><p>{intro}</p><p style='font-size:32px;font-weight:700;letter-spacing:9px;padding:18px;background:#f4f0ff;text-align:center'>{code}</p><p>This code expires in {minutes} minutes and can only be used once. If you did not request this, you can ignore this email.</p><p>TNI · HAN</p></div>"
    text = f"Hello {name},\n\n{intro}\n\n{code}\n\nThis code expires in {minutes} minutes and can only be used once. If you did not request this, ignore this email."
    return send_email(to_email, subject, html, text)


def send_registration_reminder(to_email: str, name: str, link: str) -> bool:
    subject = "Finish creating your HAN account"
    safe_name = escape(name)
    safe_link = escape(link, quote=True)
    html = f"<div style='font-family:Arial,sans-serif;max-width:560px;margin:auto;color:#17152a'><h2>Your HAN registration is waiting</h2><p>Hello {safe_name},</p><p>Your email address has not yet been verified. Continue your registration using the secure link below.</p><p><a href='{safe_link}' style='display:inline-block;padding:12px 20px;background:#6d4aff;color:white;text-decoration:none;border-radius:8px'>Complete registration</a></p><p>The link expires in 7 days. You can request a fresh verification code from the sign-in page.</p><p>If you did not start this registration, you can ignore this email.</p><p>TNI · HAN</p></div>"
    text = f"Hello {name},\n\nYour HAN registration is incomplete. Complete it here: {link}\n\nThe link expires in 7 days. If you did not start this registration, ignore this email."
    return send_email(to_email, subject, html, text)
