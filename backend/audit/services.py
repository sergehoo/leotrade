from core.logging import get_logger, log_event

logger = get_logger("audit")


class AuditLogService:
    @staticmethod
    def log_business_event(event_name: str, **payload):
        log_event(logger, "info", event_name, **payload)

    @staticmethod
    def log_security_event(event_name: str, **payload):
        log_event(logger, "warning", event_name, **payload)

    @staticmethod
    def log_error_event(event_name: str, **payload):
        log_event(logger, "error", event_name, **payload)