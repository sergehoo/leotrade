from urllib.parse import urlparse

from django.conf import settings
from django.contrib.sites.models import Site
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Synchronise le domaine public et l'identité Lyneci pour Django Sites."

    def handle(self, *args, **options):
        site_url = str(getattr(settings, "SITE_BASE_URL", "") or "").strip()
        parsed_url = urlparse(site_url)
        domain = parsed_url.netloc
        if not domain:
            raise CommandError("SITE_BASE_URL doit contenir une URL publique complète.")

        site, created = Site.objects.update_or_create(
            pk=settings.SITE_ID,
            defaults={
                "domain": domain,
                "name": getattr(
                    settings,
                    "BRAND_FULL_NAME",
                    "Lyneci — Intelligent Trading",
                ),
            },
        )
        action = "créé" if created else "mis à jour"
        self.stdout.write(self.style.SUCCESS(f"Site {site.domain} {action}."))
