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

### Lot 3 — Socle mobile Flutter ✅
- Flutter 3.38 / Dart 3.10, Riverpod, Dio, GoRouter, `flutter_secure_storage`.
- **Jetons dans le Keychain / Keystore**, jamais dans SharedPreferences :
  sur un appareil rooté, SharedPreferences se lit en clair, et un refresh
  token vaut un accès complet au compte pendant quatorze jours. L'access
  reste en mémoire (15 min de durée de vie).
- Client Dio miroir du web : rafraîchissement JWT mutualisé, mêmes routes
  exclues (`login`, `login/mfa`, `refresh` — et surtout **pas** `/auth/me/`).
- Montants transportés en `String` de bout en bout : le backend calcule en
  `Decimal`, Dart n'a pas d'équivalent natif, et un arrondi binaire sur un
  solde est une erreur comptable. Conversion en `double` au seul affichage.
- `Capabilities.closed` : en l'absence d'information serveur, aucune capacité
  n'est ouverte. Un défaut permissif, c'est un ordre réel passé sans droit.
- Thème miroir du web (vert/rouge réservés au P&L), interface en français.
- Connexion avec étape MFA, reprise de session, tableau de bord.
- `flutter analyze` propre, **8 tests** passés.

### Lot 4 — Portage fonctionnel ⏳
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

---

## Lot 4 — Brokers (terminé)

Premier domaine métier porté de bout en bout : service → API → React → Flutter.

### Ce qui a été remonté

`brokers/services_accounts.py` devient la source unique des règles du cycle
de vie d'un compte broker. Les deux surfaces (API v1 et vues Django) y
appellent les mêmes gardes — c'était la condition pour ne pas laisser
diverger ce qui touche à l'argent réel.

| Règle | Où elle vit |
|---|---|
| Présence d'un secret, jamais sa valeur | `secret_status` / `missing_secrets` |
| KYC approuvé obligatoire pour LIVE | `assert_live_allowed` |
| Un seul compte par défaut | `set_default`, sous verrou de ligne |
| Pas de suppression d'un compte engagé | `assert_deletable` |
| Test de connexion + état + notification | `test_connection` |
| Masquage des secrets dans les erreurs | `redact_secrets` |

### API exposée

`/api/v1/brokers/` — CRUD complet, plus `set-default/`, `test-connection/`,
`sync-constraint/`, `health/`. Les trois premières sous le throttle
« sensitive ». Codes d'erreur stables : `KYC_REQUIRED`, `MISSING_SECRETS`,
`OPEN_POSITIONS`, `LINKED_PORTFOLIOS`, `CONNECTION_FAILED`, `SYNC_FAILED`.
Un broker injoignable renvoie 502, pas 500.

### Trois failles fermées en passant

1. **`IsOwner` ne demandait pas l'authentification.** Les ViewSets qui la
   déclarent remplacent la permission par défaut du projet ; une requête
   anonyme franchissait `has_permission` puis atteignait `get_queryset()`,
   où `filter(user=AnonymousUser)` lève un `TypeError` — 500 au lieu de 401.
   Concernait tous les ViewSets, pas seulement les brokers.

2. **La bascule PAPER→LIVE n'avait aucune garde KYC.** Un compte non vérifié
   pouvait passer tous ses brokers en LIVE depuis le sidebar, alors que l'API
   annonce `can_trade_live=false`. Le retour en PAPER reste toujours ouvert :
   on ne verrouille pas la porte de sortie.

3. **`last_connection_error` persistait la chaîne brute du broker**, que
   l'API servait ensuite. Un broker qui renvoie la valeur soumise dans son
   message (« Invalid API key: AK-… ») faisait ressortir un secret par le
   chemin le moins surveillé.

### Vérification

- 516 tests backend (1 ignoré) — dont 47 sur ce domaine, les assertions de
  non-fuite portant sur toutes les routes **et sur le contrat OpenAPI**.
- 18 tests Flutter, `flutter analyze` propre, build web OK.
- Parcours validé au navigateur : refus serveur en Live avec motif KYC,
  création acceptée en Paper, test de connexion réel contre Deriv dont
  l'échec 401 s'affiche tel quel. Aucune réponse HTTP ne porte la valeur
  du jeton soumis (vérifié dans le panneau réseau).

### Ce que ce lot ne couvre pas

- Aucun temps réel : l'état du circuit est lu par sondage (30 s côté web).
- `sync-constraint/` est exposé mais sans écran ; les contraintes
  d'instrument seront pilotées depuis le domaine Marchés.
