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
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import AssistantConversation, AssistantMessage, AssistantAction, AIUserQuota, AIQuotaPayment
from .services import QuotaService

log = logging.getLogger("leotrade.ai_assistant")


class AssistantConversationView(LoginRequiredMixin, View):
    """Retourne la session active + les N derniers messages."""

    def get(self, request):
        session = (
            AssistantConversation.objects
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
        completed = bool(
            session_id
            and AIQuotaPayment.objects.filter(
                stripe_session_id=session_id,
                quota__user=request.user,
                status=AIQuotaPayment.STATUS_COMPLETED,
            ).exists()
        )
        suffix = "quota_ok=1" if completed else "quota_processing=1"
        return redirect(f"/dashboard/?{suffix}")


class QuotaCancelView(LoginRequiredMixin, View):
    """Page de retour après annulation du paiement Stripe."""
    def get(self, request):
        return redirect("/dashboard/?quota_cancelled=1")


@csrf_exempt
@require_POST
@transaction.atomic
def stripe_webhook(request):
    """Webhook Stripe pour les paiements de quota LeoTrade AI."""
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

    if event["type"] in {
        "checkout.session.completed",
        "checkout.session.async_payment_succeeded",
    }:
        session = event["data"]["object"]
        session_id = session.get("id")
        metadata = session.get("metadata", {})
        user_id = metadata.get("user_id")
        plan = metadata.get("plan")

        if session_id and user_id and plan:
            payment = AIQuotaPayment.objects.select_for_update().select_related(
                "quota"
            ).filter(
                stripe_session_id=session_id,
                status=AIQuotaPayment.STATUS_PENDING,
            ).first()
            if payment:
                try:
                    paid_amount = (
                        Decimal(str(session.get("amount_total"))) / Decimal("100")
                    )
                except (InvalidOperation, TypeError, ValueError):
                    paid_amount = None

                valid = all(
                    (
                        session.get("payment_status") == "paid",
                        str(session.get("currency") or "").upper() == "USD",
                        paid_amount == payment.amount_usd,
                        str(user_id) == str(payment.quota.user_id),
                        plan == payment.plan,
                    )
                )
                if not valid:
                    log.warning(
                        "quota.stripe.mismatch session=%s payment=%s",
                        session_id,
                        payment.pk,
                    )
                    return HttpResponse(status=400)

                payment.status = AIQuotaPayment.STATUS_COMPLETED
                payment.completed_at = timezone.now()
                payment.save(update_fields=["status", "completed_at"])
                payment.quota.top_up(payment.plan)
                log.info(
                    "quota.stripe.completed user=%s plan=%s",
                    payment.quota.user_id,
                    payment.plan,
                )

    return HttpResponse(status=200)


class ConversationCenterView(LoginRequiredMixin, View):
    """Centre des conversations — interface type ChatGPT (liste, recherche,
    archivage, reprise). Les données viennent de l'API DRF."""

    def get(self, request):
        from django.shortcuts import render
        return render(request, "assistant/conversations.html")
