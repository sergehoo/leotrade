from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from strategies.models import Signal


class SignalReviewError(ValueError):
    pass


class SignalReviewService:
    REVIEWABLE_STATUSES = {"NEW", "SCORED", "APPROVED", "REJECTED"}

    @classmethod
    @transaction.atomic
    def review(cls, *, signal_id: int, user, decision: str) -> Signal:
        normalized_decision = str(decision or "").upper()
        if normalized_decision not in {"APPROVED", "REJECTED"}:
            raise SignalReviewError("Décision de validation invalide.")

        signal = (
            Signal.objects.reviewable_by(user)
            .select_for_update()
            .select_related("strategy", "user")
            .filter(pk=signal_id)
            .first()
        )
        if signal is None:
            raise SignalReviewError("Signal introuvable ou non modifiable.")
        if signal.expires_at and signal.expires_at <= timezone.now():
            raise SignalReviewError("Ce signal a expiré et ne peut plus être validé.")
        if signal.status not in cls.REVIEWABLE_STATUSES:
            raise SignalReviewError(
                f"Le signal ne peut plus être validé depuis le statut {signal.status}."
            )

        now = timezone.now()
        signal.status = normalized_decision
        signal.reviewed_by = user
        signal.reviewed_at = now
        signal.approved_at = now if normalized_decision == "APPROVED" else None
        signal.save(
            update_fields=[
                "status",
                "reviewed_by",
                "reviewed_at",
                "approved_at",
                "updated_at",
            ]
        )
        return signal

    @classmethod
    def approve(cls, *, signal_id: int, user) -> Signal:
        return cls.review(signal_id=signal_id, user=user, decision="APPROVED")

    @classmethod
    def reject(cls, *, signal_id: int, user) -> Signal:
        return cls.review(signal_id=signal_id, user=user, decision="REJECTED")
