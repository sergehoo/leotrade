"""
api/fields.py
=============

Champs de relation qui refusent les objets d'autrui.

Un `PrimaryKeyRelatedField` ordinaire accepte n'importe quel identifiant
existant. Sur une ressource rattachée à un portefeuille, cela suffit à
écrire chez un autre utilisateur : `perform_create` fixe bien
`user=request.user`, mais la clé étrangère, elle, vient du corps de la
requête et n'est vérifiée nulle part.

Le cas réellement reproduit avant ce correctif : un compte tiers créait
un `RiskProfile` sur le portefeuille d'une victime, avec
`max_risk_per_trade=99%` et `is_default=True`. Le moteur de risque
retenant le profil par défaut, l'intrus réécrivait les limites de
sécurité d'un autre utilisateur.

La garde filtre le queryset plutôt que de valider après coup : DRF rend
alors une erreur « objet inexistant » identique à celle d'un identifiant
inconnu, sans révéler qu'il existe et appartient à quelqu'un d'autre.
"""

from __future__ import annotations

from rest_framework import serializers


class OwnedRelatedField(serializers.PrimaryKeyRelatedField):
    """Relation restreinte aux objets de l'utilisateur authentifié.

    `owner_lookup` est le chemin ORM menant au propriétaire depuis le
    modèle cible : ``"user"`` pour un Portfolio, ``"portfolio__user"``
    pour une Position, etc.
    """

    def __init__(self, *, owner_lookup: str = "user", **kwargs):
        self.owner_lookup = owner_lookup
        super().__init__(**kwargs)

    def get_queryset(self):
        queryset = super().get_queryset()
        request = self.context.get("request")
        user = getattr(request, "user", None)

        if user is None or not user.is_authenticated:
            # Sans utilisateur identifié, aucun objet n'est accessible.
            # Renvoyer le queryset complet ici rouvrirait exactement la
            # faille que cette classe ferme.
            return queryset.none()

        return queryset.filter(**{self.owner_lookup: user})
