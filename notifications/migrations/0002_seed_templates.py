"""
Seed des gabarits de notification pour les événements les plus sensibles.

Les événements sans gabarit utilisent le fallback title/message — ce seed
couvre les messages qui doivent être très explicites (trade LIVE, kill switch,
limites de perte) conformément au cahier des charges.
"""

from django.db import migrations

TEMPLATES = [
    # (event_type, channel, subject, body)
    (
        "LIVE_MODE_ENABLED", "EMAIL",
        "⚠ Mode LIVE activé — argent réel",
        "Le mode LIVE vient d'être activé sur ton compte LeoTrade.\n\n"
        "À partir de maintenant, les ordres sont envoyés au broker réel et "
        "engagent de l'argent réel.\n\n"
        "Si tu n'es pas à l'origine de ce changement, repasse immédiatement "
        "en mode PAPER depuis {{ site_url }}/brokers/ et change ton mot de passe.",
    ),
    (
        "LIVE_MODE_ENABLED", "SMS",
        "Mode LIVE activé",
        "LeoTrade : le mode LIVE (argent réel) vient d'être activé sur ton compte. "
        "Si ce n'est pas toi, repasse en PAPER immédiatement.",
    ),
    (
        "LIVE_TRADE_CONFIRMATION", "EMAIL",
        "⚠ Trade LIVE : {{ side }} {{ symbol }} — argent réel",
        "Un ordre LIVE va être exécuté sur ton compte broker réel :\n\n"
        "Actif : {{ symbol }}\n"
        "Direction : {{ side }}\n"
        "Montant engagé : {{ stake }} {{ currency }}\n"
        "Stop loss : {{ stop_loss }}\n"
        "Take profit : {{ take_profit }}\n\n"
        "Cet ordre engage de l'argent réel. Si tu n'es pas à l'origine de "
        "cette opération, ouvre {{ site_url }}/trading/orders/ immédiatement.",
    ),
    (
        "KILL_SWITCH_ACTIVATED", "EMAIL",
        "🛑 Kill switch activé — trading bloqué",
        "Le kill switch vient d'être déclenché sur ton portefeuille "
        "« {{ portfolio_name }} ».\n\n"
        "Raison : {{ reason }}\n\n"
        "Plus aucun nouvel ordre ne sera exécuté tant que le kill switch est "
        "actif. Consulte le Centre Risque : {{ site_url }}/trading/hedge-fund/risk/",
    ),
    (
        "KILL_SWITCH_ACTIVATED", "SMS",
        "Kill switch activé",
        "LeoTrade : kill switch déclenché ({{ reason }}). Trading bloqué sur "
        "{{ portfolio_name }}. Détails sur la plateforme.",
    ),
    (
        "DAILY_LOSS_LIMIT", "EMAIL",
        "🛑 Limite de perte journalière atteinte",
        "Ta perte du jour ({{ loss_percent }}%) a atteint la limite configurée "
        "({{ max_loss_percent }}%) sur « {{ portfolio_name }} ».\n\n"
        "Les nouvelles entrées sont bloquées pour aujourd'hui. C'est une "
        "protection : reprends demain à tête reposée, ou ajuste ta limite "
        "dans ton profil de risque si elle ne correspond plus à ta stratégie.",
    ),
    (
        "ORDER_FILLED", "EMAIL",
        "✅ Ordre exécuté : {{ side }} {{ symbol }}",
        "Ton ordre vient d'être exécuté :\n\n"
        "Actif : {{ symbol }}\n"
        "Direction : {{ side }}\n"
        "Quantité : {{ quantity }}\n"
        "Prix moyen : {{ price }}\n"
        "Mode : {{ mode }}\n\n"
        "Suivi de la position : {{ site_url }}/portfolio/",
    ),
    (
        "STOP_LOSS_HIT", "EMAIL",
        "🔻 Stop loss atteint : {{ symbol }}",
        "Ton stop loss a été touché sur {{ symbol }}.\n\n"
        "PnL réalisé : {{ pnl }} {{ currency }}\n\n"
        "Le stop loss a fait son travail : il a limité la perte au montant "
        "que tu avais accepté de risquer.",
    ),
    (
        "TAKE_PROFIT_HIT", "EMAIL",
        "🎯 Take profit atteint : {{ symbol }}",
        "Ton take profit a été touché sur {{ symbol }}.\n\n"
        "PnL réalisé : {{ pnl }} {{ currency }}\n\n"
        "Bien joué — l'objectif de gain est encaissé.",
    ),
    (
        "SECURITY_ALERT", "EMAIL",
        "🔐 Alerte sécurité sur ton compte",
        "{{ message }}\n\n"
        "Si tu n'es pas à l'origine de cette action, change ton mot de passe "
        "immédiatement et contacte le support.",
    ),
]


def seed(apps, schema_editor):
    NotificationTemplate = apps.get_model("notifications", "NotificationTemplate")
    for event_type, channel, subject, body in TEMPLATES:
        NotificationTemplate.objects.update_or_create(
            event_type=event_type,
            channel=channel,
            language="fr",
            defaults={"subject": subject, "body": body, "is_active": True},
        )


def unseed(apps, schema_editor):
    NotificationTemplate = apps.get_model("notifications", "NotificationTemplate")
    NotificationTemplate.objects.filter(
        event_type__in={t[0] for t in TEMPLATES}, language="fr",
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
