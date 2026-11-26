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

---

## Lot 7 — Leo, assistant transversal

### Ce qui existait déjà

Leo n'était pas à écrire : 4 889 lignes dans `ai_assistant/`, avec
streaming WebSocket (`thinking` / `chunk` / `done`), conversations
persistées, flux de confirmation d'action, quotas et outils. Rien n'était
atteignable depuis React ou Flutter.

### Le blocage : l'authentification du WebSocket

`AuthMiddlewareStack` de Channels ne lit qu'un cookie de session. React
porte son JWT en mémoire, Flutter n'a aucun cookie : toutes les
connexions temps réel — assistant, notifications, exécution,
portefeuille, marché — étaient fermées en 4401.

`core/ws_auth.py` authentifie par jeton porté dans le **sous-protocole**.
Pas dans la chaîne de requête : un `?token=` figure dans les journaux
d'accès du serveur, des proxies et des CDN, où il survit bien au-delà de
ses 15 minutes de validité. `Sec-WebSocket-Protocol` n'est pas
journalisé, et c'est le seul en-tête qu'un navigateur laisse définir à
l'ouverture d'un WebSocket.

### Deux défauts que seul le test de bout en bout a révélés

1. Composer `JWTAuthMiddleware(AuthMiddlewareStack(inner))` **annulait**
   l'authentification : `AuthMiddleware` écrase `scope["user"]` par un
   objet paresseux résolu depuis la session. Le chemin JWT court-circuite
   désormais la pile session.
2. Les sous-protocoles étaient lus dans les en-têtes bruts. La
   spécification ASGI les expose dans `scope["subprotocols"]`, déjà
   découpés — c'est ce que fournissent Daphne et Uvicorn. La lecture
   renvoyait une liste vide et toutes les connexions JWT retombaient sur
   la session.

Les tests unitaires traversent la même composition qu'en production :
tester le middleware isolément aurait masqué le premier défaut.

### Transversalité

Leo est monté dans l'`AppShell` React et accessible depuis chaque écran
Flutter, pas enfermé dans une route. Il sert à commenter ce que
l'utilisateur regarde ; l'y obliger à quitter l'écran dont il veut parler
viderait la fonctionnalité de son sens. Le chemin courant est transmis
comme contexte à chaque message.

### Rendu et garde-fous

Le Markdown est rendu en **éléments React**, sans
`dangerouslySetInnerHTML` : le texte vient d'un modèle de langage, qui
peut restituer n'importe quoi, y compris du contenu tiers remonté par un
outil. L'injection devient structurellement impossible plutôt que
filtrée. Les liens non-`http(s)` ne deviennent pas cliquables.

Les actions proposées exigent un geste explicite — l'assistant propose,
il ne dispose pas. Un statut absent est traité comme « en attente »,
jamais comme « exécuté ».

### Vérification

593 tests backend (1 ignoré), 46 Flutter, build web OK. Validé au
navigateur : le panneau affiche « Leo — En ligne » et le serveur
enregistre `WebSocket CONNECT /ws/assistant/chat/`, hors harnais de test.

**Aucun message n'a été envoyé à un modèle** : le fournisseur configuré
est DeepSeek, avec une clé active. Un test de génération ferait un appel
payant sur le compte du propriétaire du projet.

### Reste à faire sur ce domaine

- Interaction vocale, pièces jointes, graphiques interactifs dans les
  réponses (le modèle `AssistantAttachment` existe, rien ne l'alimente
  depuis les nouveaux clients).
- Reprise d'une conversation précise depuis l'historique.
- Vérification que les sources citées par Leo sont réellement
  rattachées à des données consultables.

---

## Lot 8 — Marchés

### Ce que la base a révélé

46 instruments, 248 438 bougies — et la plus récente datée du
**13 juin 2026**, soit plus de cinq mois. Tous les instruments déclarent
pourtant `market_status = "OPEN"`, valeur par défaut que rien ne met à
jour.

