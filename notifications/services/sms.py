"""
SMSNotificationService — Twilio + fournisseur local Côte d'Ivoire configurable.

Chaîne de providers :
  1. NOTIFY_SMS_PRIMARY ("local_ci" ou "twilio", settings/env)
  2. Fallback Twilio international si le primaire échoue.

Twilio est appelé via son API REST (httpx) — pas de SDK requis.
Le fournisseur local est un POST HTTP générique configurable (URL, clé,
champs) pour brancher n'importe quel agrégateur ivoirien (LeTexto, etc.).
Sans credentials configurés, l'envoi est SKIPPED (journalisé), jamais bloquant.
"""

from __future__ import annotations

import logging

import httpx
from django.conf import settings

from notifications.services.renderer import NotificationTemplateRenderer

log = logging.getLogger("leotrade.notifications.sms")

SMS_MAX_LEN = 320  # 2 segments GSM


def _twilio_send(to: str, body: str) -> dict:
    sid = getattr(settings, "TWILIO_ACCOUNT_SID", "")
    token = getattr(settings, "TWILIO_AUTH_TOKEN", "")
    from_number = getattr(settings, "TWILIO_SMS_FROM", "")
    if not (sid and token and from_number):
        return {"ok": False, "skipped": True, "provider": "twilio",
                "response": {}, "error": "Twilio non configuré (TWILIO_ACCOUNT_SID/AUTH_TOKEN/SMS_FROM)."}
    try:
        resp = httpx.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            data={"To": to, "From": from_number, "Body": body},
            auth=(sid, token),
            timeout=15.0,
        )
        data = resp.json() if resp.content else {}
        ok = resp.status_code in (200, 201)
        return {
            "ok": ok, "skipped": False, "provider": "twilio",
            "response": {"sid": data.get("sid"), "status": data.get("status"),
                         "http_status": resp.status_code},
            "error": "" if ok else str(data.get("message", resp.text))[:500],
        }
    except Exception as exc:
        return {"ok": False, "skipped": False, "provider": "twilio",
                "response": {}, "error": str(exc)[:500]}


def _local_ci_send(to: str, body: str) -> dict:
    """Agrégateur SMS local (Côte d'Ivoire) — POST HTTP générique."""
    url = getattr(settings, "SMS_LOCAL_CI_URL", "")
    api_key = getattr(settings, "SMS_LOCAL_CI_API_KEY", "")
    sender = getattr(settings, "SMS_LOCAL_CI_SENDER", "LeoTrade")
    if not (url and api_key):
        return {"ok": False, "skipped": True, "provider": "local_ci",
                "response": {}, "error": "Fournisseur SMS local non configuré (SMS_LOCAL_CI_URL/API_KEY)."}
    try:
        resp = httpx.post(
            url,
            json={"to": to, "from": sender, "message": body},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15.0,
        )
        ok = 200 <= resp.status_code < 300
        return {
            "ok": ok, "skipped": False, "provider": "local_ci",
            "response": {"http_status": resp.status_code, "body": resp.text[:500]},
            "error": "" if ok else resp.text[:500],
        }
    except Exception as exc:
        return {"ok": False, "skipped": False, "provider": "local_ci",
                "response": {}, "error": str(exc)[:500]}


class SMSNotificationService:
    provider = "twilio/local_ci"

    @classmethod
    def send(cls, notification, language: str = "fr") -> dict:
        pref = getattr(notification.user, "notification_preference", None)
        recipient = (getattr(pref, "phone_number", "") or "").strip()
        if not recipient:
            return {"ok": False, "skipped": True, "recipient": "", "provider": cls.provider,
                    "response": {}, "error": "Pas de numéro de téléphone configuré."}

        rendered = NotificationTemplateRenderer.render(notification, "SMS", language)
        body = f"LeoTrade — {rendered['subject']}\n{rendered['body']}"[:SMS_MAX_LEN]

        primary = getattr(settings, "NOTIFY_SMS_PRIMARY", "twilio")
        chain = [_local_ci_send, _twilio_send] if primary == "local_ci" else [_twilio_send, _local_ci_send]

        last = {"ok": False, "skipped": True, "provider": "", "response": {}, "error": "Aucun provider SMS configuré."}
        for sender in chain:
            result = sender(recipient, body)
            if result["ok"]:
                return {**result, "recipient": recipient}
            # Provider non configuré → essaie le suivant sans bruit ;
            # vrai échec → log + fallback.
            if not result.get("skipped"):
                log.warning("sms.provider_failed provider=%s err=%s", result["provider"], result["error"])
            last = result

        return {**last, "recipient": recipient}
