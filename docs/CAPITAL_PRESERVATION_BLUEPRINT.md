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

| Classe | Instruments | Politique |
|---|---|---|
| **CORE** (préservation) | Actions, ETF, FX majeur | Univers **par défaut**, éligible « préservation », caps standards. |
| **SPÉCULATIF** (haut risque) | Synthétiques Deriv (R_75…) | **Opt-in explicite**, étiqueté « spéculatif / haut risque », **exclu du défaut**, cap par trade ≤ 0,25 %, exposition plafonnée. L'IA ne le recommande **jamais** comme outil de préservation. |

**Architecture :**
- Chaque `Asset` porte une classe d'éligibilité (s'appuie sur `asset_class`).
- Le moteur de risque lit la classe et applique la politique (cap par trade,
  exposition max, éligibilité au mode préservation).
- L'IA connaît la classe : pour un instrument SPÉCULATIF, disclosure renforcée
  et jamais de cadrage « préservation ».
- Le mode par défaut de l'utilisateur = CORE uniquement ; le SPÉCULATIF exige
  un opt-in tracé.

---

## 4. Capital Preservation First — spécification d'ingénierie

Hiérarchie stricte (mission 1 avant 2 avant 3) :

**Mission 1 — Protéger**
- **Volatility targeting** : taille de position calculée pour un risque cible
  constant, jamais un % fixe du capital.
- **Risque par trade ≤ 0,5 %** du capital (plafond dur).
- Refus d'entrée si drawdown courant > seuil profil.
- Mapping code : `RiskProfile.max_risk_per_trade`, `RiskGuardService.validate_trade`.

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

## 9. Décisions

1. **Instrument** (§3) : ✅ ACTÉ — multi-instrument classifié (CORE préservation
   + SPÉCULATIF opt-in). Synthétiques Deriv conservés mais hors du défaut.
2. Prochain pilier à détailler (au choix) : moteur de risque (spec chiffrée),
   pipeline de validation (sur le code existant), ou cadrage Modèle A (ce qu'on
   a le droit de dire / ne pas dire).