Deux signaux faux, donc, sur la donnée la plus sensible de la
plateforme. Afficher ces cours sans leur âge, c'est laisser décider sur
un prix de juin en croyant lire celui du jour.

### La fraîcheur comme contrat, pas comme décoration

`Asset` ne porte aucun prix : le cours se déduit de la dernière bougie.
`MarketQuoteService` le rend donc toujours accompagné de :

| Champ | Rôle |
|---|---|
| `as_of` | horodatage de la bougie dont le prix est tiré |
| `age_seconds` | ancienneté |
| `freshness` | LIVE / DELAYED / STALE / NO_DATA |
| `source` | place d'où vient le chiffre |
| `declared_market_status` | statut porté par l'instrument, nommé « déclaré » |
| `is_tradable_quote` | faux dès que la cotation n'est plus à jour |

Les seuils sont **relatifs à l'unité de temps** : une bougie journalière
vieille de deux jours est normale, une bougie d'une minute vieille de
deux jours ne l'est pas.

Un instrument sans donnée rend `price: null`, jamais `0` — un zéro est
un prix.

### Un défaut d'affichage attrapé par les tests

`Decimal.normalize()` rendait `1E+2` pour `100.00`. Les clients auraient
affiché cette chaîne telle quelle. Les montants sont désormais formatés
en virgule fixe, zéros de fin retirés à la main.

### Exposé

| Route | |
|---|---|
| `/market/assets/` | catalogue, recherche, filtres par classe |
| `/market/assets/quotes/` | cotations paginées — la pagination précède le calcul, chaque cotation coûtant deux requêtes |
| `/market/assets/{id}/candles/` | historique borné à 1000 bougies |
| `/market/watchlist/` | liste de suivi, idempotente au second « suivre » |

### Écrans

React et Flutter : recherche, filtres, liste de cotations où chaque ligne
porte sa pastille de fraîcheur **et sa date**. Une pastille seule
laisserait deviner ce que « périmé » veut dire — un jour ? cinq mois ?
Un cours périmé est grisé et un bandeau compte combien de lignes sont
concernées.

### Vérification

616 tests backend (1 ignoré), 55 Flutter, build web OK. Validé au
navigateur : BTCUSDT affiche 66 385,83 avec le badge rouge « Périmé » et
la date 29/03/26 ; les instruments sans bougie affichent « Aucune
donnée » et un tiret en variation.

### Reste à faire sur ce domaine

