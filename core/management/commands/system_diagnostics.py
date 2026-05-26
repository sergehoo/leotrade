from django.core.management.base import BaseCommand
from django.db import connection
from django.conf import settings
from django.core.cache import cache
import redis


class Command(BaseCommand):
    help = "Diagnostic système LeoTrade"

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("== LeoTrade diagnostics =="))

        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            self.stdout.write(self.style.SUCCESS("Database: OK"))
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"Database: ERROR - {exc}"))

        try:
            cache.set("diag", "ok", timeout=10)
            value = cache.get("diag")
            if value == "ok":
                self.stdout.write(self.style.SUCCESS("Cache: OK"))
            else:
                self.stdout.write(self.style.ERROR("Cache: ERROR - invalid readback"))
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"Cache: ERROR - {exc}"))

        try:
            r = redis.from_url(settings.REDIS_URL)
            r.ping()
            self.stdout.write(self.style.SUCCESS("Redis: OK"))
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"Redis: ERROR - {exc}"))

        self.stdout.write(self.style.SUCCESS("Diagnostics terminés."))