- La rotation planifiée des secrets (`BrokerCredential.rotated_at` existe,
  rien ne l'écrit).

### Suite — Lot 5 : portefeuille et positions

28 fonctions, 5 prêtes. Dépend du Lot 4 : une position appartient à un
portefeuille, lui-même rattaché à un compte broker.

---

## Lot 5 — Portefeuille, positions, et parcours d'accueil

### Le blocage levé

Un portefeuille exige un compte broker, et un compte broker exigeait un
courtier réel. Un nouvel utilisateur arrivait donc sur un tableau de bord
vide dont la seule issue était d'ouvrir un compte chez un tiers — avant
même d'avoir pu regarder la plateforme.

`POST /api/v1/portfolios/provision-paper/` provisionne en un appel une
place d'exécution locale (`SIMULATION`, mode PAPER), un portefeuille et
son capital de départ. Le routage d'exécution se faisant sur le **mode**
et non sur le broker (cf. `execution.adapters.factory`), ces comptes
empruntent le `PaperBrokerAdapter` comme n'importe quel autre.

Trois gardes empêchent cette porte de devenir une porte dérobée :
`BrokerAccount.clean()` refuse un compte SIMULATION en LIVE,
`assert_mode_allowed` le refuse côté service, et `trading_mode_toggle`
saute ces comptes lors d'une bascule globale.

### Un bug de double comptage, trouvé au navigateur

La première version créditait le capital À LA FOIS sur
`starting_balance` et comme écriture de grand livre. Or
`recompute_cash_state` calcule `starting_balance + Σ(écritures)` : un
portefeuille de 10 000 affichait 20 000.

Le test initial vérifiait qu'une écriture existait — il passait. C'est la
vérification au navigateur qui a montré le chiffre faux. Le test figé
désormais assert le **solde résultant**, pas la présence d'une écriture.

Le capital d'ouverture n'est pas une transaction : c'est la ligne de
départ des mouvements, et le dénominateur de la performance.

### Exposé

| Route | Contenu |
|---|---|
| `/portfolios/provision-paper/` | parcours d'accueil en un appel |
| `/portfolios/{id}/summary/` | P&L latent/réalisé, exposition, répartition |
| `/positions/?trading_mode=` | séparation stricte simulation / réel |

`PortfolioSummaryService` centralise les agrégats : les trois surfaces en
calculaient chacune leur version, et faire diverger un chiffre de P&L est
la manière la plus sûre de perdre la confiance de l'utilisateur.

Tous les montants sortent en chaîne. Le backend calcule en `Decimal` ; ni
TypeScript ni Dart n'ont d'équivalent natif.

### Écrans

React et Flutter : sélecteur de portefeuille, synthèse, tableau des
positions ouvertes, état vide explicite, parcours de création. Le mode
est affiché partout où un portefeuille est nommé — c'est lui qui décide
si un ordre engage de l'argent réel.

### Vérification

561 tests backend (1 ignoré), 25 Flutter, build web OK, parcours validé
au navigateur : création, capital correct, état vide des positions.

### Reste à faire sur ce domaine

- Clôture de position depuis l'interface (le service existe, pas l'écran).
- Historique des positions fermées et des mouvements de trésorerie.
- Graphique d'évolution de la valorisation (les snapshots existent).

---

## Lot 6 — Risk Control

### Une faille de cloisonnement, reproduite avant correction

`RiskProfileSerializer` exposait `portfolio` en écriture sans vérifier
l'appartenance. `perform_create` fixait bien `user=request.user`, mais la
clé étrangère venait du corps de la requête.

Reproduction : un compte tiers crée un `RiskProfile` sur le portefeuille
d'une victime, `max_risk_per_trade=99%`, et le serveur répond **201**. Le
profil injecté arrivant avec `is_default=True`, il devient celui que le
moteur applique — un inconnu réécrit les limites de sécurité d'un autre
utilisateur.

`PortfolioAllocationSerializer` portait la même faille.

Le correctif est une classe partagée, `api.fields.OwnedRelatedField`, qui
**filtre le queryset** au lieu de valider après coup : DRF rend alors la
même erreur qu'un identifiant inexistant, sans révéler que l'objet existe
et appartient à quelqu'un d'autre.

### Capital Preservation : rendue visible

Quatre champs du modèle n'étaient dans aucun contrat d'API :
`preservation_mode`, `allow_volatile_instruments`,
`allow_speculative_instruments`, `max_monthly_loss`. La principale
protection du capital était donc invisible et non modifiable depuis les
clients, alors qu'elle s'applique par défaut.

Le profil de risque est désormais créé au provisionnement, pas
paresseusement : l'utilisateur voit ses limites dès l'arrivée.

### Synthèse

`GET /risk-utils/summary/{portfolio_id}/` — limites, consommation,
drawdown, kill switch, politique de préservation.

Le chiffre exposé est le **taux d'utilisation**, pas la limite brute :
savoir que la limite journalière est à 3 % n'apprend rien ; savoir qu'on
en a consommé 80 % change la décision. Une limite non posée rend
`usage_percent = null` plutôt que 0 — afficher « 0 % utilisé » laisserait
croire à une protection qui n'existe pas.

### Écrans

Jauges colorées par consommation (verte, orange à 75 %, rouge au
franchissement), bannière d'arrêt d'urgence avec son motif, et pilotage
des trois drapeaux de préservation. Lever un arrêt d'urgence demande une
confirmation explicite rappelant que la cause ne disparaît pas.

### Vérification

583 tests backend (1 ignoré), 36 Flutter, build web OK. Validé au
navigateur — y compris un drawdown à 50 % correctement signalé
« Dépassée », qui s'est révélé être l'artefact du bug de double comptage
du Lot 5 persisté dans `max_equity`.

### Reste à faire sur ce domaine

- Édition des seuils chiffrés (seuls les drapeaux de préservation sont
  pilotables depuis l'interface).
- Historique des décisions de risque et des déclenchements.
- Les points de l'audit Capital Preservation non traités : plafonds
  d'exposition par classe déclarés mais non consommés, case d'override
  unique levant tous les blocages SOUPLES en LIVE, `RiskOverrideAudit`
  écrit seulement à l'approbation.