- Graphiques interactifs (l'historique est exposé, `lightweight-charts`
  est déjà en dépendance, rien ne l'utilise).
- Fiche instrument détaillée.
- BRVM : aucune source n'est branchée, et le dépôt ne documente aucun
  fournisseur pour cette place.
- Rafraîchissement temps réel des cotations par WebSocket
  (`market/routing.py` existe, le consumer n'est pas consommé).

---

## Lot 9 — Portefeuille électronique

C'est le domaine qui touche à l'argent réel. Deux principes l'ont
gouverné.

### Aucune route ne déclenche de flux financier

Les dépôts ne sont **pas** initiables depuis l'API. Un dépôt débite
réellement l'instrument de paiement de l'utilisateur ; l'ouvrir sans
intégration validée reviendrait à activer un flux d'argent réel. Un test
vérifie qu'aucune route de dépôt n'existe.

Une demande de retrait crée un enregistrement PENDING et **verrouille**
des fonds — le total du portefeuille est inchangé, seule la répartition
disponible/verrouillé bouge. Une revue humaine décide ensuite. Le
verrouillage passe par `WalletService`, qui écrit au grand livre : un
verrouillage sans écriture laisserait un solde inexpliqué, exactement ce
que le rapprochement du Lot 3 sert à détecter.

L'annulation en libre-service n'existe pas côté service : l'API renvoie
501 plutôt que de changer un statut sans libérer les fonds, ce qui
laisserait de l'argent bloqué.

### Réel et simulé, nommés séparément

| Champ | Nature |
|---|---|
| `available_balance`, `locked_balance` | argent réel |
| `simulated_trading_capital` | portefeuilles dont les ordres n'atteignent aucun marché |
| `live_trading_capital` | portefeuilles branchés sur un broker réel |

Les additionner mentalement est l'erreur que ce découpage rend
difficile. Dans l'interface, le capital simulé est grisé et porte la
mention « n'atteint aucun marché — cet argent n'existe pas ».

### Le rapprochement remonte dans le produit

`is_reconciled` et `unexplained_amount` sont exposés : un solde que
l'historique n'explique pas est une information qui appartient à son
propriétaire, pas à une commande d'administration. L'écran l'annonce et
conseille de signaler avant d'engager ces fonds.

### Bornes alignées sur le formulaire Django

5 à 100 000 par opération, garde KYC, solde suffisant. Une API plus
permissive que le formulaire serait le chemin qu'on emprunte pour
contourner la limite — un test le vérifie.

`destination_masked` refuse plus de six chiffres : le champ sert à
reconnaître une destination, pas à la définir.

### Correction d'une affirmation antérieure

J'avais signalé, plusieurs lots plus tôt, que les dépôts multi-devises
créditaient un montant au taux indéfini. **C'était faux.**
`wallet/form.py` refuse toute devise différente de celle du portefeuille,
et le webhook Stripe vérifie devise, montant, utilisateur et identifiant
de session avant de créditer. La liste `CURRENCY_CHOICES` est trompeuse
— elle propose des devises qui seront rejetées — mais aucun crédit à
taux indéfini ne peut se produire.

### Vérification

632 tests backend (1 ignoré), 63 Flutter, build web OK. Validé au
navigateur.

### Plus aucun écran « en cours de portage »

`PendingSection` est supprimé : les sept sections de l'application sont
désormais alimentées par l'API.

### Reste à faire sur ce domaine

- Parcours de dépôt (volontairement non exposé).
- Annulation d'une demande de retrait (le service legacy ne l'implémente
  pas).
- `CURRENCY_CHOICES` à restreindre à la devise du portefeuille, pour que
  l'interface cesse de proposer ce qui sera refusé.
- Plafonds à rendre dépendants du palier KYC — le commentaire
  « à ajuster en config selon le KYC tier » est toujours là.

---

## Lot 10 — Graphiques

### Une cause avant un dessin

`PortfolioSnapshot` existait depuis l'origine et portait tout ce qu'il
faut pour une courbe de valorisation — mais **aucune des 31 tâches beat
ne l'alimentait**. En développement : cinq instantanés, un seul
portefeuille, datant de six mois. Tracer une « courbe » dessus aurait
relié cinq îlots en une ligne continue.

Une tâche horaire a été ajoutée. Un portefeuille en erreur n'empêche pas
les autres d'être capturés : chaque série est indépendante.

### Le verdict de traçabilité vient du serveur

`GET /portfolios/{id}/equity-curve/` renvoie la série **et** de quoi
juger s'il y a lieu de la tracer : nombre de points, intervalle médian,
`is_plottable`, motifs du refus. Le seuil n'est pas redérivé par chaque
client — deux clients ne doivent pas trancher différemment.

Refus si moins de cinq points (deux points font un segment, pas une
trajectoire) ou si l'écart médian dépasse 36 h (l'interpolation
inventerait plus qu'elle ne montrerait).

Quand le refus tombe, l'interface montre les **points eux-mêmes** et dit
pourquoi elle ne les relie pas.

### Ce qui empêche un graphique exact de mentir

- **L'échelle de la courbe de valorisation inclut zéro** tant que la
  série reste positive. Un axe calé sur le minimum observé transforme
  une variation de 0,5 % en pente spectaculaire : c'est la manière la
  plus commune de mentir avec un graphique par ailleurs juste.
- **Marges symétriques** sur les chandeliers : coller la série aux bords
  suggère un plafond ou un plancher qui n'existe pas.
- **Une bougie incomplète est écartée**, pas dessinée à zéro — une
  valeur manquante lue comme 0 écraserait toute l'échelle.
- **Un graphique périmé le dit**, au-dessus de lui : « la dernière
  bougie date du 29/03/2026 (il y a 8 mois). Ce qui s'est passé depuis
  n'apparaît nulle part sur ce graphique. »

### Une erreur de ma part, corrigée

La migration `market_watchlistitem` du Lot 8 n'avait **jamais été
appliquée à la base de développement**. La route renvoyait 500 depuis, et
je ne l'avais pas vu : l'échec était absorbé côté client par un
`?? []`, et j'avais validé la page en la chargeant sans exercer la
fonctionnalité.

Leçon retenue : charger une page ne la valide pas. La liste de suivi a
été revérifiée en cliquant réellement.

### Flutter sans dépendance

Chandeliers et courbe dessinés au `CustomPainter`, mêmes règles
d'échelle. Aucun paquet graphique ajouté.

### Vérification

644 tests backend (1 ignoré), 72 Flutter, build web OK. Validé au
navigateur : chandeliers BTCUSDT sur 300 bougies avec l'avertissement de
péremption, refus de courbe sur un portefeuille neuf, liste de suivi
fonctionnelle.

### Reste à faire

- Indicateurs superposés (`MarketFeature` porte RSI, MACD, SMA, ATR,
  bandes de Bollinger — rien ne les trace).
- Graphiques dans les réponses de Leo.
- Temps réel des cotations par WebSocket.

---

## Lot 10 bis — Correction des trouvailles de la relecture adversariale

Cinq chercheurs, un angle chacun ; 49 trouvailles brutes, chacune soumise
à un réfutateur ayant consigne de réfuter par défaut. **12 ont survécu**,
se ramenant à six défauts distincts.

### 1. La précision d'affichage tronquait le transport

`Asset.price_precision` vaut 2 par défaut et n'est renseigné nulle part.
Le service arrondissait les bougies à cette précision **avant de les
transmettre**. Mesuré sur la vraie base :

```
ADAUSDT 1h, avant : 300 bougies → 10 cours distincts, 263 bougies plates
                    échantillon {open:'0.24' high:'0.24' low:'0.24' close:'0.24'}
          après  : 300 bougies → 212 cours distincts, 9 bougies plates
                    amplitude réelle 0,1498 → 0,2377 (+58,7 %)
```

Un mouvement de près de 60 % était rendu comme une ligne horizontale. La
précision d'affichage est une indication pour le client ; le serveur
transmet désormais la précision de STOCKAGE, et `price_precision` reste
exposé à part pour le formatage.

### 2. L'ancrage à zéro ne jouait que vers le bas

`Math.min(0, minValue)` sans son pendant. Sur une série entièrement
négative — rien ne borne le champ `equity` — zéro n'entrait jamais dans
la plage et l'axe se recalait sur l'amplitude observée. Le réfutateur a
trouvé en base un portefeuille à −464 361 qui deviendra traçable après
cinq cycles de la tâche horaire ajoutée au Lot 10.

Ancrage bidirectionnel, et une ligne de zéro est tracée dès que la série
touche le négatif : sans elle, l'aire d'une courbe négative est peinte
du même dégradé qu'une courbe positive.

### 3. La médiane est aveugle à un trou unique

365 points quotidiens avec une interruption de huit mois au milieu
gardent une médiane de 24 h. Et l'axe des temps d'un graphique boursier
est **ordinal** : le trou s'y dessine à la largeur d'un point, avec un
segment de pente ordinaire par-dessus.

Le plus grand écart est désormais calculé, exposé, et disqualifie la
série au-delà de sept jours (motif `INTERRUPTED`).

### 4. Traçable ne veut pas dire récent

La courbe n'avait aucun verdict de fraîcheur, alors que le serveur en
calculait l'âge et que les chandeliers, eux, affichaient un bandeau. Une
série régulière arrêtée il y a six mois se dessinait sans un mot.
`is_stale` ajouté, indépendant de `is_plottable`, avec son bandeau.

### 5. Web et Flutter ne cadraient pas la même fenêtre

300 bougies côté web, 200 côté mobile ; marges 12 % contre 8 %. Mesure
du réfutateur sur BTCUSDT 1h : amplitude 15 067 sur le web contre 5 263
sur mobile — **le même mouvement dessiné 3,16 fois plus haut sur le
téléphone**. Fenêtre et marges alignées.

### 6. Les graphiques ne disaient rien aux lecteurs d'écran

`aria-hidden` sans alternative. Un résumé chiffré en `sr-only`
accompagne désormais chaque graphique.

### Non retenu

L'absence d'échelle logarithmique a été confirmée comme réelle mais
cosmétique : elle sera traitée avec les indicateurs superposés.

### Vérification

654 tests backend (+10), 75 Flutter (+3), build web OK. Validé au
navigateur : ADAUSDT affiche 0,1696 et des centaines de bougies
distinctes là où la version précédente montrait une ligne plate.

---

## Métriques fantômes — diagnostic et correction

### Ce qui était en base

Le portefeuille « Cocody » affichait un solde de **−1 588 843 224,53** et
une valorisation de −12 401 590. Le portefeuille « Onon », −464 361.

### La cause, en une ligne

`Order.approved_quantity` n'a pas d'unité garantie — défaut documenté au
lot « dimensionnement ». L'adaptateur paper calculait
`notional = prix × approved_quantity` :

```
ordre 93, BTCUSDT
  montant voulu par l'utilisateur : 20 000 USD
  approved_quantity                : 20 000      ← le montant, recopié
  prix                             : 78 776,62
  débit écrit au grand livre       : 1 575 532 400
```

La branche Deriv du même adaptateur utilisait déjà `requested_stake_amount`
au lieu du produit : quelqu'un savait que le champ quantité n'est pas
fiable, mais n'avait corrigé qu'un cas.

### Prévention

- `AccountingBridgeService` refuse désormais d'écrire un débit dont le
  notionnel dépasse de plus de 50 % le notionnel approuvé par le moteur
  de risque. Un slippage réel reste très en deçà ; au-delà, ce n'est plus
  un écart de marché mais une erreur d'unité. **Refuser plutôt qu'écrire :
  un débit faux au grand livre est irréversible dans les faits, alors
  qu'un ordre refusé se rejoue.**
- L'adaptateur paper se fonde sur `approved_notional` quand il existe.

### Réparation

`manage.py repair_phantom_notional [--positions] [--apply]`, inspection
seule par défaut.

La commande **ne réécrit pas l'historique**. Elle poste une écriture de
correction, comme on le fait en comptabilité : un grand livre se corrige
par une contre-écriture datée et motivée, jamais en effaçant une ligne.

Pour les positions, elle ne touche que celles dont la quantité est, à 1 %
près, égale au notionnel approuvé de son ordre — la signature
démontrable du défaut. Quand la référence broker n'est pas exploitable,
le rattachement à un ordre est authentifié **par cette signature**, et
abandonné s'il est ambigu.

### Résultat sur Cocody

| | avant | après |
|---|---:|---:|
| solde | −1 588 843 224,53 | **2 530,57** |
| latent | −12 404 120,90 | −8 170 916,38 |

7 écritures corrigées, 5 quantités de position corrigées.

### Ce qui n'a pas été réparé, et pourquoi

Trois positions portent une quantité qui ne se réconcilie avec aucun
ordre : 1HZ25V affiche 14 pour un unique ordre de 10, JD10 affiche 7 pour
un ordre de 1. Le surplus vient d'imports broker dont la provenance n'est
pas vérifiable depuis le dépôt.

Leur `current_price` vaut par ailleurs 1000,00 — une valeur de
remplissage, les marks venant d'une clé Redis alimentée par des flux qui
ne tournent pas. Les rafraîchir depuis les bougies remplacerait un
chiffre faux par un chiffre vieux de cinq mois, appliqué à une quantité
elle-même fausse.

**Reconstruire ces quantités reviendrait à inventer des positions.** Elles
sont laissées intactes et signalées par la commande.

Les portefeuilles 1 et 3 présentent le même défaut (26 écritures,
correction cumulée ≈ 10,9 M) et n'ont pas été touchés : la demande
portait sur Cocody.

### Extension à LeoTrade et Onon

| Portefeuille | solde avant | solde après |
|---|---:|---:|
| Cocody | −1 588 843 224,53 | 2 530,57 |
| Onon | −464 361,39 | 2 962,50 |
| LeoTrade | 38 896,38 | 39 377,38 *(champ périmé, voir ci-dessous)* |

26 écritures de correction supplémentaires, 5 quantités de position.

### Un blocage découvert en route : portefeuille inenregistrable

Le recalcul de « LeoTrade » échoue sur :

> `{'broker_account': ['Le broker account doit appartenir au même utilisateur.']}`

Le portefeuille appartient à **sergehoo@gmail.com** mais pointe sur le
compte broker « DerivTradeOg », qui appartient à **sergeleo14@yahoo.fr**
— et ce compte est en mode **LIVE**.

Deux conséquences distinctes :

1. **Cloisonnement.** Un ordre issu de ce portefeuille emprunterait les
   identifiants broker d'un autre utilisateur. `Portfolio.clean()`
   l'interdit, donc la donnée est antérieure à la règle ou a été écrite
   par un chemin qui contourne `full_clean()`.
2. **Comptabilité gelée.** `Portfolio.save()` appelant `full_clean()`,
   **aucune écriture n'est plus possible sur ce portefeuille** : ni le
   recalcul du solde, ni une mise à jour de valorisation, ni un
   instantané. Le champ `current_balance` affiche 38 896,38 alors que son
   grand livre dit 39 377,38, et restera périmé tant que le rattachement
   n'est pas corrigé.

Le propriétaire du portefeuille possède son propre compte DERIV/LIVE
(id=4). Réaffecter le portefeuille change le courtier par lequel passent
ses ordres réels : **cette décision ne m'appartient pas** et n'a pas été
prise.

La commande de réparation isole désormais les échecs par portefeuille et
annonce le blocage plutôt que d'abandonner la série — un champ de solde
périmé sans explication serait pire qu'une erreur, on croirait le chiffre
à jour.

---

## Finalisation du client mobile

### Audit

Sept auditeurs en parallèle (parité web, couverture API, correction
Flutter, livraison Android/iOS, UX téléphone, conformité au mandat,
tests), chaque constat soumis à trois réfuteurs à lentilles distinctes
— *est-ce vrai, est-ce que ça se produit, est-ce que ça compte*.
**63 constats bruts → 43 confirmés, 20 réfutés.**

Trois réfutations ont évité des corrections inutiles, et sont notées ici
parce qu'elles valent pour la suite :

- **La politique réseau d'Android et ATS ne s'appliquent pas.** Dio et
  `WebSocketChannel` passent par `dart:io HttpClient`, qui ouvre ses
  sockets depuis la VM Dart sans consulter `NetworkSecurityPolicy`. Une
  configuration de trafic en clair aurait été inerte — et se serait lue
  comme une protection active.
- **R8 ne mordrait que sur `MainActivity`** : le code Dart est compilé
  AOT dans `libapp.so`. Et le découpage par ABI est déjà posé par le
  plugin Gradle de Flutter.
- **L'absence de keystore dans le dépôt n'est pas un défaut**, c'est la
  règle : `android/.gitignore` l'écrit déjà.

### Ce que seul le téléphone a montré

Le défaut le plus grave n'était dans aucun des 43 constats. Il n'a été
vu qu'en installant l'application sur un appareil réel.

**La socket de Leo était refusée en 403, et l'avait toujours été.**

`AllowedHostsOriginValidator` (channels/security/websocket.py) :

```python
# None is not allowed unless all hosts are allowed
if parsed_origin is None and "*" not in self.allowed_origins:
    return False
```

Un navigateur envoie toujours `Origin`. Dart, Swift et Kotlin, jamais.
Leo fonctionnait donc sur le web et **ne pouvait pas** fonctionner sur
mobile — pas « ne fonctionnait pas » : ne pouvait pas. L'écran affichait
« Connexion… » indéfiniment, ce que l'audit avait relevé comme symptôme
sans en trouver la cause.

Le test de bout en bout ne pouvait pas l'attraper : il monte
`JWTAuthMiddlewareStack` seul, sans le validateur qui l'enveloppe dans
`asgi.py`. Le défaut vivait **entre** les deux.

`JWTFriendlyOriginValidator` accepte l'absence d'en-tête **uniquement**
si le client présente un jeton dans le sous-protocole. Ce que la
vérification protège, c'est le détournement depuis une page tierce, où
le NAVIGATEUR joint le cookie de session d'office ; un JWT, lui, n'est
jamais joint d'office. Une connexion qui compte sur le cookie reste
soumise à la vérification exactement comme avant.

### Trois boutons morts sur les deux clients

DRF dérive deux noms d'une même méthode décorée :

```python
func.url_path = url_path if url_path else func.__name__          # soulignés
func.url_name = url_name if url_name else func.__name__.replace('_', '-')
```

Neuf `@action` avaient oublié `url_path`. Le web et le mobile écrivent
des tirets. « Définir par défaut », « Lever l'arrêt d'urgence » et
« Recalculer les états » tombaient dans le vide.

La suite était verte : elle passe par `reverse()`, qui part du NOM de
route et ne peut pas produire un chemin inexistant. Elle validait une
URL qu'aucun client n'appelait. `test_api_route_paths.py` vise désormais
le chemin littéral et refuse tout chemin servi avec un souligné.

### Le reste

| | |
|---|---|
| Navigation | Sept `IconButton` dans une barre de titre étaient le seul chemin vers quoi que ce soit. `StatefulShellRoute`, cinq destinations, chacune gardant sa pile. |
| Session | Une panne sur la requête REJOUÉE détruisait la session ; `restore()` effaçait le jeton sur une simple coupure réseau. |
| Leo | Confirmer une action visait la mauvaise table — soit bouton mort, soit exécution d'une opération non regardée. La demande du Risk Engine n'était affichée nulle part. |
| Release | INTERNET n'était déclarée que dans les manifestes debug/profile : un APK release n'avait aucun accès réseau. |
| Identité | `com.lyneci.lyneci` → `com.leotrade.app`. Le commentaire qui justifiait le maintien était faux. |
| Parité | Courbe de valorisation, cotation du détail d'instrument, suivi des retraits, pagination, cours et exposition des positions. |

### Validé sur un appareil réel

Samsung `R58M325DX6M`, API pointée sur le Mac. Parcours : lancement →
connexion refusée par le serveur sur un e-mail non vérifié → connexion →
création d'un portefeuille de simulation (10 000 USD, sans double
comptage) → onglets → recherche BTCUSDT → détail avec cotation périmée
datée → Leo **en ligne**.

