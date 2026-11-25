"""
NotificationPreferenceService — résolution des canaux effectifs.

Règles de priorité (cahier des charges) :
  - Email = canal prioritaire pour toute notification importante.
  - Critique → email + in-app + SMS + WhatsApp si le profil l'autorise.
  - Non critique → email + in-app.
  - Quiet hours : les canaux intrusifs (email, SMS, WhatsApp) sont coupés
    pour les notifications non critiques ; l'in-app reste toujours actif.
  - Les événements critiques ignorent les quiet hours.
"""

from __future__ import annotations

from notifications.events import (
    CATEGORY_PREFERENCE_FIELD,
    Channel,
    Priority,
    get_event,
)


class NotificationPreferenceService:
    @staticmethod
    def get_or_create(user):
        from notifications.models import NotificationPreference

        pref, _ = NotificationPreference.objects.get_or_create(user=user)
        return pref

    @classmethod
    def category_enabled(cls, pref, event_code: str) -> bool:
        spec = get_event(event_code)
        field = CATEGORY_PREFERENCE_FIELD.get(spec.category, "trade_events_enabled")
        return bool(getattr(pref, field, True))

    @classmethod
    def resolve_channels(
        cls,
        user,
        event_code: str,
        priority: str,
        requested: list[str] | None = None,
    ) -> tuple[list[str], str]:
        """
        Retourne (canaux effectifs, raison de suppression éventuelle).

        raison ∈ {"", "category_disabled"} — les canaux individuellement
        filtrés (préférence, quiet hours) sont simplement retirés de la liste.
        """
        spec = get_event(event_code)
        pref = cls.get_or_create(user)

        # Catégorie désactivée → rien (sauf critique : on garde in-app + email,
        # un kill switch ou une alerte sécurité ne doit jamais passer inaperçu)
        if not cls.category_enabled(pref, event_code):
            if spec.critical:
                base = [Channel.IN_APP, Channel.EMAIL]
                return [c for c in base if pref.channel_allowed(c)], ""
            return [], "category_disabled"

        # Canaux demandés par défaut selon la criticité
        if requested:
            candidates = list(requested)
        elif spec.critical or priority == Priority.URGENT:
            candidates = [Channel.EMAIL, Channel.IN_APP, Channel.SMS, Channel.WHATSAPP]
        elif Priority.ORDER.get(priority, 1) >= Priority.ORDER[Priority.HIGH]:
            candidates = [Channel.EMAIL, Channel.IN_APP]
        else:
            candidates = [Channel.EMAIL, Channel.IN_APP]

        # Filtre par préférences de canal
        channels = [c for c in candidates if pref.channel_allowed(c)]

        # Quiet hours : on ne garde que l'in-app pour le non-critique
        if not spec.critical and pref.in_quiet_hours():
            channels = [c for c in channels if c == Channel.IN_APP]

        # Email en tête (canal prioritaire), in-app ensuite, le reste après
        order = {Channel.EMAIL: 0, Channel.IN_APP: 1, Channel.SMS: 2, Channel.WHATSAPP: 3}
        channels.sort(key=lambda c: order.get(c, 9))
        return channels, ""
