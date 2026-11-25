"""
NotificationTemplateRenderer — rendu des gabarits par événement × canal × langue.

Ordre de résolution :
  1. NotificationTemplate actif (event_type, channel, language)
  2. NotificationTemplate actif (event_type, channel, "fr")  — langue de repli
  3. Fallback : title/message bruts de la notification

Le rendu utilise le moteur de template Django sur un contexte plat
(les valeurs viennent de Notification.payload + champs standards).
"""

from __future__ import annotations

import logging

from django.template import Context, Template

log = logging.getLogger("lyneci.notifications.renderer")


class NotificationTemplateRenderer:
    @classmethod
    def render(cls, notification, channel: str, language: str = "fr") -> dict:
        """Retourne {"subject": str, "body": str} pour le canal demandé."""
        from notifications.models import NotificationTemplate

        template = (
            NotificationTemplate.objects.filter(
                event_type=notification.event_type,
                channel=channel,
                language=language,
                is_active=True,
            ).first()
            or NotificationTemplate.objects.filter(
                event_type=notification.event_type,
                channel=channel,
                language="fr",
                is_active=True,
            ).first()
        )

        context = {
            "title": notification.title,
            "message": notification.message,
            "severity": notification.severity,
            "priority": notification.priority,
            "event_type": notification.event_type,
            "user": notification.user,
            **(notification.payload or {}),
        }

        if template is None:
            return {"subject": notification.title, "body": notification.message}

        try:
            subject = Template(template.subject or "").render(Context(context)).strip()
            body = Template(template.body).render(Context(context)).strip()
            return {
                "subject": subject or notification.title,
                "body": body or notification.message,
            }
        except Exception:
            log.exception(
                "template.render_failed event=%s channel=%s",
                notification.event_type, channel,
            )
            return {"subject": notification.title, "body": notification.message}
