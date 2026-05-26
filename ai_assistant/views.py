"""
ai_assistant/views.py
=====================

Endpoints HTTP du panel IA.

GET  /assistant/session/          → info session active + historique
POST /assistant/action/<id>/confirm/  → confirmer une action proposée
POST /assistant/action/<id>/reject/   → rejeter une action proposée
GET  /assistant/actions/pending/  → liste des actions en attente
"""
from __future__ import annotations

import json
import logging

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import AssistantSession, AssistantMessage, AssistantAction, AIUserQuota, AIQuotaPayment
from .services import QuotaService

log = logging.getLogger("leotrade.ai_assistant")


class AssistantSessionView(LoginRequiredMixin, View):
    """Retourne la session active + les N derniers messages."""

    def get(self, request):
        session = (
            AssistantSession.objects
            .filter(user=request.user, is_active=True)
            .order_by("-updated_at")
            .first()
        )
        if not session:
            return JsonResponse({"session": None, "messages": []})

        messages = list(
            session.messages
            .order_by("-created_at")[:20]
        )
        return JsonResponse({
            "session": {
                "id": session.id,
                "page_context": session.page_context,
                "created_at": session.created_at.isoformat(),
            },
            "messages": [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "created_at": m.created_at.isoformat(),
                    "actions": [
                        {
                            "id": a.id,
                            "type": a.action_type,
                            "status": a.status,
                            "params": a.parameters,
                            "rationale": a.rationale,
                        }
                        for a in m.actions.all()
                    ] if m.role == "ASSISTANT" else [],
                }
                for m in reversed(messages)
            ],
        })


class ActionConfirmView(LoginRequiredMixin, View):
    def post(self, request, pk):
        action = AssistantAction.objects.filter(
            pk=pk,
            message__session__user=request.user,
            status=AssistantAction.STATUS_PROPOSED,
        ).first()
        if not action:
            return JsonResponse({"error": "Action introuvable ou déjà traitée."}, status=404)

        action.confirm()

        result: dict = {}
        if action.action_type == AssistantAction.TYPE_DRAFT_ORDER:
            result = {"redirect": "draft_order", "params": action.parameters}
            action.mark_executed(result)

        return JsonResponse({"status": "confirmed", "result": result})


class ActionRejectView(LoginRequiredMixin, View):
    def post(self, request, pk):
        action = AssistantAction.objects.filter(
            pk=pk,
            message__session__user=request.user,
            status=AssistantAction.STATUS_PROPOSED,
        ).first()
        if not action:
            return JsonResponse({"error": "Action introuvable ou déjà traitée."}, status=404)

        action.reject()
        return JsonResponse({"status": "rejected"})


class PendingActionsView(LoginRequiredMixin, View):
    def get(self, request):
        actions = (
            AssistantAction.objects
            .filter(
                message__session__user=request.user,
                status=AssistantAction.STATUS_PROPOSED,
            )
            .select_related("message")
            .order_by("-created_at")[:10]
        )
        return JsonResponse({
            "actions": [
                {
                    "id": a.id,
                    "type": a.action_type,
                    "params": a.parameters,
                    "rationale": a.rationale,
                    "created_at": a.created_at.isoformat(),
                }
                for a in actions
            ]
        })


# ── Quota views ────────────────────────────────────────────────────────────────

class QuotaStatusView(LoginRequiredMixin, View):
    """GET /assistant/quota/ — état du quota courant."""
    def get(self, request):
        quota = QuotaService.get_or_create(request.user)
        return JsonResponse({
            "plan": quota.plan,
            "used": quota.messages_used,
            "limit": quota.messages_limit,
            "remaining": quota.remaining,
            "pct": quota.usage_pct,
            "exhausted": quota.is_exhausted,
            "plan_label": dict(AIUserQuota.PLAN_CHOICES).get(quota.plan, quota.plan),
            "upgrade_options": QuotaService.upgrade_options(quota),
        })


class QuotaSuccessView(LoginRequiredMixin, View):
    """Page de retour après paiement Stripe réussi."""
    def get(self, request):
        session_id = request.GET.get("session_id")
        if session_id:
            # Marquer le paiement comme complété
            payment = AIQuotaPayment.objects.filter(
                stripe_session_id=session_id,
                quota__user=request.user,
                status=AIQuotaPayment.STATUS_PENDING,
            ).first()
            if payment:
                payment.status = AIQuotaPayment.STATUS_COMPLETED
                payment.completed_at = timezone.now()
                payment.save(update_fields=["status", "completed_at"])
                payment.quota.top_up(payment.plan)
        # Rediriger vers le dashboard avec un message de succès
        return redirect("/dashboard/?quota_ok=1")


class QuotaCancelView(LoginRequiredMixin, View):
    """Page de retour après annulation du paiement Stripe."""
    def get(self, request):
        return redirect("/dashboard/?quota_cancelled=1")


@csrf_exempt
@require_POST
def stripe_webhook(request):
    """Webhook Stripe pour les paiements de quota LeoAI."""
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
    webhook_secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", "")

    if not webhook_secret:
        return HttpResponse(status=400)

    try:
        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except Exception as exc:
        log.warning("stripe.webhook.invalid err=%s", exc)
        return HttpResponse(status=400)

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        session_id = session.get("id")
        metadata = session.get("metadata", {})
        user_id = metadata.get("user_id")
        plan = metadata.get("plan")

        if session_id and user_id and plan:
            payment = AIQuotaPayment.objects.filter(
                stripe_session_id=session_id,
                status=AIQuotaPayment.STATUS_PENDING,
            ).first()
            if payment:
                payment.status = AIQuotaPayment.STATUS_COMPLETED
                payment.completed_at = timezone.now()
                payment.save(update_fields=["status", "completed_at"])
                payment.quota.top_up(plan)
                log.info("quota.stripe.completed user=%s plan=%s", user_id, plan)

    return HttpResponse(status=200)
