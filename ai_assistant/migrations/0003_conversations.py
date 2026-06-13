"""
Chat persistant — AssistantSession devient AssistantConversation.

RenameModel + RenameField préservent toutes les données existantes
(sessions et messages déjà en base). Ajouts : titre, contexte métier,
archivage, statut de message, participants (futur mode équipe) et
pièces jointes (futur upload).
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("ai_assistant", "0002_quota_billing"),
        ("portfolio", "0001_initial"),
    ]

    operations = [
        # ── Renommages (préservent les données) ──────────────────────────
        migrations.RenameModel(
            old_name="AssistantSession",
            new_name="AssistantConversation",
        ),
        migrations.RenameField(
            model_name="assistantmessage",
            old_name="session",
            new_name="conversation",
        ),

        migrations.RenameIndex(
            model_name="assistantconversation",
            old_name="ai_assistan_user_id_09d773_idx",
            new_name="ai_assistan_user_id_52ff2e_idx",
        ),

        # ── Conversation : contexte métier + archivage ───────────────────
        migrations.AddField(
            model_name="assistantconversation",
            name="title",
            field=models.CharField(blank=True, help_text="Auto-généré depuis le premier message si vide.", max_length=200),
        ),
        migrations.AddField(
            model_name="assistantconversation",
            name="context_type",
            field=models.CharField(
                choices=[
                    ("GENERAL", "Assistant général"), ("DASHBOARD", "Dashboard"),
                    ("TRADE_IDEA", "Trade Idea"), ("POSITION", "Position"),
                    ("ORDER", "Ordre"), ("PORTFOLIO", "Portefeuille"),
                    ("BROKER", "Broker"), ("SIGNAL", "Signal"),
                    ("OPPORTUNITY", "Opportunité IA"),
                ],
                db_index=True, default="GENERAL", max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="assistantconversation",
            name="context_id",
            field=models.PositiveIntegerField(blank=True, db_index=True, help_text="ID de l'objet métier (trade idea, position…).", null=True),
        ),
        migrations.AddField(
            model_name="assistantconversation",
            name="archived",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddIndex(
            model_name="assistantconversation",
            index=models.Index(fields=["user", "context_type", "context_id"], name="ai_assistan_user_id_1c3cee_idx"),
        ),
        migrations.AddIndex(
            model_name="assistantconversation",
            index=models.Index(fields=["user", "archived", "-updated_at"], name="ai_assistan_user_id_c66b03_idx"),
        ),

        # ── Message : statut + erreurs + updated_at ──────────────────────
        migrations.AddField(
            model_name="assistantmessage",
            name="status",
            field=models.CharField(
                choices=[("SAVED", "Sauvegardé"), ("PARTIAL", "Partiel"), ("FAILED", "Échec")],
                db_index=True, default="SAVED", max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="assistantmessage",
            name="error_message",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="assistantmessage",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AlterField(
            model_name="assistantmessage",
            name="content",
            field=models.TextField(blank=True),
        ),
        migrations.AddIndex(
            model_name="assistantmessage",
            index=models.Index(fields=["conversation", "created_at"], name="ai_assistan_convers_e1f86d_idx"),
        ),
        migrations.AddIndex(
            model_name="assistantmessage",
            index=models.Index(fields=["status"], name="ai_assistan_status_241469_idx"),
        ),

        # ── Participants (futur mode équipe) ─────────────────────────────
        migrations.CreateModel(
            name="AssistantConversationParticipant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(choices=[("OWNER", "Propriétaire"), ("MEMBER", "Membre"), ("VIEWER", "Lecture seule")], default="OWNER", max_length=10)),
                ("joined_at", models.DateTimeField(auto_now_add=True)),
                ("conversation", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="participants", to="ai_assistant.assistantconversation")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="assistant_participations", to=settings.AUTH_USER_MODEL)),
            ],
            options={"unique_together": {("conversation", "user")}},
        ),

        # ── Pièces jointes (futur upload) ────────────────────────────────
        migrations.CreateModel(
            name="AssistantAttachment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("file", models.FileField(upload_to="assistant/attachments/%Y/%m/")),
                ("filename", models.CharField(max_length=255)),
                ("content_type", models.CharField(blank=True, max_length=100)),
                ("size_bytes", models.PositiveBigIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("conversation", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="attachments", to="ai_assistant.assistantconversation")),
                ("message", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="attachments", to="ai_assistant.assistantmessage")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="assistant_attachments", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