Compte de recette dédié `recette.mobile@leotrade.test` : aucun compte
existant n'a été touché, et aucun mot de passe personnel n'a été saisi.

**Reste à faire, non traité ici** : icônes et écran de lancement sont
désormais aux couleurs de l'application, mais la marque est un
**provisoire** — une ligne de prix et deux chandeliers, sans typographie
ni symbole inventé. À remplacer par un vrai dessin.

Vérifié : 120 tests Flutter, suite backend complète verte,
`flutter analyze` et `tsc` sans remarque, build APK et build web OK.

---

## Les outils de formatage de Leo

### Le prompt promettait ce que personne ne rendait

Quatre outils annoncés à Leo dans `ASSISTANT_SYSTEM_PROMPT` n'avaient de
rendu nulle part : `==surlignage==`, `> citation`, `---`, et les liens
internes. Leo les écrivait consciencieusement ; ils s'affichaient en
caractères parasites.

Pire, sa liste blanche de routes était celle de l'ancien panneau Django
— `/trading/ideas/`, `/risk/profile/`, `/wallet/`. Aucune de ces pages
n'existe dans React ni dans Flutter : chaque lien envoyait l'utilisateur
dans le vide. La règle anti-hallucination était écrite juste au-dessus.

### La grammaire, écrite une fois

