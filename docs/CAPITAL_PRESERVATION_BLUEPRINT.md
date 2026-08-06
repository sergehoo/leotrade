# LeoTrade — Blueprint « Capital Preservation First »

> Document de design issu de la session Office Hours. Feuille de route produit,
> risque, IA, validation et conformité. **Ce n'est pas un avis juridique** : les
> points réglementaires doivent être validés par un conseil agréé BCEAO/CREPMF
> avant toute manipulation de fonds de tiers.
>
> Principe directeur : le produit ne promet **aucun gain**. Il protège le
> capital, limite les pertes, et ne cherche du rendement qu'ensuite.

---

## 0. Deux vérités dures, non négociables

**V1 — « 2 à 5 % / mois durable » est irréaliste.** Cela équivaut à 27–80 %
annualisés composés — au-dessus du meilleur fonds de l'histoire. On ne l'affiche
JAMAIS comme objectif ou attente. Le succès se mesure en **risque maîtrisé**
(drawdown, survie du capital), pas en % de rendement.

**V2 — Le choix de l'instrument est architectural.** Les indices synthétiques
Deriv ont une **espérance négative par construction** (avantage maison). On ne
fait pas de préservation du capital durable sur un instrument négatif-EV : le
temps joue mécaniquement contre l'utilisateur. → **Décision ouverte (§3).**

---

## 1. Thèse produit (testable)

Un **copilote d'aide à la décision qui, par défaut, ne trade pas.** Sa valeur
n'est pas de prédire l'avenir — c'est de **filtrer** : refuser la grande majorité
des configurations, n'agir que sur celles à **espérance positive nette de coûts**
et à **risque borné**, et recommander explicitement **« ne pas trader »** quand
le risque est trop élevé.

**KPI produit (dans cet ordre) :**
1. Max drawdown des comptes utilisateurs (le plus bas possible).
2. Taux de survie du capital à 3 / 6 / 12 mois.
3. Ratio ajusté du risque (Sortino) — *pas* le rendement brut.
4. Rendement, en dernier.

---

## 2. Décision n°1 — Modèle réglementaire (contraint tout le reste)

| Modèle | Activité | Charge |
|---|---|---|
| **A. SaaS analytique** | Analyse + signaux **éducatifs** ; l'utilisateur exécute chez SON broker. Aucun fonds touché, aucun conseil nominatif. | Légère — pas de licence marché financier. |
| **B. Conseil / copy-trading** | Recommandation personnalisée, gestion, copie. | Licence CREPMF / statut conseiller. |
| **C. Garde & transmission de fonds (mobile money)** | Recharge, détention d'avoirs. | Statut monnaie électronique / paiement **BCEAO** ou partenariat EME agréé. |

**DÉCISION ADOPTÉE : démarrer en Modèle A.** Débloque validation + premiers
utilisateurs sans le mur B/C, repousse le mobile money (statut BCEAO) à la
traction. Passage à B/C uniquement en Phase 4, financé par la traction.

**Contraintes Modèle A (à coder comme des règles produit) :**
- Jamais de conseil nominatif (« TOI, achète X ») → analyses et signaux génériques.
- Ne jamais détenir ni transmettre les fonds de l'utilisateur.
- Disclosure de risque brutale, permanente, non contournable.
- Aucun vocabulaire de garantie / rendement promis (déjà retiré du prompt LeoAI).

---

## 3. Décision n°2 — Instrument (ACTÉE : multi-instrument classifié)

**Décision : garder Deriv ET ouvrir aux autres marchés.** Le multi-instrument
sauve la thèse de préservation ; l'architecture Broker Gateway (déjà en place)
l'absorbe. Contrainte non négociable : un instrument négatif-EV ne peut pas être
le socle de la préservation. → **Couche de classification des instruments.**

**Raffinement à l'implémentation : 3 niveaux, pas 2.** Deux propriétés sont
orthogonales et les confondre serait malhonnête : l'**espérance** (négative par
construction vs neutre) et la **volatilité**. La crypto n'est pas négative-EV —
la ranger avec un produit de casino serait faux ; la ranger avec un ETF le serait
aussi. D'où un niveau intermédiaire.

| Niveau | Instruments | Risque/trade (plafond dur) | Expo symbole | Expo niveau | Préservation | Opt-in |
|---|---|---|---|---|---|---|
| **CORE** | Actions, ETF, indices réels, FX **majeur** | 0,50 % | 15 % | 100 % | ✅ éligible | non |
| **VOLATILE** | Crypto, FX exotique, matières premières | 0,25 % | 10 % | 30 % | ❌ exclu | ✅ requis |
| **SPECULATIVE** | Synthétiques Deriv (R_*, 1HZ*V, BOOM/CRASH, JD*, stpRNG) | 0,25 % | 5 % | 10 % | ❌ exclu | ✅ requis + disclosure espérance négative |

