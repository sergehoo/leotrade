"""
Migration 0004 — recrée la table `portfolio_trade` si elle n'existe plus en DB.

Même cause que brokers/0004 : la migration 0003_delete_trade a été
auto-générée (modèle pas chargé par portfolio/models.py) puis appliquée,
ce qui a DROP la table en DB. Elle a depuis été neutralisée mais la table
reste à recréer côté base.

Idempotente : sûre à appliquer même si la table existe déjà.
"""

from django.db import migrations


SQL_FORWARD = """
CREATE TABLE IF NOT EXISTS "portfolio_trade" (
    "id"                 serial NOT NULL PRIMARY KEY,
    "broker_fill_id"     varchar(120),
    "symbol"             varchar(50)  NOT NULL,
    "side"               varchar(10)  NOT NULL,
    "quantity"           numeric(24, 8) NOT NULL,
    "entry_avg_price"    numeric(24, 8) NOT NULL,
    "exit_avg_price"     numeric(24, 8) NOT NULL,
    "gross_pnl"          numeric(18, 2) NOT NULL DEFAULT 0,
    "fees"               numeric(18, 2) NOT NULL DEFAULT 0,
    "realized_pnl"       numeric(18, 2) NOT NULL,
    "cash_invested"      numeric(18, 2) NOT NULL DEFAULT 0,
    "cash_returned"      numeric(18, 2) NOT NULL DEFAULT 0,
    "opened_at"          timestamptz NOT NULL,
    "closed_at"          timestamptz NOT NULL DEFAULT NOW(),
    "metadata"           jsonb NOT NULL DEFAULT '{}'::jsonb,
    "created_at"         timestamptz NOT NULL DEFAULT NOW(),
    "broker_account_id"  integer NOT NULL,
    "closing_fill_id"    integer,
    "opening_order_id"   integer,
    "portfolio_id"       integer NOT NULL,
    "position_id"        integer
);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'portfolio_trade_broker_account_id_fk') THEN
        ALTER TABLE "portfolio_trade"
            ADD CONSTRAINT "portfolio_trade_broker_account_id_fk"
            FOREIGN KEY ("broker_account_id") REFERENCES "brokers_brokeraccount" ("id")
            DEFERRABLE INITIALLY DEFERRED;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'portfolio_trade_portfolio_id_fk') THEN
        ALTER TABLE "portfolio_trade"
            ADD CONSTRAINT "portfolio_trade_portfolio_id_fk"
            FOREIGN KEY ("portfolio_id") REFERENCES "portfolio_portfolio" ("id")
            ON DELETE CASCADE
            DEFERRABLE INITIALLY DEFERRED;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'portfolio_trade_position_id_fk') THEN
        ALTER TABLE "portfolio_trade"
            ADD CONSTRAINT "portfolio_trade_position_id_fk"
            FOREIGN KEY ("position_id") REFERENCES "portfolio_position" ("id")
            ON DELETE SET NULL
            DEFERRABLE INITIALLY DEFERRED;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'portfolio_trade_opening_order_id_fk') THEN
        ALTER TABLE "portfolio_trade"
            ADD CONSTRAINT "portfolio_trade_opening_order_id_fk"
            FOREIGN KEY ("opening_order_id") REFERENCES "execution_order" ("id")
            ON DELETE SET NULL
            DEFERRABLE INITIALLY DEFERRED;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'portfolio_trade_closing_fill_id_fk') THEN
        ALTER TABLE "portfolio_trade"
            ADD CONSTRAINT "portfolio_trade_closing_fill_id_fk"
            FOREIGN KEY ("closing_fill_id") REFERENCES "execution_executionfill" ("id")
            ON DELETE SET NULL
            DEFERRABLE INITIALLY DEFERRED;
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS "portfolio_t_portfol_a3b1c2_idx"
    ON "portfolio_trade" ("portfolio_id", "closed_at");
CREATE INDEX IF NOT EXISTS "portfolio_t_portfol_e90df3_idx"
    ON "portfolio_trade" ("portfolio_id", "symbol");
CREATE INDEX IF NOT EXISTS "portfolio_t_broker__c4ee21_idx"
    ON "portfolio_trade" ("broker_account_id");
CREATE INDEX IF NOT EXISTS "portfolio_trade_broker_fill_id_idx"
    ON "portfolio_trade" ("broker_fill_id");
CREATE INDEX IF NOT EXISTS "portfolio_trade_symbol_idx"
    ON "portfolio_trade" ("symbol");
CREATE INDEX IF NOT EXISTS "portfolio_trade_opened_at_idx"
    ON "portfolio_trade" ("opened_at");
CREATE INDEX IF NOT EXISTS "portfolio_trade_closed_at_idx"
    ON "portfolio_trade" ("closed_at");
"""

SQL_REVERSE = """
-- Reverse : on conserve la table (la suppression était la régression à corriger).
"""


class Migration(migrations.Migration):

    dependencies = [
        ("portfolio", "0003_delete_trade"),
        ("brokers", "0004_recreate_broker_external_ref"),
        ("execution", "0001_initial"),
    ]

    operations = [
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
