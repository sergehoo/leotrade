from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar


# =============================
# Context (request / user)
# =============================

request_id_ctx_var: ContextVar[str | None] = ContextVar("request_id", default=None)
user_id_ctx_var: ContextVar[str | None] = ContextVar("user_id", default=None)


def set_request_context(request_id: str | None = None, user_id: str | None = None):
    request_id_ctx_var.set(request_id or str(uuid.uuid4()))
    user_id_ctx_var.set(user_id)


def clear_request_context():
    request_id_ctx_var.set(None)
    user_id_ctx_var.set(None)


class RequestContextFilter(logging.Filter):
    def filter(self, record):
        record.request_id = request_id_ctx_var.get() or "-"
        record.user_id = user_id_ctx_var.get() or "-"
        return True


# =============================
# Logger factory
# =============================

def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)

    # éviter d'ajouter plusieurs fois le filter
    if not any(isinstance(f, RequestContextFilter) for f in logger.filters):
        logger.addFilter(RequestContextFilter())

    return logger


# =============================
# Structured logging helper
# =============================

def log_event(
    logger: logging.Logger,
    level: str,
    event: str,
    **payload,
):
    """
    Logging structuré pour événements métier

    Exemple :
        log_event(logger, "info", "order_created", order_id=1, symbol="BTCUSDT")
    """

    log_method = getattr(logger, level.lower(), logger.info)

    log_method(
        event,
        extra={
            "event": event,
            **payload,
        },
    )