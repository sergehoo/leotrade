from rest_framework.permissions import BasePermission


class IsOwner(BasePermission):
    """
    Permission objet générique : l'objet doit appartenir à request.user
    via .user ou .portfolio.user
    """

    def has_object_permission(self, request, view, obj):
        if hasattr(obj, "user_id"):
            return obj.user_id == request.user.id

        if hasattr(obj, "portfolio") and hasattr(obj.portfolio, "user_id"):
            return obj.portfolio.user_id == request.user.id

        return False