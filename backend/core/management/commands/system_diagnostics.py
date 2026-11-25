from __future__ import annotations

import json
import uuid

from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from core.monitoring import (
    collect_operational_snapshot,
    operational_snapshot_age,
    read_operational_snapshot,
    store_operational_snapshot,
)


class Command(BaseCommand):
    help = "Diagnostic système et trading Lyneci"

    def add_arguments(self, parser):
        parser.add_argument(
            "--fresh",
            action="store_true",
            help="Recalcule immédiatement le snapshot opérationnel.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Retourne un résultat JSON exploitable par une sonde.",
        )
        parser.add_argument(
            "--no-fail",
            action="store_true",
            help="Conserve un code de sortie nul même en état dégradé.",
        )

    def handle(self, *args, **options):
        checks = {"database": False, "cache": False, "monitoring": False}
        errors = {}

        try:
            with connections["default"].cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            checks["database"] = True
        except Exception as exc:
            errors["database"] = type(exc).__name__

        cache_key = f"diagnostics:{uuid.uuid4().hex}"
        try:
            cache.set(cache_key, "ok", timeout=10)
            checks["cache"] = cache.get(cache_key) == "ok"
            cache.delete(cache_key)
        except Exception as exc:
            errors["cache"] = type(exc).__name__

        snapshot = None
        if checks["database"] and checks["cache"]:
            try:
                if options["fresh"]:
                    snapshot = collect_operational_snapshot()
                    store_operational_snapshot(snapshot)
                else:
                    snapshot = read_operational_snapshot()
                age = operational_snapshot_age(snapshot)
                max_age = int(
                    getattr(settings, "MONITORING_HEARTBEAT_MAX_AGE_SECONDS", 120)
                )
                checks["monitoring"] = age is not None and age <= max_age
            except Exception as exc:
                errors["monitoring"] = type(exc).__name__

        operational_status = snapshot.get("status") if snapshot else "unavailable"
        healthy = all(checks.values()) and operational_status != "critical"
        result = {
            "status": "ok" if healthy else "degraded",
            "checks": checks,
            "operational_status": operational_status,
            "snapshot_age_seconds": operational_snapshot_age(snapshot),
            "errors": errors,
            "snapshot": snapshot,
        }

        if options["json"]:
            self.stdout.write(json.dumps(result, ensure_ascii=False, default=str))
        else:
            self.stdout.write(self.style.NOTICE("== Lyneci diagnostics =="))
            for name, passed in checks.items():
                style = self.style.SUCCESS if passed else self.style.ERROR
                self.stdout.write(style(f"{name}: {'OK' if passed else 'ERROR'}"))
            self.stdout.write(f"operational_status: {operational_status}")

        if not healthy and not options["no_fail"]:
            raise CommandError("Lyneci est dégradé ; consulter le diagnostic.")

        return None
