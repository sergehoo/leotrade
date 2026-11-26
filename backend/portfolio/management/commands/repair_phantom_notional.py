"""Corrige les débits fantômes du grand livre des portefeuilles.

    python manage.py repair_phantom_notional            # inspection seule
    python manage.py repair_phantom_notional --apply    # écrit les corrections

`Order.approved_quantity` n'a pas d'unité garantie : plusieurs chemins y
écrivent un montant en devise au lieu d'une quantité. L'adaptateur paper
calculait alors `notional = prix × quantité`, et le grand livre recevait
un débit sans rapport avec l'opération voulue.

La commande ne RÉÉCRIT PAS l'historique. Elle poste une écriture de
CORRECTION pour la différence, comme on le ferait en comptabilité : un
grand livre se corrige par une contre-écriture datée et motivée, jamais
en effaçant une ligne. L'écriture fautive reste lisible, et le
rapprochement (`WalletReconciliationService` côté portefeuille
électronique, `recompute_cash_state` ici) retombe sur ses pieds.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

#: Même seuil que la garde d'exécution, pour que l'inspection et la
#: prévention désignent exactement le même ensemble d'écritures.
from execution.services import MAX_NOTIONAL_OVERSHOOT


class Command(BaseCommand):
    help = "Corrige les débits de grand livre incohérents avec le notionnel approuvé."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Écrit les corrections. Sans ce drapeau, rien n'est modifié.",
        )
        parser.add_argument(
            "--portfolio",
            type=int,
            default=None,
            help="Limiter à un portefeuille.",
        )
        parser.add_argument(
            "--positions",
            action="store_true",
            help=(
                "Corriger aussi les quantités de position égales au montant "
                "approuvé. Signature la plus sûre du défaut d'unité."
            ),
        )

    def handle(self, *args, **options):
        from execution.models import Order
        from portfolio.models import CashLedgerEntry, Portfolio
        from portfolio.services import PortfolioAccountingService, PortfolioService

        entries = CashLedgerEntry.objects.filter(
            entry_type="TRADE_EXECUTION", reference_type="ORDER",
        ).select_related("portfolio")
        if options["portfolio"]:
            entries = entries.filter(portfolio_id=options["portfolio"])

        suspects = []
        for entry in entries.order_by("portfolio_id", "created_at"):
            # Une correction déjà posée ne doit pas en appeler une seconde.
            if (entry.metadata or {}).get("repaired"):
                continue
            try:
                order = Order.objects.get(pk=int(entry.reference_id))
            except (Order.DoesNotExist, TypeError, ValueError):
                continue

            approved = Decimal(order.approved_notional or 0)
            if approved <= 0:
                continue

            magnitude = abs(Decimal(entry.amount))
            if magnitude <= approved * MAX_NOTIONAL_OVERSHOOT:
                continue

            suspects.append((entry, order, approved, magnitude))

        if not suspects:
            self.stdout.write(self.style.SUCCESS("Aucun débit fantôme au grand livre."))
            # Les quantités de position sont un défaut distinct : un grand
            # livre déjà corrigé n'implique pas des positions saines.
            if options["positions"]:
                self._repair_positions(options)
            return

        touched = set()
        total_correction = Decimal("0.00")

        for entry, order, approved, magnitude in suspects:
            # Le débit aurait dû valoir le notionnel approuvé. La
            # correction est la différence, dans le sens inverse.
            correction = (magnitude - approved).quantize(Decimal("0.01"))
            total_correction += correction
            touched.add(entry.portfolio_id)

            self.stdout.write(
                f"  portefeuille {entry.portfolio_id} · ordre {order.pk} "
                f"{order.symbol} : débité {entry.amount}, approuvé {approved} "
                f"→ correction +{correction}"
            )

            if not options["apply"]:
                continue

            with transaction.atomic():
                PortfolioAccountingService.add_ledger_entry(
                    portfolio=entry.portfolio,
                    entry_type="MANUAL_ADJUSTMENT",
                    amount=correction,
                    reference_type="ORDER",
                    reference_id=str(order.pk),
                    description=(
                        f"Correction d'un débit incohérent : {magnitude} débité "
                        f"pour un notionnel approuvé de {approved}."
                    ),
                    metadata={
                        "stage": "phantom_notional_repair",
                        "corrected_entry_id": entry.pk,
                        "original_amount": str(entry.amount),
                        "approved_notional": str(approved),
                    },
                )
                # On marque l'écriture d'origine pour qu'une seconde
                # exécution ne la corrige pas deux fois. Son montant reste
                # intact : l'historique n'est pas réécrit.
                entry.metadata = {**(entry.metadata or {}), "repaired": True}
                entry.save(update_fields=["metadata", "updated_at"])

        self.stdout.write("")
        self.stdout.write(
            f"{len(suspects)} écriture(s) concernée(s), "
            f"{len(touched)} portefeuille(s), correction totale +{total_correction}"
        )

        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING(
                    "Inspection seule — rien n'a été modifié. "
                    "Relance avec --apply pour écrire les corrections."
                )
            )
            if options["positions"]:
                self._repair_positions(options)
            return

        self._refresh(touched, "solde")

        self.stdout.write(self.style.SUCCESS("Corrections écrites."))

        if options["positions"]:
            self._repair_positions(options)

    def _refresh(self, portfolio_ids, label: str) -> None:
        """Recalcule les métriques, un portefeuille à la fois.

        Un portefeuille dont l'enregistrement échoue ne doit pas priver
        les autres de leur recalcul. `Portfolio.save()` appelle
        `full_clean()`, et un portefeuille rattaché au compte broker d'un
        AUTRE utilisateur devient par là même impossible à écrire : toute
        mise à jour comptable y est bloquée, pas seulement celle-ci.
        """
        from portfolio.models import Portfolio
        from portfolio.services import PortfolioService

        for portfolio_id in sorted(portfolio_ids):
            portfolio = Portfolio.objects.get(pk=portfolio_id)
            try:
                PortfolioService.refresh_portfolio_metrics(portfolio)
            except Exception as exc:
                self.stdout.write(
                    self.style.ERROR(
                        f"  portefeuille {portfolio_id} « {portfolio.name} » : "
                        f"recalcul IMPOSSIBLE — {exc}"
                    )
                )
                self.stdout.write(
                    "      Les corrections sont écrites au grand livre, mais le "
                    "champ de solde reste périmé tant que la cause n'est pas levée."
                )
                continue
            portfolio.refresh_from_db()
            self.stdout.write(
                f"  portefeuille {portfolio_id} « {portfolio.name} » : "
                f"{label} {portfolio.current_balance}, "
                f"valorisation {portfolio.equity}"
            )

    #: Une quantité dont l'écart au montant approuvé est sous ce seuil est
    #: tenue pour être ce montant, recopié dans le champ quantité.
    QUANTITY_MATCH_TOLERANCE = Decimal("0.01")

    def _repair_positions(self, options):
        """Corrige les quantités de position qui portent un montant.

        On ne touche QUE les positions dont la quantité est, à 1 % près,
        égale au notionnel approuvé de son ordre d'origine. C'est la
        signature démontrable du défaut : sur BTCUSDT, `quantity` vaut
        exactement 20 000 — le montant engagé — au lieu de 0,2538 BTC.

        Toute position dont l'écart n'est pas concluant est signalée et
        laissée intacte : deviner une quantité serait inventer une
        position.
        """
        from execution.models import Order
        from portfolio.models import Portfolio, Position
        from portfolio.services import PortfolioService

        self.stdout.write("")
        self.stdout.write("=== Quantités de position ===")

        positions = Position.objects.filter(status__in=["OPEN", "PARTIALLY_CLOSED"])
        if options["portfolio"]:
            positions = positions.filter(portfolio_id=options["portfolio"])

        repaired = 0
        skipped = []
        touched = set()

        for position in positions.select_related("portfolio").order_by("pk"):
            quantity = Decimal(position.quantity or 0)
            entry = Decimal(position.average_entry_price or 0)
            if quantity <= 0 or entry <= 0:
                skipped.append((position, "quantité ou prix d'entrée absent"))
                continue

            reference = position.broker_order_id or ""
            order = None
            if reference.startswith("PAPER-"):
                try:
                    order = Order.objects.filter(pk=int(reference.split("-")[1])).first()
                except (ValueError, IndexError):
                    order = None

            if order is None:
                # Référence broker non exploitable (identifiant de contrat
                # Deriv, par exemple). On cherche alors sur le même
                # portefeuille et le même symbole un ordre dont le
                # notionnel approuvé correspond à la quantité — c'est la
                # SIGNATURE qui authentifie le rattachement, pas l'inverse.
                # Si plusieurs ordres correspondent, le rattachement est
                # ambigu et on ne touche à rien.
                matches = [
                    candidate
                    for candidate in Order.objects.filter(
                        portfolio_id=position.portfolio_id,
                        symbol=position.symbol,
                        status="FILLED",
                    )
                    if Decimal(candidate.approved_notional or 0) > 0
                    and abs(quantity - Decimal(candidate.approved_notional))
                    / Decimal(candidate.approved_notional)
                    <= self.QUANTITY_MATCH_TOLERANCE
                ]
                if len(matches) == 1:
                    order = matches[0]
                elif len(matches) > 1:
                    skipped.append(
                        (position, f"rattachement ambigu ({len(matches)} ordres)")
                    )
                    continue

            if order is None:
                skipped.append((position, "ordre d'origine introuvable"))
                continue

            approved = Decimal(order.approved_notional or 0)
            if approved <= 0:
                skipped.append((position, "notionnel approuvé absent"))
                continue

            gap = abs(quantity - approved) / approved
            if gap > self.QUANTITY_MATCH_TOLERANCE:
                skipped.append((position, f"écart non concluant ({gap:.2%})"))
                continue

            corrected = (approved / entry).quantize(Decimal("0.00000001"))
            self.stdout.write(
                f"  position {position.pk} {position.symbol} : "
                f"quantité {quantity} → {corrected} "
                f"(montant approuvé {approved}, entrée {entry})"
            )
            repaired += 1
            touched.add(position.portfolio_id)

            if not options["apply"]:
                continue

            with transaction.atomic():
                position.quantity = corrected
                position.metadata = {
                    **(position.metadata or {}),
                    "phantom_quantity_repair": {
                        "previous_quantity": str(quantity),
                        "previous_unrealized_pnl": str(position.unrealized_pnl),
                        "approved_notional": str(approved),
                    },
                }
                # `unrealized_pnl`, `notional_value` et `exposure_value`
                # sont des champs STOCKÉS, dérivés de la quantité. Les
                # laisser en l'état après avoir corrigé la quantité les
                # rendrait incohérents, et le portefeuille se contente de
                # les sommer : le latent fantôme survivrait à la
                # correction.
                position.update_market_metrics()
                position.save(update_fields=[
                    "quantity", "notional_value", "exposure_value",
                    "unrealized_pnl", "pnl", "pnl_percent",
                    "metadata", "updated_at",
                ])

        for position, reason in skipped:
            self.stdout.write(
                f"  position {position.pk} {position.symbol} : laissée intacte "
                f"— {reason}"
            )

        self.stdout.write("")
        self.stdout.write(
            f"{repaired} quantité(s) corrigée(s), {len(skipped)} laissée(s) intacte(s)"
        )

        if not options["apply"]:
            return

        self._refresh(touched, "valorisation")
