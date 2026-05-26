"""
Lance le worker WebSocket Deriv persistant pour TOUS les BrokerAccount Deriv actifs.

Usage :
    python manage.py run_deriv_streamer

À placer derrière un superviseur (systemd, supervisord, k8s).
"""

from __future__ import annotations

import asyncio

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Lance le streamer WebSocket Deriv (subscriptions balance/transaction/contracts)."

    def handle(self, *args, **options):
        from brokers.services.deriv_streamer import start_for_all_active_accounts

        try:
            asyncio.run(start_for_all_active_accounts())
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Streamer arrêté par l'utilisateur."))
