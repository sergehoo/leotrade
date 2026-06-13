"""
Tâches Celery du chat persistant.

mark_stale_partials_task : si le serveur redémarre PENDANT une génération,
le message reste en PARTIAL avec son contenu progressif sauvegardé. Cette
tâche bascule en FAILED les PARTIAL sans mise à jour depuis 10 minutes —
le contenu déjà généré est conservé, le statut devient honnête.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

log = logging.getLogger("leotrade.ai_assistant.tasks")

STALE_PARTIAL_MINUTES = 10


@shared_task(name="ai_assistant.tasks.mark_stale_partials_task")
def mark_stale_partials_task():
    from .models import AssistantMessage

    cutoff = timezone.now() - timedelta(minutes=STALE_PARTIAL_MINUTES)
    stale = AssistantMessage.objects.filter(
        role="ASSISTANT",
        status=AssistantMessage.STATUS_PARTIAL,
        updated_at__lt=cutoff,
    )
    updated = stale.update(
        status=AssistantMessage.STATUS_FAILED,
        error_message="generation_interrupted_by_restart",
    )
    if updated:
        log.warning("assistant.stale_partials_marked count=%s", updated)
    return {"marked_failed": updated}
