"""
WhatsAppNotificationService — Twilio WhatsApp, WhatsApp Business Cloud API en option.

Provider primaire : NOTIFY_WHATSAPP_PRIMARY ("twilio" par défaut, "cloud_api"
pour Meta WhatsApp Business Cloud). Sans credentials, l'envoi est SKIPPED
(journalisé), jamais bloquant pour le flux de trading.
"""

from __future__ import annotations

import logging

import httpx
from django.conf import settings

from notifications.services.renderer import NotificationTemplateRenderer

log = logging.getLogger("lyneci.notifications.whatsapp")


def _twilio_whatsapp_send(to: str, body: str) -> dict:
    sid = getattr(settings, "TWILIO_ACCOUNT_SID", "")
    token = getattr(settings, "TWILIO_AUTH_TOKEN", "")
    from_number = getattr(settings, "TWILIO_WHATSAPP_FROM", "")
    if not (sid and token and from_number):
        return {"ok": False, "skipped": True, "provider": "twilio_whatsapp",
                "response": {}, "error": "Twilio WhatsApp non configuré (TWILIO_WHATSAPP_FROM)."}
    try:
        resp = httpx.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            data={
                "To": f"whatsapp:{to}",
                "From": f"whatsapp:{from_number}",
                "Body": body,
            },
            auth=(sid, token),
            timeout=15.0,
        )
        data = resp.json() if resp.content else {}
        ok = resp.status_code in (200, 201)
        return {
            "ok": ok, "skipped": False, "provider": "twilio_whatsapp",
            "response": {"sid": data.get("sid"), "status": data.get("status"),
                         "http_status": resp.status_code},
            "error": "" if ok else str(data.get("message", resp.text))[:500],
        }
    except Exception as exc:
        return {"ok": False, "skipped": False, "provider": "twilio_whatsapp",
                "response": {}, "error": str(exc)[:500]}


def _cloud_api_send(to: str, body: str) -> dict:
    """WhatsApp Business Cloud API (Meta Graph)."""
    token = getattr(settings, "WHATSAPP_CLOUD_TOKEN", "")
    phone_id = getattr(settings, "WHATSAPP_CLOUD_PHONE_ID", "")
    if not (token and phone_id):
        return {"ok": False, "skipped": True, "provider": "whatsapp_cloud",
                "response": {}, "error": "WhatsApp Cloud API non configurée (WHATSAPP_CLOUD_TOKEN/PHONE_ID)."}
    try:
        resp = httpx.post(
            f"https://graph.facebook.com/v19.0/{phone_id}/messages",
            json={
                "messaging_product": "whatsapp",
                "to": to.lstrip("+"),
                "type": "text",
                "text": {"body": body},
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=15.0,
        )
        ok = 200 <= resp.status_code < 300
        return {
            "ok": ok, "skipped": False, "provider": "whatsapp_cloud",
            "response": {"http_status": resp.status_code, "body": resp.text[:500]},
            "error": "" if ok else resp.text[:500],
        }
    except Exception as exc:
        return {"ok": False, "skipped": False, "provider": "whatsapp_cloud",
                "response": {}, "error": str(exc)[:500]}


class WhatsAppNotificationService:
    provider = "twilio_whatsapp/cloud_api"

    @classmethod
    def send(cls, notification, language: str = "fr") -> dict:
        pref = getattr(notification.user, "notification_preference", None)
        recipient = (
            (getattr(pref, "whatsapp_number", "") or getattr(pref, "phone_number", "") or "")
        ).strip()
        if not recipient:
            return {"ok": False, "skipped": True, "recipient": "", "provider": cls.provider,
                    "response": {}, "error": "Pas de numéro WhatsApp configuré."}

        rendered = NotificationTemplateRenderer.render(notification, "WHATSAPP", language)
        body = f"*Lyneci — {rendered['subject']}*\n{rendered['body']}"[:1500]

        primary = getattr(settings, "NOTIFY_WHATSAPP_PRIMARY", "twilio")
        chain = (
            [_cloud_api_send, _twilio_whatsapp_send]
            if primary == "cloud_api"
            else [_twilio_whatsapp_send, _cloud_api_send]
        )

        last = {"ok": False, "skipped": True, "provider": "", "response": {},
                "error": "Aucun provider WhatsApp configuré."}
        for sender in chain:
            result = sender(recipient, body)
            if result["ok"]:
                return {**result, "recipient": recipient}
            if not result.get("skipped"):
                log.warning("whatsapp.provider_failed provider=%s err=%s",
                            result["provider"], result["error"])
            last = result

        return {**last, "recipient": recipient}
