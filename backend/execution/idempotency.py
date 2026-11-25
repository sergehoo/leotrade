from __future__ import annotations

import hashlib
import json
from django.db import IntegrityError, transaction

from execution.models import IdempotencyKey


class IdempotencyService:
    @staticmethod
    def build_request_hash(payload: dict) -> str:
        raw = json.dumps(payload or {}, sort_keys=True, default=str).encode()
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    @transaction.atomic
    def get_or_create_record(user, endpoint: str, key: str, payload: dict):
        key = str(key or "").strip()
        if not key:
            raise ValueError("Clé d'idempotence vide.")
        if len(key) > 120:
            raise ValueError("Clé d'idempotence trop longue.")

        request_hash = IdempotencyService.build_request_hash(payload)
        obj = IdempotencyKey.objects.filter(key=key, user=user, endpoint=endpoint).first()

        if obj:
            if obj.request_hash != request_hash:
                raise ValueError("Même clé d'idempotence utilisée avec un payload différent.")
            return obj, False

        try:
            with transaction.atomic():
                obj = IdempotencyKey.objects.create(
                    user=user,
                    key=key,
                    endpoint=endpoint,
                    request_hash=request_hash,
                )
        except IntegrityError:
            obj = IdempotencyKey.objects.get(key=key, user=user, endpoint=endpoint)
            if obj.request_hash != request_hash:
                raise ValueError(
                    "Même clé d'idempotence utilisée avec un payload différent."
                )
            return obj, False
        return obj, True

    @staticmethod
    @transaction.atomic
    def save_response(record: IdempotencyKey, status_code: int, payload: dict):
        record.status_code = status_code
        record.response_payload = payload or {}
        record.save(update_fields=["status_code", "response_payload"])
        return record