`docs/LEO_MARKDOWN.md` est désormais la source unique, et trois fichiers
s'y conforment : le prompt, `Markdown.tsx`, `markdown.dart`.

Ajouté : titres sur six niveaux, citations, **encadrés**
(`> [!NOTE|TIP|IMPORTANT|WARNING|CAUTION]`) rendus avec les composants
d'alerte déjà présents dans chaque client, séparateurs, listes
imbriquées, cases à cocher, barré, surlignage, **icônes** (liste fermée),
**liens internes**, **boutons de navigation**, images, et retrait des
commentaires HTML.

### Trois refus délibérés

- **Un bouton navigue, rien d'autre.** Les opérations financières
  passent par les cartes d'action et les demandes du Risk Engine, qui
  ont leur protocole, leur audit et leur double confirmation en mode
  réel. Un bouton de texte n'y touche pas.
- **Un chemin hors liste blanche est rendu en TEXTE**, jamais en lien ni
  en bouton. La règle anti-hallucination s'applique ainsi à l'affichage,
  pas seulement à la consigne : si le modèle invente une page,
  l'interface ne fabrique pas un bouton mort pour autant.
- **Une adresse externe est montrée, jamais masquée** derrière un
  libellé. Un modèle peut rapporter un lien venu d'un tiers, et un
  libellé rassurant sur une adresse qui ne l'est pas est la forme même
  de l'hameçonnage. Et une image distante n'est pas chargée : c'est un
  pixel traceur, qui révèle l'IP du lecteur et l'instant de la lecture.

