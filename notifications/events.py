"""
Registre canonique des événements de notification LeoTrade.

Chaque événement déclare : catégorie (pour les préférences utilisateur),
sévérité et priorité par défaut, et s'il est critique (un événement critique
ignore les quiet hours et force tous les canaux autorisés par l'utilisateur).

Source de vérité unique : la data migration de seed et les services lisent
ce registre — ajouter un événement ici suffit pour qu'il soit utilisable.
"""

from __future__ import annotations

from dataclasses import dataclass


class Severity:
    INFO = "INFO"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"

    CHOICES = [(v, v) for v in (INFO, SUCCESS, WARNING, CRITICAL)]


class Priority:
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"

    CHOICES = [(v, v) for v in (LOW, NORMAL, HIGH, URGENT)]
    ORDER = {LOW: 0, NORMAL: 1, HIGH: 2, URGENT: 3}


class Channel:
    EMAIL = "EMAIL"
    IN_APP = "IN_APP"
    SMS = "SMS"
    WHATSAPP = "WHATSAPP"

    CHOICES = [(v, v) for v in (EMAIL, IN_APP, SMS, WHATSAPP)]
    ALL = (EMAIL, IN_APP, SMS, WHATSAPP)


class Category:
    """Catégories alignées sur les toggles de NotificationPreference."""
    TRADE = "TRADE"
    RISK = "RISK"
    BROKER = "BROKER"
    AI = "AI"
    SECURITY = "SECURITY"
    REPORT = "REPORT"
    ACCOUNT = "ACCOUNT"

    CHOICES = [(v, v) for v in (TRADE, RISK, BROKER, AI, SECURITY, REPORT, ACCOUNT)]


@dataclass(frozen=True)
class EventSpec:
    code: str
    label: str
    category: str
    severity: str = Severity.INFO
    priority: str = Priority.NORMAL
    critical: bool = False  # ignore quiet hours + force SMS/WhatsApp si autorisés


def _e(code, label, category, severity=Severity.INFO, priority=Priority.NORMAL, critical=False):
    return EventSpec(code, label, category, severity, priority, critical)


