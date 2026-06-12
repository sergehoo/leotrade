"""
EmailNotificationService — canal prioritaire.

Backend : django.core.mail (SMTP configuré par EMAIL_BACKEND/EMAIL_HOST…).
Le passage futur à SendGrid / Mailgun / SES se fait par EMAIL_BACKEND sans
toucher ce service (backends django-anymail compatibles).
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from notifications.services.renderer import NotificationTemplateRenderer

log = logging.getLogger("leotrade.notifications.email")


class EmailNotificationService:
    provider = "django-smtp"

    @classmethod
    def send(cls, notification, language: str = "fr") -> dict:
        """Envoie l'email. Retourne {"ok", "recipient", "provider", "response", "error"}."""
        recipient = (notification.user.email or "").strip()
        if not recipient:
            return {
                "ok": False, "recipient": "", "provider": cls.provider,
                "response": {}, "error": "Utilisateur sans adresse email.",
            }

        rendered = NotificationTemplateRenderer.render(notification, "EMAIL", language)
        subject = f"[LeoTrade] {rendered['subject']}"

        html_body = render_to_string("notifications/email/notification.html", {
            "notification": notification,
            "subject": rendered["subject"],
            "body": rendered["body"],
            "severity": notification.severity,
            "site_url": getattr(settings, "SITE_URL", ""),
        })
        text_body = render_to_string("notifications/email/notification.txt", {
            "subject": rendered["subject"],
            "body": rendered["body"],
            "severity": notification.severity,
            "site_url": getattr(settings, "SITE_URL", ""),
        })

        try:
            email = EmailMultiAlternatives(
                subject=subject,
                body=text_body,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                to=[recipient],
            )
            email.attach_alternative(html_body, "text/html")
            email.send(fail_silently=False)
            return {
                "ok": True, "recipient": recipient, "provider": cls.provider,
                "response": {"subject": subject}, "error": "",
            }
        except Exception as exc:
            log.warning("email.send_failed notification_id=%s err=%s", notification.id, exc)
            return {
                "ok": False, "recipient": recipient, "provider": cls.provider,
                "response": {}, "error": str(exc)[:1000],
            }
