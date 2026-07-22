"""
Unified alerting for Lyneci.

Provides a single ``send_alert`` API that routes to all enabled channels
(Email, Telegram, Slack-compatible webhook). Each channel is best-effort —
a failure on Telegram does not block Email and vice versa.

Channels are configured via environment variables (read at runtime so
tests can override them):

- ``ALERT_EMAIL_TO``                       → comma-separated list
- ``ALERT_TELEGRAM_BOT_TOKEN`` + ``ALERT_TELEGRAM_CHAT_ID``
- ``ALERT_WEBHOOK_URL``                    → POSTs JSON ``{level, title, message, payload}``

The function is safe to call from views, Celery tasks, signal handlers.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Iterable, Optional

logger = logging.getLogger(__name__)


def _enabled_channels() -> dict[str, bool]:
    return {
        "email": bool(os.environ.get("ALERT_EMAIL_TO")),
        "telegram": bool(
            os.environ.get("ALERT_TELEGRAM_BOT_TOKEN")
            and os.environ.get("ALERT_TELEGRAM_CHAT_ID")
        ),
        "webhook": bool(os.environ.get("ALERT_WEBHOOK_URL")),
    }


def _send_email(level: str, title: str, message: str, payload: dict) -> bool:
    try:
        from django.core.mail import send_mail
        from django.conf import settings

        recipients = [r.strip() for r in os.environ["ALERT_EMAIL_TO"].split(",") if r.strip()]
        if not recipients:
            return False
        body = f"{message}\n\nPayload:\n{json.dumps(payload, indent=2, default=str)}"
        send_mail(
            subject=f"[Lyneci {level}] {title}",
            message=body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@lyneci.local"),
            recipient_list=recipients,
            fail_silently=False,
        )
        return True
    except Exception:
        logger.exception("Email alert failed")
        return False


def _send_telegram(level: str, title: str, message: str, payload: dict) -> bool:
    try:
        import httpx

        token = os.environ["ALERT_TELEGRAM_BOT_TOKEN"]
        chat_id = os.environ["ALERT_TELEGRAM_CHAT_ID"]
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        text = (
            f"*[{level}] {title}*\n"
            f"{message}\n"
            f"```\n{json.dumps(payload, indent=2, default=str)[:1500]}\n```"
        )
        with httpx.Client(timeout=10) as client:
            r = client.post(
                url,
                json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            )
            r.raise_for_status()
        return True
    except Exception:
        logger.exception("Telegram alert failed")
        return False


def _send_webhook(level: str, title: str, message: str, payload: dict) -> bool:
    try:
        import httpx

        url = os.environ["ALERT_WEBHOOK_URL"]
        with httpx.Client(timeout=10) as client:
            r = client.post(
                url,
                json={
                    "level": level,
                    "title": title,
                    "message": message,
                    "payload": payload,
                },
            )
            r.raise_for_status()
        return True
    except Exception:
        logger.exception("Webhook alert failed")
        return False


def send_alert(
    *,
    title: str,
    message: str,
    level: str = "INFO",
    payload: Optional[dict] = None,
    channels: Optional[Iterable[str]] = None,
) -> dict[str, bool]:
    """
    Send an alert to all configured channels.

    Args:
        title: short header.
        message: human-readable body.
        level: ``INFO`` / ``WARNING`` / ``ERROR`` / ``CRITICAL``.
        payload: structured context attached to the alert.
        channels: optional iterable to restrict (e.g. ``["telegram"]``).

    Returns:
        Dict of channel → success bool.
    """
    payload = payload or {}
    enabled = _enabled_channels()
    if channels is not None:
        wanted = set(channels)
        enabled = {k: (v and k in wanted) for k, v in enabled.items()}

    results = {}
    if enabled.get("email"):
        results["email"] = _send_email(level, title, message, payload)
    if enabled.get("telegram"):
        results["telegram"] = _send_telegram(level, title, message, payload)
    if enabled.get("webhook"):
        results["webhook"] = _send_webhook(level, title, message, payload)

    if not results:
        logger.info(
            "send_alert: no channel configured for title=%s level=%s",
            title,
            level,
        )

    return results