**Implémenté** — `risk/instruments.py` :
- `classify()` résout le niveau. ⚠️ **`asset_class` n'est PAS fiable** : la
  commande de seed enregistre les synthétiques Deriv en `asset_class="INDEX"`,
  identiques à un vrai indice. La résolution se fait donc dans cet ordre :
  **motif de symbole → exchange → asset_class → fail-safe**.
- **Fail-safe** : un instrument inconnu est classé SPECULATIVE (le plus
  restrictif). En préservation, l'inconnu se traite comme dangereux.
- `effective_risk_pct()` : le plafond de niveau ne peut **que réduire** le
  risque du profil, jamais l'augmenter.
- `RiskProfile.preservation_mode` (défaut **True**),
  `allow_volatile_instruments` / `allow_speculative_instruments` (défaut
  **False**) → migration `risk/0007`.
- Garde-fou `validate_trade` bloc « 3bis » : opt-in manquant →
  `INSTRUMENT_TIER_NOT_ENABLED` ; mode préservation + instrument non éligible →
  `PRESERVATION_MODE_EXCLUDES_INSTRUMENT`. Blocages **SOFT** : franchissables par
  décharge explicite, ce qui **trace l'opt-in dans `RiskOverrideAudit`**.

> Bug corrigé au passage : le détecteur de synthétiques préexistant
> (`dashboard/views.py SYNTHETIC_PREFIXES`) ne reconnaissait **ni les `1HZ*V`
> (Volatility 1s) ni `stpRNG`** — ces instruments échappaient donc au traitement
> spécifique. Le classifieur canonique les couvre.

---

## 4. Capital Preservation First — spécification d'ingénierie

Hiérarchie stricte (mission 1 avant 2 avant 3) :

**Mission 1 — Protéger** *(implémenté : `PositionSizingService.compute`)*

La quantité retenue est le **minimum** de tous les plafonds — le plus
contraignant gagne toujours :

```
risque_effectif_%  = min(profil.max_risk_per_trade, plafond_dur_du_niveau)   # ne peut que réduire
risk_amount        = équité × risque_effectif_% / 100
qty_risque         = risk_amount / distance_au_stop          # sizing stop-based
qty_stake          = stake_demandé / prix_entrée
qty_cash           = cash_disponible / prix_entrée
qty_volatilité     = (équité × target_vol_% / 100) / ATR     # volatility targeting
quantité_finale    = min(qty_risque, qty_stake, qty_cash, qty_volatilité)
```

- **Risque par trade ≤ 0,5 %** du capital, plafond **dur** par niveau (§3).
- **Volatility targeting** (`atr` + `target_vol_pct`, défaut 1 %) : borne la
  quantité pour qu'un mouvement de 1 ATR ne déplace pas l'équité de plus de la
  cible. Complète le stop-based : protège le cas d'un **stop très serré sur un
  instrument très volatil** (stop-out quasi certain), que le sizing stop-based
  seul autorise à tort en grande quantité.
- Refus d'entrée si drawdown courant > seuil profil.
- Mapping : `RiskProfile.max_risk_per_trade`, `risk/instruments.py`,
  `RiskGuardService.validate_trade`.

**Mission 2 — Limiter**
- Stop-loss obligatoire sur chaque position.
- Caps de perte jour / semaine / mois → `DailyRiskState` / `WeeklyRiskState` /
  `MonthlyRiskState` (déjà en base) + limites `max_daily_loss` / `max_weekly_loss`
  / `max_monthly_loss`.
- **Kill switch automatique** sur dépassement (déjà : `RiskGuardService`).
- **Circuit breaker par stratégie dégradée** (déjà : `StrategyCircuitBreakerService`).

**Mission 3 — Rendement**
- Uniquement sur ce qui reste après 1 et 2.

> Le ×5 du backtest initial violait la Mission 1. La bonne architecture rend ce
> ×5 **structurellement impossible** — c'est une feature, pas une limite.

---

## 5. IA copilote — zéro prétention prédictive

Chaque sortie IA (schéma déjà en place dans `AIDecision`) :
- **espérance nette estimée** (après spread + frais),
- **niveau de confiance** calibré,
- **scénario principal + condition d'invalidation**,
- **décision par défaut = ABSTENTION**.

