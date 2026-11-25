"""
Centre de notifications web (templates Django + Alpine, cohérent avec
le reste de la plateforme ; l'API DRF sert le polling/temps réel).
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import redirect, render

from .events import EVENT_CHOICES, Priority, Severity
from .models import Notification
from .services import NotificationPreferenceService, NotificationService


@login_required
def notification_center(request):
    qs = Notification.objects.filter(user=request.user)

    event_type = request.GET.get("event_type", "")
    severity = request.GET.get("severity", "")
    unread_only = request.GET.get("unread") == "1"

    if event_type:
        qs = qs.filter(event_type=event_type)
    if severity:
        qs = qs.filter(severity=severity)
    if unread_only:
        qs = qs.filter(read_at__isnull=True)

    paginator = Paginator(qs.order_by("-created_at"), 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "notifications/center.html", {
        "page_obj": page_obj,
        "notifications": page_obj.object_list,
        "unread_count": NotificationService.unread_count(request.user),
        "event_choices": EVENT_CHOICES,
        "severity_choices": Severity.CHOICES,
        "priority_choices": Priority.CHOICES,
        "current_event_type": event_type,
        "current_severity": severity,
        "unread_only": unread_only,
    })


@login_required
def notification_preferences(request):
    pref = NotificationPreferenceService.get_or_create(request.user)

    if request.method == "POST":
        bool_fields = [
            "email_enabled", "in_app_enabled", "sms_enabled", "whatsapp_enabled",
            "trade_events_enabled", "risk_events_enabled", "broker_events_enabled",
            "ai_events_enabled", "security_events_enabled", "reports_enabled",
        ]
        for field in bool_fields:
            setattr(pref, field, request.POST.get(field) == "on")

        pref.preferred_language = request.POST.get("preferred_language", "fr")[:5]
        pref.phone_number = request.POST.get("phone_number", "").strip()[:30]
        pref.whatsapp_number = request.POST.get("whatsapp_number", "").strip()[:30]

        for field in ("quiet_hours_start", "quiet_hours_end"):
            raw = request.POST.get(field, "").strip()
            setattr(pref, field, raw or None)

        try:
            pref.save()
            messages.success(request, "Préférences de notification enregistrées.")
        except Exception:
            messages.error(request, "Format d'heure invalide pour les quiet hours (HH:MM).")
        return redirect("notifications:preferences")

    return render(request, "notifications/preferences.html", {"pref": pref})
