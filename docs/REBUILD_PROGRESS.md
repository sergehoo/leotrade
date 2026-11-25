# Refonte LeoTrade — React + Flutter

Branche : `refonte/react-flutter`
Fichier de reprise entre sessions. **Mettre à jour à chaque lot commité.**

---

## Cible

| Couche | Stack |
|---|---|
| Backend | Django 4.2 + DRF, PostgreSQL, Redis, Celery, Channels (ASGI/Daphne) |
| Web | React + TypeScript + Vite + Tailwind + shadcn/ui |
| Mobile | Flutter (Android/iOS), Riverpod, Dio, GoRouter |
| API | REST versionnée `/api/v1/`, OpenAPI, WebSocket pour le temps réel |

## Arborescence monorepo

```
backend/          Django (apps, templates legacy, static legacy, tests_phase)
web/              React
mobile/           Flutter
infrastructure/   docker/ (Dockerfile, docker-compose.yml), deploy/ (env, runbook, observability)
docs/             documentation + ce fichier
scripts/          quality.mjs (gate `npm run check` / `npm test`, cwd = backend/)
```

`venv/` reste à la racine. Commandes backend : `cd backend && ../venv/bin/python manage.py …`

---

## Périmètre repris — 80 modèles métier, 15 apps

`execution` (6) · `core` (1) · `market` (4) · `brokers` (4) · `strategies` (7) · `portfolio` (7)
`risk` (9) · `trading` (17) · `leo_backtesting` (1) · `dashboard` (1) · `wallet` (9)
`notifications` (4) · `ai_engine` (1) · `ai_assistant` (8) · `accounting` (1)

---

## Journal des lots

### Lot 0 — Restructuration monorepo ✅
- Django déplacé sous `backend/` via `git mv` (historique préservé).
- `infrastructure/docker/` : Dockerfile (contexte = racine monorepo, `COPY backend/`), docker-compose.
- `infrastructure/deploy/` : gabarits d'environnement, runbook, scripts, règles d'alerte Prometheus.
- `scripts/quality.mjs` : `cwd` pointé sur `backend/`.
- CI `.github/workflows/production-ci.yml` : chemins mis à jour.
- Tests d'infra (`test_production_readiness`, `test_operational_monitoring`) : constantes de chemin
  rebasées sur `INFRA_ROOT`.
- **Vérifié : `manage.py check` OK, 439 tests passés / 1 skippé.**

### Lot 1 — Socle API v1 ⏳
À venir.

---

## Règles de la refonte

1. **Aucune régression fonctionnelle.** La matrice fonctionnelle (ci-dessous, en cours
   de constitution) est le contrat. Toute fonctionnalité retirée doit être justifiée et validée.
2. **Zéro donnée fictive.** Pas de mock, pas d'écran de démo, pas de bouton inerte en production.
   Les états vides sont explicites et expliqués.
3. **Logique métier dans les services Django**, jamais dans les vues, les serializers ou le front.
4. **Pas de modification destructive de la base de production.** Migrations réversibles,
   sauvegarde avant bascule.
5. **Mutualisation** : un composant par usage, pas de duplication de règle métier entre web et mobile.

---

## Matrice fonctionnelle

> En cours de constitution (cartographie parallèle des 10 domaines).
> Sera insérée ici avant le démarrage du Lot 1.
