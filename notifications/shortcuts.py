"""
Raccourci d'intégration pour les autres apps.

    from notifications.shortcuts import notify

    notify(user, "ORDER_FILLED",
           title="Ordre exécuté : BUY R_75",
           message="10 lots à 1 234,56 $.",
           payload={"order_id": order.id})

`notify` est volontairement tolérant : import différé, jamais d'exception,
appel possible depuis les services, vues, tâches et signaux sans risque
de casser le flux métier (règle : un trade ne rate jamais à cause d'une notif).
"""

from __future__ import annotations

import logging

log = logging.getLogger("lyneci.notifications")


def notify(user, event_type: str, **kwargs):
    """Wrapper sûr autour de NotificationService.notify."""
    try:
        from notifications.services import NotificationService
        return NotificationService.notify(user, event_type, **kwargs)
    except Exception:
        log.exception("notifications.shortcut_failed event=%s", event_type)
        return None


def notify_admins(event_type: str, **kwargs):
    """Notifie tous les superusers actifs (erreurs système, sécurité)."""
    try:
        from django.contrib.auth import get_user_model

        admins = get_user_model().objects.filter(is_superuser=True, is_active=True)
        return [notify(a, event_type, **kwargs) for a in admins]
    except Exception:
        log.exception("notifications.notify_admins_failed event=%s", event_type)
        return []
