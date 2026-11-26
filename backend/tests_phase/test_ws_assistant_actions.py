"""
tests_phase/test_ws_assistant_actions.py
========================================

Confirmer une action proposée par Leo.

Deux modèles distincts portent deux choses distinctes, et ils avaient
été confondus :

  ``AssistantAction``        — ce que Leo PROPOSE au fil d'un message
                               (brouillon d'ordre, stop suggéré). Tranché
                               par la socket : ``action_confirm`` /
                               ``action_reject``.
  ``AssistantActionRequest`` — une demande de confirmation
                               TRANSACTIONNELLE passée par le Risk
                               Engine. Tranchée par
                               ``action_request_confirm`` ou par
                               ``/assistant/action-requests/<id>/confirm/``.

Les deux clients envoyaient l'identifiant du premier à l'endpoint du
second. Deux séquences de clés primaires différentes : soit rien ne
correspond et le bouton est mort, soit une demande de l'utilisateur
porte le même numéro et c'est ELLE qui est exécutée — un ordre qu'il n'a
pas regardé.

Côté serveur, le chemin socket n'avait jamais été emprunté par personne,
et il portait deux défauts :

  - le filtre visait ``message__session__user`` alors que
    ``AssistantMessage`` porte ``conversation`` : un ``FieldError`` au
    premier clic ;
  - ``CONFIRMED`` était renvoyé sans regarder le résultat, y compris
    quand l'action appartenait à quelqu'un d'autre.
"""

import pytest
from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model

from ai_assistant.consumers import AssistantConsumer
from ai_assistant.models import (
    AssistantAction,
    AssistantConversation,
    AssistantMessage,
)

User = get_user_model()


def _user(name):
    return User.objects.create_user(
        username=name, email=f"{name}@leotrade.test", password="StrongPass123!",
    )


def _action_for(user):
    conversation = AssistantConversation.objects.create(user=user)
    message = AssistantMessage.objects.create(
        conversation=conversation, role="ASSISTANT", content="Proposition.",
    )
    return AssistantAction.objects.create(
        message=message,
        action_type=AssistantAction.TYPE_SUGGEST_SIZE,
        rationale="Taille suggérée par le moteur.",
    )


def _consumer_for(user):
    consumer = AssistantConsumer()
    consumer.user = user
    return consumer


@pytest.mark.django_db
class TestConfirmingAnAction:

    def test_the_owner_can_confirm(self):
        """Le filtre doit simplement RÉSOUDRE.

        Avec ``message__session__user``, cet appel levait un FieldError —
        le bouton tombait sur une erreur 500 côté socket.
        """
        owner = _user("proprietaire")
        action = _action_for(owner)

        result = async_to_sync(_consumer_for(owner)._confirm_action)(action.pk)

        assert "error" not in result
        action.refresh_from_db()
        assert action.status == "CONFIRMED"

    def test_another_user_cannot_confirm_it(self):
        """Le cloisonnement vaut aussi sur la socket.

        Une action propose d'engager de l'argent : elle ne doit jamais
        traverser la frontière du compte.
        """
        owner = _user("proprietaire")
        intruder = _user("intrus")
        action = _action_for(owner)

        result = async_to_sync(_consumer_for(intruder)._confirm_action)(action.pk)

        assert result.get("error")
        action.refresh_from_db()
        assert action.status != "CONFIRMED"

    def test_rejecting_reports_whether_it_happened(self):
        """``_reject_action`` rend un verdict, il ne se tait plus.

        Tant qu'il ne retournait rien, le consumer répondait ``REJECTED``
        même pour une action inexistante : l'écran affichait « Refusée »
        sans que rien n'ait été refusé.
        """
        owner = _user("proprietaire")
        intruder = _user("intrus")
        action = _action_for(owner)

        assert async_to_sync(_consumer_for(intruder)._reject_action)(action.pk) is False
        assert async_to_sync(_consumer_for(owner)._reject_action)(action.pk) is True

        action.refresh_from_db()
        assert action.status == "REJECTED"
