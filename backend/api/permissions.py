from rest_framework.permissions import IsAuthenticated


class IsOwner(IsAuthenticated):
    """
    L'objet doit appartenir à request.user, via `.user` ou `.portfolio.user`.

    Hérite d'`IsAuthenticated` à dessein : les ViewSets qui déclarent
    `permission_classes = [IsOwner]` remplacent la permission par défaut du
    projet. Sans ce socle, une requête anonyme franchissait `has_permission`
    (qui renvoyait `True`) et atteignait `get_queryset()`, où le
    `filter(user=AnonymousUser)` lève un TypeError — soit un 500 là où un
    401 est attendu.
    """

    def has_object_permission(self, request, view, obj):
        if not (request.user and request.user.is_authenticated):
            return False

        if hasattr(obj, "user_id"):
            return obj.user_id == request.user.id

        if hasattr(obj, "portfolio") and hasattr(obj.portfolio, "user_id"):
            return obj.portfolio.user_id == request.user.id

        return False