`EXECUTE` seulement si : espérance nette > seuil **ET** confiance > seuil **ET**
risque borné. Ajouter l'action explicite **`DO_NOT_TRADE`** avec explication
(« volatilité anormale », « aucun setup à espérance positive aujourd'hui »).

Interdits : le mot « garantie », tout affichage de rendement comme attente.
Mapping code : `AIDecision` enrichi, `AIPerformanceService` (calibration
gains/pertes), `PredictionEvaluationService` (prévision vs réalité).

---

## 6. Protocole scientifique de validation — portes go/no-go

Aucune porte franchie ⇒ **PAPER uniquement, zéro argent de tiers.**

- **Gate 1 — Significativité** : ≥ ~1 000 trades **paper forward** (pas backtest), horodatés.
- **Gate 2 — Hors échantillon & régimes** : données jamais vues ; testé séparément
  sur marché haussier / baissier / range / haute-volatilité.
- **Gate 3 — Coûts réels** : spread + frais + slippage + latence modélisés.
- **Gate 4 — Ajusté du risque** : Sharpe, **Sortino**, **max drawdown**,
  profit factor, expectancy. Drawdown & Sortino priment sur le rendement.
- **Gate 5 — Transparence** : track record **public, immuable, vérifiable** —
  chaque prédiction horodatée **avant** son résultat (c'est déjà ce que fait
  `PredictionEvaluationService`). Aucune courbe rétro-ajustée.

---

## 7. Feuille de route par phases

- **Phase 0 (maintenant)** : figer Modèle A ; retirer tout « garantie »
  (fait côté prompt) ; brancher la mesure de perf réelle ; inverser le défaut IA
  vers l'abstention.
- **Phase 1** : forward paper trading massif → Gates 1–4. Argent propre en
  parallèle (100 $, exécution manuelle).
- **Phase 2** : track record public (Gate 5) + avis juridique écrit BCEAO/CREPMF.
- **Phase 3** : premiers utilisateurs réels **en Modèle A** (ils tradent chez
  eux) ; disclosure brutale ; LIVE réservé aux avertis.
- **Phase 4 (si traction)** : financer la conformité B/C + mobile money.

---

## 8. Anti-patterns interdits

- ❌ Promesse / garantie de gains, affichage d'un rendement cible.
- ❌ Sizing agressif (tout % « qui fait ×N »).
- ❌ Backtest présenté comme preuve (seul le forward compte).
- ❌ Marketing du rendement vers une population vulnérable.
- ❌ Détenir les fonds utilisateurs avant statut BCEAO / partenaire EME.
- ❌ Conseil nominatif sans licence CREPMF.

---

## 9bis. État d'implémentation (honnêteté sur le périmètre réel)

| Élément | État |
|---|---|
| Classification 3 niveaux + politiques (`risk/instruments.py`) | ✅ implémenté + testé |
| Plafond dur de risque par niveau (`effective_risk_pct`) | ✅ implémenté + testé |
| Volatility targeting dans le sizing | ✅ implémenté + testé (paramètre `atr` optionnel) |
| Garde-fou opt-in / préservation dans `validate_trade` | ✅ implémenté + testé |
| Champs `RiskProfile` + migration `risk/0007` | ✅ implémenté |
| Caps d'**exposition** (`max_symbol_exposure_pct`, `max_tier_exposure_pct`) | ⚠️ **déclarés dans `TierPolicy` mais pas encore appliqués** — à brancher sur le contrôle d'exposition existant |
| Passage du `instrument_tier` par les appelants de `compute()` | ✅ câblé sur les 3 chemins actifs (`trading/services/ai_engine.py`, `trading/services/trade_idea_execution.py`, `risk/engine.py`) — le plafond n'est plus dormant |
| Source d'ATR réelle (données marché) | ⚠️ à brancher : sans ATR, le volatility targeting est inactif |
| UI d'opt-in par niveau (page `/risk/profile/`) | ⚠️ à faire |
| Protocole de validation (Gates 1–5) | ⛔ non commencé — **c'est le vrai bloqueur avant tout argent réel** |

## 9bis-2. Revue adversariale — failles trouvées et traitées

Une revue multi-lentilles (quant / cas limites / politique de protection /
intégration) a été passée sur le moteur de risque. **Corrigé immédiatement :**

| Faille | Gravité | Correctif |
|---|---|---|
| `STEPINDEX` (le Step index réellement seedé) ressortait **CORE**, donc éligible préservation | CRITIQUE | ajouté au motif ; **verrou de test** qui valide les 22 synthétiques seedés |
| Plafond de classe + volatility targeting **dormants** : aucun appelant de production ne les passait | CRITIQUE | câblés sur les 3 chemins (`ai_engine`, `trade_idea_execution`, `risk/engine`) |
| **Deriv contournait totalement le sizing** : `_build_deriv_sizing` ne lisait jamais `risk_profile` ⇒ `max_risk_per_trade` jamais appliqué sur les instruments à espérance négative | CRITIQUE | la mise est plafonnée par le risque effectif (sur ces contrats la mise = perte max) ; refus explicite si le plafond tombe sous le minimum broker |
| Le garde-fou de classe **masquait le kill switch** : placé avant les blocs de perte, son retour anticipé empêchait `trigger_kill_switch` | CRITIQUE | bloc déplacé en 9bis (après les blocs 7/8/8bis/9) + test de régression |
| Aucun **chemin d'opt-in** : le message invitait à activer la classe alors que `RiskSettingsUpdateService` ne l'autorisait pas | HAUTE | 3 champs ajoutés aux `EDITABLE_FIELDS` (mutateur audité + notifié) |
| Suffixes de courtier (`EURUSDm`, `EURUSD.a`) éjectaient les majeurs FX de CORE | MOYENNE | reconnaissance tolérante aux suffixes |
| Budget de volatilité figé à 1 % ⇒ 1 ATR coûtait 4× le plafond d'un SPECULATIVE | MOYENNE | budget dérivé du risque **effectif** (après plafond de classe) |

**Backlog confirmé, NON corrigé (à traiter avant tout argent réel) :**

1. **CRITIQUE — `contract_size` ignoré** : la quantité est calculée en unités
   de prix mais transmise à MT5 comme des **lots** (`"volume"`). Sur du FX,
   l'exposition réelle peut être 100 000× la cible.
2. **CRITIQUE — plafonds d'exposition de `TierPolicy` non appliqués** :
   `max_symbol_exposure_pct` / `max_tier_exposure_pct` sont déclarés mais aucun
   code de production ne les lit (vérifié). Seul `profile.max_symbol_exposure_percent`
   (25 %) agit ⇒ la politique affichée est fictive. Les brancher ou les retirer.
3. **HAUTE — pas de conversion de devise** : `stop_distance` est en devise de
   cotation, `risk_amount` en devise du compte. Le risque réel dévie du taux de
   change (ex. +27 % sur EURGBP depuis un compte USD).
4. **HAUTE — pas de plafond de notionnel** : un stop très serré transforme un
   budget de risque de 0,5 % en exposition notionnelle allant jusqu'à 100 % de
   l'équité ; un gap traverse le stop et la perte dépasse largement le budget.
5. **HAUTE — sécurité API** : `RiskProfileViewSet` est un `ModelViewSet` complet
   dont la permission `IsOwner` n'implémente que `has_object_permission` — jamais
   appelé sur une création. Un utilisateur pourrait créer un profil par défaut
   sur le portefeuille d'autrui (kill switch désactivé, risque 100 %).
6. **HAUTE — l'override est une case unique** au motif facultatif qui franchit
   d'un coup **tous** les blocages SOFT (dont l'instrument à espérance négative,
   en LIVE). Il faut une friction dédiée par classe de blocage.
