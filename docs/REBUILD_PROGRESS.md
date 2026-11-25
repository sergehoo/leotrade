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

### Lot 1 — Socle API v1 ✅
- `api/views/auth.py` + `api/serializers/auth.py` : login, login/mfa, refresh,
  verify, logout, me.
- **MFA non contournable** : allauth.mfa est actif ; une route JWT naïve aurait
  délivré un jeton sur la seule paire email/mot de passe. Connexion en deux temps
  dès qu'un TOTP existe, défi = signature Django de 5 min.
- Email non vérifié refusé (403 `EMAIL_NOT_VERIFIED`), anti-énumération préservée.
- `SIMPLE_JWT` : access 15 min, refresh 14 j, rotation + blacklist.
- `api/pagination.py` : pagination imposée globalement + variante par curseur
  pour les flux chronologiques temps réel.
- Throttling par portée (auth 10/min, sensitive 30/min, ai 20/min), refresh inclus.
- OpenAPI : `/api/v1/schema/`, `/docs/`, `/redoc/`.
- **16 tests** (`tests_phase/test_api_auth.py`).

### Lot 2 — Contexte applicatif + socle web React ✅
**Backend**
- `core/services_context.py` : la résolution du mode PAPER/LIVE vivait dans un
  context processor, donc inaccessible hors template. Remontée en service ;
  le context processor délègue. Une seule vérité sur « suis-je en réel ? ».
- `GET /api/v1/context/` : portefeuille par défaut, portefeuille électronique,
  mode de trading, kill switch de plateforme.
- **9 tests** (`tests_phase/test_api_context.py`), dont : le client ne peut pas
  forcer son mode, et aucun secret broker ne fuit dans la réponse.

**Web**
- Vite 8 + React 19 + TypeScript 7 + Tailwind 4 + Radix. Proxy dev `/api` et
  `/ws` vers Django (same-origin, pas de CORS en développement).
- Système de design : sombre par défaut, **vert et rouge réservés au P&L** —
  jamais de vert décoratif. Paliers d'instrument CORE/VOLATILE/SPÉCULATIF
  alignés sur `risk/instruments.py`.
- Client axios : refresh JWT automatique, **mutualisé** (une seule requête de
  refresh en vol). Sans cela, la rotation côté serveur ferait tomber la session
  dès que deux appels concurrents rencontrent un access expiré.
- Composants d'état vide / erreur / chargement traités en première classe
  (règle « zéro donnée fictive » : un écran vide explique pourquoi il est vide).
- Connexion avec étape MFA, route protégée, coque applicative, tableau de bord.
- **Validé au navigateur** : connexion, rendu, restauration de session après
  rechargement. Un bug réel a été trouvé et corrigé à cette occasion —
  l'exclusion `/auth/` de l'intercepteur empêchait le refresh sur `/auth/me/`,
  donc la session ne survivait pas au rechargement.

### Lot 3 — Portage fonctionnel ⏳
Prochain. Voir la matrice et l'ordre de bataille ci-dessous.

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

Voir **[docs/FUNCTIONAL_MATRIX.md](FUNCTIONAL_MATRIX.md)** — contrat de
non-régression, généré par cartographie parallèle (10 agents + 1 agent de
complétude, 0 échec).

### Le chiffre qui commande le plan

| État de l'API | Fonctionnalités | Part |
|---|---:|---:|
| Déjà consommable en REST | 49 | 14 % |
| Partiellement exposé | 79 | 23 % |
| **Vue Django uniquement** | **212** | **62 %** |

**340 fonctionnalités** au total, dont 93 en temps réel et 241 à porter sur mobile.

> L'essentiel du travail n'est pas de redessiner des écrans : c'est de
> **remonter la logique métier des vues Django vers des services et une API**.
> Refaire le front avant d'exposer le back produirait une coquille vide.

### Points durs identifiés

1. **Mode PAPER/LIVE en session** — résolu au Lot 2 (`core/services_context.py`).
2. **Multi-devise sans table de change** — dépôts acceptés en XOF, NGN, GHS, KES,
   ZAR, USD, EUR alors que les portefeuilles sont en USD, et aucune règle de
   conversion n'existe. À trancher avant d'ouvrir les dépôts non-USD.
3. **Plafonds monétaires codés en dur** (`wallet/form.py`) — à remonter en
   configuration serveur, par palier KYC.
4. **Décimales** — le backend calcule en `Decimal`. Ni TypeScript ni Dart n'ont
   d'équivalent natif : les montants doivent transiter en chaîne et ne jamais
   être reconvertis en `number`/`double` pour un calcul.
5. **Médias sur disque local** (`MEDIA_ROOT`) — incompatible avec plusieurs
   instances derrière Dokploy. Documents KYC et pièces jointes concernés.
6. **`trading/admin.py` entièrement commenté** — aucun back-office pour les
   17 modèles de trading.
7. **Kill switch de plateforme** (`core/feature_flags.py`) — exposé au Lot 2.

### Ordre de bataille proposé pour le Lot 3

Par valeur décroissante et dépendances :

1. **Brokers** — rien ne fonctionne sans compte broker connecté. 23 fonctions,
   2 prêtes. Jamais exposer les secrets.
2. **Portefeuille et positions** — 28 fonctions, 5 prêtes. Cœur de l'usage quotidien.
3. **Risque** — 29 fonctions, 8 prêtes. Le mieux couvert ; à exposer avant
   l'exécution, car il la conditionne.
4. **Exécution et trading** — 46 fonctions, 7 prêtes. Le plus sensible.
5. **Portefeuille électronique** — 31 fonctions, 4 prêtes, 0 partielles :
   le domaine le moins exposé, et il touche à l'argent réel.
6. **Assistant IA** — 44 fonctions, 14 prêtes. Le mieux amorcé.
7. **Marchés et stratégies** — 41 fonctions, 0 prête.
8. **Notifications et temps réel** — 36 fonctions, transverse aux précédents.