EVENTS: dict[str, EventSpec] = {e.code: e for e in [
    # ── Broker ───────────────────────────────────────────────────────────────
    _e("BROKER_ACCOUNT_CREATED", "Compte broker créé", Category.BROKER, Severity.SUCCESS),
    _e("BROKER_ACCOUNT_UPDATED", "Compte broker modifié", Category.BROKER),
    _e("BROKER_CONNECTION_OK", "Connexion broker réussie", Category.BROKER, Severity.SUCCESS),
    _e("BROKER_CONNECTION_FAILED", "Connexion broker échouée", Category.BROKER, Severity.WARNING, Priority.HIGH),
    _e("BROKER_DEFAULT_CHANGED", "Broker par défaut modifié", Category.BROKER),
    _e("BROKER_ERROR", "Erreur broker", Category.BROKER, Severity.CRITICAL, Priority.URGENT, critical=True),
    _e("BROKER_SYNC_OK", "Synchronisation portefeuille réussie", Category.BROKER, Severity.SUCCESS, Priority.LOW),
    _e("BROKER_SYNC_FAILED", "Synchronisation portefeuille échouée", Category.BROKER, Severity.WARNING, Priority.HIGH),
    _e("BROKER_RECONCILIATION_OK", "Réconciliation broker réussie", Category.BROKER, Severity.SUCCESS, Priority.LOW),
    _e("BROKER_RECONCILIATION_FAILED", "Réconciliation broker échouée", Category.BROKER, Severity.WARNING, Priority.HIGH),

    # ── IA / opportunités ────────────────────────────────────────────────────
    _e("AI_OPPORTUNITY_DETECTED", "Nouvelle opportunité IA détectée", Category.AI),
    _e("AI_OPPORTUNITY_APPROVED", "Opportunité IA approuvée", Category.AI, Severity.SUCCESS),
    _e("AI_OPPORTUNITY_REJECTED", "Opportunité IA rejetée", Category.AI),
    _e("AI_OPPORTUNITY_EXPIRED", "Opportunité IA expirée", Category.AI, Severity.INFO, Priority.LOW),
    _e("AI_ERROR", "Erreur du moteur IA", Category.AI, Severity.WARNING, Priority.HIGH),

    # ── Signaux ──────────────────────────────────────────────────────────────
    _e("SIGNAL_GENERATED", "Signal généré", Category.TRADE, Severity.INFO, Priority.LOW),
    _e("SIGNAL_VALIDATED", "Signal validé", Category.TRADE, Severity.SUCCESS),
    _e("SIGNAL_RISK_REJECTED", "Signal rejeté par le risk engine", Category.RISK, Severity.WARNING),

    # ── Ordres ───────────────────────────────────────────────────────────────
    _e("ORDER_CREATED", "Ordre créé", Category.TRADE),
    _e("ORDER_SUBMITTED", "Ordre soumis au broker", Category.TRADE),
    _e("ORDER_PARTIALLY_FILLED", "Ordre partiellement exécuté", Category.TRADE, Severity.SUCCESS),
    _e("ORDER_FILLED", "Ordre exécuté", Category.TRADE, Severity.SUCCESS, Priority.HIGH),
    _e("ORDER_REJECTED", "Ordre rejeté", Category.TRADE, Severity.WARNING, Priority.HIGH),
    _e("ORDER_FAILED", "Ordre échoué", Category.TRADE, Severity.CRITICAL, Priority.URGENT, critical=True),
    _e("ORDER_CANCELLED", "Ordre annulé", Category.TRADE),

    # ── Positions ────────────────────────────────────────────────────────────
    _e("POSITION_OPENED", "Position ouverte", Category.TRADE, Severity.SUCCESS, Priority.HIGH),
    _e("POSITION_UPDATED", "Position mise à jour", Category.TRADE, Severity.INFO, Priority.LOW),
    _e("POSITION_CLOSED", "Position fermée", Category.TRADE, Severity.SUCCESS, Priority.HIGH),
    _e("TAKE_PROFIT_HIT", "Take profit atteint", Category.TRADE, Severity.SUCCESS, Priority.HIGH),
    _e("STOP_LOSS_HIT", "Stop loss atteint", Category.TRADE, Severity.WARNING, Priority.HIGH),

    # ── Risque ───────────────────────────────────────────────────────────────
    _e("HIGH_DRAWDOWN", "Drawdown élevé", Category.RISK, Severity.WARNING, Priority.URGENT, critical=True),
    _e("DAILY_LOSS_LIMIT", "Limite de perte journalière atteinte", Category.RISK, Severity.CRITICAL, Priority.URGENT, critical=True),
    _e("WEEKLY_LOSS_LIMIT", "Limite de perte hebdomadaire atteinte", Category.RISK, Severity.CRITICAL, Priority.URGENT, critical=True),
    _e("MONTHLY_LOSS_LIMIT", "Limite de perte mensuelle atteinte", Category.RISK, Severity.CRITICAL, Priority.URGENT, critical=True),
    _e("KILL_SWITCH_ACTIVATED", "Kill switch activé", Category.RISK, Severity.CRITICAL, Priority.URGENT, critical=True),
    _e("KILL_SWITCH_DEACTIVATED", "Kill switch désactivé", Category.RISK, Severity.SUCCESS, Priority.HIGH),
    _e("STRATEGY_CIRCUIT_BREAKER", "Stratégie coupée automatiquement", Category.RISK, Severity.WARNING, Priority.URGENT, critical=True),

    # ── KYC / compte ─────────────────────────────────────────────────────────
    _e("KYC_SUBMITTED", "KYC soumis", Category.ACCOUNT),
    _e("KYC_APPROVED", "KYC approuvé", Category.ACCOUNT, Severity.SUCCESS, Priority.HIGH),
    _e("KYC_REJECTED", "KYC rejeté", Category.ACCOUNT, Severity.WARNING, Priority.HIGH),

    # ── Sécurité ─────────────────────────────────────────────────────────────
    _e("SECURITY_ALERT", "Alerte sécurité", Category.SECURITY, Severity.CRITICAL, Priority.URGENT, critical=True),
    _e("SUSPICIOUS_LOGIN", "Connexion suspecte", Category.SECURITY, Severity.CRITICAL, Priority.URGENT, critical=True),
    _e("LIVE_MODE_ENABLED", "Passage en mode LIVE", Category.SECURITY, Severity.WARNING, Priority.URGENT, critical=True),
    _e("LIVE_TRADE_CONFIRMATION", "Confirmation avant trade LIVE", Category.SECURITY, Severity.WARNING, Priority.URGENT, critical=True),

    # ── Système ──────────────────────────────────────────────────────────────
    _e("CELERY_CRITICAL_ERROR", "Erreur Celery critique", Category.SECURITY, Severity.CRITICAL, Priority.URGENT, critical=True),

    # ── Rapports ─────────────────────────────────────────────────────────────
    _e("DAILY_TRADING_REPORT", "Rapport quotidien de trading", Category.REPORT, Severity.INFO, Priority.LOW),
    _e("WEEKLY_PERFORMANCE_REPORT", "Rapport hebdomadaire de performance", Category.REPORT, Severity.INFO, Priority.LOW),
]}

EVENT_CHOICES = [(code, spec.label) for code, spec in EVENTS.items()]

# Mapping catégorie → champ de préférence utilisateur
CATEGORY_PREFERENCE_FIELD = {
    Category.TRADE: "trade_events_enabled",
    Category.RISK: "risk_events_enabled",
    Category.BROKER: "broker_events_enabled",
    Category.AI: "ai_events_enabled",
    Category.SECURITY: "security_events_enabled",
    Category.REPORT: "reports_enabled",
    Category.ACCOUNT: "security_events_enabled",  # KYC = sensible, même toggle
}


def get_event(code: str) -> EventSpec:
    """Retourne la spec ; un code inconnu retombe sur un INFO générique
    plutôt que de casser le flux appelant."""
    return EVENTS.get(code) or EventSpec(
        code=code, label=code, category=Category.TRADE,
    )