### Le contrat est sous test

`test_leo_grammar_contract.py` lit les trois fichiers et échoue si leurs
listes de routes ou d'icônes divergent, si le prompt cite un chemin
qu'aucun client ne sert, ou s'il enseigne une syntaxe sans rendu. C'est
exactement la dérive qui avait produit le défaut.

### Un plantage que seul le téléphone a montré

Le premier bouton tapé sur l'appareil a fait rougir l'écran :

```
navigator.dart: Failed assertion: '!keyReservation.contains(key)'
```

Les destinations de Leo sont des onglets d'une `StatefulShellRoute`.
Leo, lui, est posé par-dessus, sur le navigateur racine. **Pousser** une
route de branche reconstruit le `Navigator` de cette branche alors que
sa `GlobalKey` est déjà prise par celui qui tourne en dessous. Il faut
`go`, qui bascule sur l'onglet — ce qui est de toute façon le geste
attendu.

Le premier test de non-régression écrit pour ce défaut **passait quand
même** : son routeur démarrait sur Leo, donc la coquille n'était jamais
montée et la seconde n'entrait en collision avec rien. Corrigé pour
démarrer dans la coquille, il échoue avec `push` et passe avec `go`.

### Validé sur l'appareil et au navigateur

Un message portant toute la grammaire, inséré en base pour ne pas
consommer de quota LLM, puis retiré. Sur le Samsung : encadré orange
« Attention », cases à cocher, surlignage, barré, citation, séparateur,
icônes, deux boutons qui basculent réellement sur l'onglet Risque, lien
interne, lien externe avec son adresse visible, et
`[l'ancien panneau](/trading/ideas/)` rendu **en texte brut** — comme
prévu. Au navigateur, même grammaire sur une conversation réelle.

138 tests Flutter (+18), suite backend verte (+11).
