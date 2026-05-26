"""
Migration 0004 — recrée la table `brokers_brokerexternalref` si elle n'existe
plus en DB.

Contexte : la migration 0003 a été générée automatiquement par makemigrations
et a supprimé la table parce que le modèle n'était pas chargé par
brokers/models.py (le fichier modèle vit dans brokers/models_external_ref.py).
Elle a depuis été neutralisée (operations vides) MAIS l'ancienne version a
déjà été appliquée sur la base, donc la table a été DROP côté DB.

Django, lui, considère que 0002 + 0003 sont appliquées, donc le state interne
contient toujours BrokerExternalRef → makemigrations ne propose rien.

Solution : SeparateDatabaseAndState avec un RunSQL idempotent
(CREATE TABLE IF NOT EXISTS + CREATE * IF NOT EXISTS pour les index).

Cette migration est sûre à appliquer même si la table existe déjà.
"""

from django.db import migrations


SQL_FORWARD = """
CREATE TABLE IF NOT EXISTS "brokers_brokerexternalref" (
    "id"            serial NOT NULL PRIMARY KEY,
    "broker"        varchar(20)  NOT NULL,
    "kind"          varchar(30)  NOT NULL,
    "external_id"   varchar(120) NOT NULL,
    "internal_kind" varchar(30)  NOT NULL,
    "internal_id"   varchar(64)  NOT NULL,
    "last_status"   varchar(40)  NOT NULL DEFAULT '',
    "last_payload"  jsonb        NOT NULL DEFAULT '{}'::jsonb,
    "last_seen_at"  timestamptz  NOT NULL DEFAULT NOW(),
    "created_at"    timestamptz  NOT NULL DEFAULT NOW(),
    "broker_account_id" integer  NOT NULL
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'brokers_brokerextern_broker_account_id_fk_brokers_brokeraccount'
    ) THEN
        ALTER TABLE "brokers_brokerexternalref"
            ADD CONSTRAINT "brokers_brokerextern_broker_account_id_fk_brokers_brokeraccount"
            FOREIGN KEY ("broker_account_id")
            REFERENCES "brokers_brokeraccount" ("id")
            ON DELETE CASCADE
            DEFERRABLE INITIALLY DEFERRED;
    END IF;
END
$$;

-- Contrainte d'unicité (clé d'idempotence) — via index unique pour pouvoir IF NOT EXISTS
CREATE UNIQUE INDEX IF NOT EXISTS "uniq_broker_external_ref"
    ON "brokers_brokerexternalref" ("broker", "kind", "external_id");

-- Index secondaires
CREATE INDEX IF NOT EXISTS "brokers_bro_interna_b50d8f_idx"
    ON "brokers_brokerexternalref" ("internal_kind", "internal_id");

CREATE INDEX IF NOT EXISTS "brokers_bro_broker__c20e6f_idx"
    ON "brokers_brokerexternalref" ("broker_account_id", "kind");

CREATE INDEX IF NOT EXISTS "brokers_brokerexternalref_broker_account_id_idx"
    ON "brokers_brokerexternalref" ("broker_account_id");

CREATE INDEX IF NOT EXISTS "brokers_brokerexternalref_broker_idx"
    ON "brokers_brokerexternalref" ("broker");

CREATE INDEX IF NOT EXISTS "brokers_brokerexternalref_kind_idx"
    ON "brokers_brokerexternalref" ("kind");

CREATE INDEX IF NOT EXISTS "brokers_brokerexternalref_external_id_idx"
    ON "brokers_brokerexternalref" ("external_id");

CREATE INDEX IF NOT EXISTS "brokers_brokerexternalref_internal_kind_idx"
    ON "brokers_brokerexternalref" ("internal_kind");

CREATE INDEX IF NOT EXISTS "brokers_brokerexternalref_internal_id_idx"
    ON "brokers_brokerexternalref" ("internal_id");
"""


SQL_REVERSE = """
-- Reverse : on garde la table en place (la suppression était précisément la
-- régression qu'on essaie de corriger). On retombe sur 0003 qui est noop.
"""


class Migration(migrations.Migration):

    dependencies = [
        ("brokers", "0003_delete_brokerexternalref"),
    ]

    operations = [
        # SeparateDatabaseAndState : on touche UNIQUEMENT la base de données.
        # Le state Django reste inchangé (BrokerExternalRef est déjà dans le
        # state via les fichiers 0002 + 0003 noop).
        migrations.SeparateDatabaseAndState(
            state_operations=[],
            database_operations=[
                migrations.RunSQL(
                    sql=SQL_FORWARD,
                    reverse_sql=SQL_REVERSE,
                    elidable=False,
                ),
            ],
        ),
    ]
