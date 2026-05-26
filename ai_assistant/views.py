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

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.utils import timezone
from django.views import View

from .models import AssistantSession, AssistantMessage, AssistantAction


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