7. **MOYENNE — le fail-safe est neutralisé en amont** : `BrokerImportService`
   crée tout symbole inconnu avec `asset_class="CRYPTO"` et l'exchange par défaut
   `BINANCE` ⇒ `classify()` voit une affirmation, pas un inconnu, et rend
   VOLATILE au lieu de SPECULATIVE.
8. **MOYENNE — `max_leverage` n'est jamais contrôlé** : la condition est
   constante et le corps est `pass` (code mort).
9. **MOYENNE — la génération d'idées ignore le mode préservation** : des
   synthétiques sont toujours *recommandés* à l'utilisateur ; la protection
   n'existe qu'à l'exécution. Filtrer en amont ou étiqueter clairement.
10. **MOYENNE — `RiskOverrideAudit` n'est écrit que si la décision finale est
    `APPROVE`** : un override suivi d'un `REDUCE` s'exécute sans trace immuable.

## 9ter. Rappel du bloqueur principal

Aucune de ces protections ne remplace la **preuve de performance**. À ce jour :
backtest sur ~10 trades, non net de frais, sizing violant la Mission 1 ⇒ **aucune
preuve exploitable**. Le seul chemin : forward paper trading massif (§6).

## 9quater. Ce que l'assistant IA ne doit jamais dire

Contrôlé côté prompt (`ai_assistant/services.py`) : pas de « garantie », pas de
rendement affiché comme attente, pas de recommandation d'un instrument
SPECULATIVE comme outil de préservation, et pour tout instrument non éligible :
disclosure du niveau avant toute suggestion.

## 10. Décisions

1. **Instrument** (§3) : ✅ ACTÉ — multi-instrument classifié (CORE préservation
   + SPÉCULATIF opt-in). Synthétiques Deriv conservés mais hors du défaut.
2. Prochain pilier à détailler (au choix) : moteur de risque (spec chiffrée),
   pipeline de validation (sur le code existant), ou cadrage Modèle A (ce qu'on
   a le droit de dire / ne pas dire).
