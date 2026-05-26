from __future__ import annotations

import uuid
from django.utils.deprecation import MiddlewareMixin

from core.logging import set_request_context, clear_request_context

class RequestIDMiddleware(MiddlewareMixin):
    HEADER_NAME = "HTTP_X_REQUEST_ID"
    RESPONSE_HEADER = "X-Request-ID"

    def process_request(self, request):
        request_id = request.META.get(self.HEADER_NAME) or str(uuid.uuid4())
        request.request_id = request_id

    def process_response(self, request, response):
        request_id = getattr(request, "request_id", None)
        if request_id:
            response[self.RESPONSE_HEADER] = request_id
        return response
class RequestContextMiddleware(MiddlewareMixin):
    def process_request(self, request):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        user_id = None

        if hasattr(request, "user") and request.user.is_authenticated:
            user_id = str(request.user.id)

        request.request_id = request_id
        set_request_context(request_id=request_id, user_id=user_id)

    def process_response(self, request, response):
        request_id = getattr(request, "request_id", None)
        if request_id:
            response["X-Request-ID"] = request_id
        clear_request_context()
        return response

    def process_exception(self, request, exception):
        clear_request_context()
        return None