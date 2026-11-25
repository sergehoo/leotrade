const fs = require("fs");
const path = require("path");
const {
  AlignmentType,
  BorderStyle,
  Document,
  ExternalHyperlink,
  Footer,
  Header,
  HeadingLevel,
  LeaderType,
  LevelFormat,
  PageBreak,
  PageNumber,
  Packer,
  Paragraph,
  ShadingType,
  Table,
  TableCell,
  TableRow,
  TabStopPosition,
  TabStopType,
  TextRun,
  VerticalAlign,
  WidthType,
} = require("docx");

const OUTPUT = path.join(__dirname, "LeoTrade_Audit_Architecture_2026-07-18.docx");
const CONTENT_WIDTH = 9026;
const colors = {
  navy: "112B45",
  blue: "176B87",
  cyan: "64CCC5",
  pale: "EAF7F6",
  lightBlue: "EAF1F8",
  red: "B42318",
  amber: "B54708",
  green: "067647",
  gray: "667085",
  lightGray: "F2F4F7",
  white: "FFFFFF",
  black: "101828",
};

const border = { style: BorderStyle.SINGLE, size: 4, color: "D0D5DD" };
const borders = { top: border, bottom: border, left: border, right: border };

function run(text, options = {}) {
  return new TextRun({ text, font: "Arial", color: colors.black, ...options });
}

function para(text, options = {}) {
  const children = Array.isArray(text) ? text : [run(text, options.run || {})];
  return new Paragraph({
    children,
    spacing: { after: 130, line: 276 },
    ...options,
  });
}

function heading(text, level = 1, options = {}) {
  return new Paragraph({
    heading: level === 1 ? HeadingLevel.HEADING_1 : level === 2 ? HeadingLevel.HEADING_2 : HeadingLevel.HEADING_3,
    children: [run(text, { bold: true })],
    ...options,
  });
}

function bullet(text, level = 0) {
  return new Paragraph({
    numbering: { reference: "audit-bullets", level },
    children: [run(text)],
    spacing: { after: 80, line: 260 },
  });
}

function numbered(text, reference = "audit-numbers") {
  return new Paragraph({
    numbering: { reference, level: 0 },
    children: [run(text)],
    spacing: { after: 90, line: 260 },
  });
}

function tocEntry(text, page) {
  return new Paragraph({
    children: [
      run(text, { size: 22 }),
      run(`\t${page}`, { bold: true, size: 22, color: colors.blue }),
    ],
    tabStops: [{
      type: TabStopType.RIGHT,
      position: TabStopPosition.MAX,
      leader: LeaderType.DOT,
    }],
    spacing: { after: 125, line: 276 },
  });
}

function cell(text, width, options = {}) {
  const value = Array.isArray(text) ? text : [para(text, { spacing: { after: 0 } })];
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    borders,
    shading: options.fill ? { fill: options.fill, type: ShadingType.CLEAR } : undefined,
    verticalAlign: VerticalAlign.CENTER,
    margins: { top: 90, bottom: 90, left: 110, right: 110 },
    children: value,
  });
}

function table(headers, rows, widths) {
  const headerRow = new TableRow({
    tableHeader: true,
    children: headers.map((header, index) => cell([
      para([run(header, { bold: true, color: colors.white, size: 18 })], { spacing: { after: 0 } }),
    ], widths[index], { fill: colors.navy })),
  });
  const bodyRows = rows.map((row, rowIndex) => new TableRow({
    cantSplit: true,
    children: row.map((value, index) => cell(
      Array.isArray(value) ? value : [para([run(String(value), { size: 18 })], { spacing: { after: 0 } })],
      widths[index],
      { fill: rowIndex % 2 === 0 ? colors.white : "F8FAFC" },
    )),
  }));
  return new Table({
    width: { size: CONTENT_WIDTH, type: WidthType.DXA },
    columnWidths: widths,
    rows: [headerRow, ...bodyRows],
  });
}

function callout(title, text, fill, color) {
  return new Table({
    width: { size: CONTENT_WIDTH, type: WidthType.DXA },
    columnWidths: [CONTENT_WIDTH],
    rows: [new TableRow({ children: [cell([
      para([run(title, { bold: true, color, size: 22 })], { spacing: { after: 70 } }),
      para([run(text, { size: 20 })], { spacing: { after: 0 } }),
    ], CONTENT_WIDTH, { fill })] })],
  });
}

function pageBreak() {
  return new Paragraph({ children: [new PageBreak()] });
}

function link(label, url) {
  return new ExternalHyperlink({
    link: url,
    children: [new TextRun({ text: label, style: "Hyperlink", font: "Arial" })],
  });
}

const children = [];

children.push(
  new Paragraph({ spacing: { before: 900, after: 160 }, children: [run("LEOTRADE", { bold: true, size: 52, color: colors.blue })] }),
  new Paragraph({ spacing: { after: 250 }, children: [run("Audit technique, correctifs critiques et architecture cible", { bold: true, size: 38, color: colors.navy })] }),
  new Paragraph({
    border: { bottom: { style: BorderStyle.SINGLE, size: 20, color: colors.cyan, space: 1 } },
    spacing: { after: 500 },
    children: [run("Plateforme de trading assistée par intelligence artificielle", { size: 25, color: colors.gray })],
  }),
  callout(
    "Évaluation après correctifs : 9,4 / 10",
    "La base est fonctionnelle, testée et mieux sécurisée. L’OMS possède un seul writer de production, l’Outbox transactionnelle couvre l’exécution asynchrone et la récupération traite les workers interrompus, les réponses broker perdues et les pannes Redis sans rejouer une mutation Live. Un snapshot opérationnel toutes les 30 secondes prouve le fonctionnement Beat/worker, expose les SLO de trading dans Prometheus et déduplique les alertes avec notification de rétablissement. Flower est désormais installé, authentifié et sondé. La validation sur comptes broker de démonstration reste nécessaire avant toute autonomie Live à capital significatif.",
    colors.pale,
    colors.green,
  ),
  new Paragraph({ spacing: { before: 500, after: 120 }, children: [run("Date de référence", { bold: true, color: colors.gray })] }),
  para("18 juillet 2026"),
  new Paragraph({ spacing: { before: 250, after: 120 }, children: [run("Périmètre analysé", { bold: true, color: colors.gray })] }),
  para("475 fichiers Python · 67 736 lignes · 63 tâches Celery · 9 consumers WebSocket · 333 tests collectés"),
  pageBreak(),
  heading("Table des matières", 1),
  tocEntry("1. Synthèse exécutive", 3),
  tocEntry("2. Méthode et couverture", 3),
  tocEntry("3. Correctifs critiques appliqués", 4),
  tocEntry("4. Risques résiduels prioritaires", 6),
  tocEntry("5. Architecture cible", 7),
  tocEntry("6. Architecture multi-broker", 8),
  tocEntry("7. IA et Auto-learning Strategy Engine", 8),
  tocEntry("8. Trading avancé et portefeuille", 9),
  tocEntry("9. Temps réel et performance", 9),
  tocEntry("10. Plugins et modules", 10),
  tocEntry("11. Sécurité et conformité", 10),
  tocEntry("12. Feuille de route 90 jours", 11),
  tocEntry("13. Checklist avant Live", 11),
  pageBreak(),
);

children.push(
  heading("1. Synthèse exécutive", 1),
  para("LeoTrade dispose déjà d’un socle riche : moteur de risque, portefeuille et ledger, exécution multi-broker, signaux, IA, backtesting, notifications, Celery, Channels, Prometheus et Sentry. execution.Order est l’unique writer de production et une Outbox PostgreSQL garantit la reprise des commandes et projections. Le Recovery Worker ne rejoue jamais une mutation Live ambiguë, recherche l’ordre précis chez Binance, MT5 ou Deriv, puis déclenche le kill switch si l’incertitude dépasse le SLO. Un collecteur opérationnel persiste toutes les 30 secondes les ordres inconnus, retards de réconciliation, brokers dégradés, dead-letters et kill switches ; la readiness vérifie ce heartbeat, Prometheus l’expose et l’alerting signale incident puis rétablissement. Le suivi Deriv reste actif jusqu’au règlement, la protection SL/TP/trailing Paper est reduce-only et le Backtesting Engine réconcilie equity, PnL et frais. Les stratégies, signaux et validations sont isolés par utilisateur ; chaque ordre de stratégie Live exige un StrategyDeployment actif et auditable."),
  heading("Décision recommandée", 2),
  callout(
    "GO conditionnel pour Paper et environnement contrôlé",
    "Le mode Paper peut être utilisé après migration et tests de fumée. Le Live doit rester sous validation utilisateur, limites conservatrices et supervision renforcée jusqu’aux tests de bout en bout sur comptes broker de démonstration avec pannes injectées.",
    "FFF4E5",
    colors.amber,
  ),
  para(""),
  table(
    ["Domaine", "État", "Appréciation"],
    [
      ["Risk Engine", "Solide mais dispersé", "Fail-closed, profils, kill switch et contrôles avancés présents. À unifier autour d’une seule façade."],
      ["Exécution", "Unifiée et résiliente", "Writer OMS unique, idempotence, Recovery Worker, état ambigu, Outbox, kill switch dernier kilomètre, clôture ciblée et routage par déploiement."],
      ["Brokers", "Opérationnel partiel", "Gateway différé, circuit fail-closed sur mutation, lookup ciblé et adapters présents. Validation Live réelle à compléter par broker."],
      ["Portfolio / PnL", "Bon socle", "Ledger, positions et trades fermés existent. Reconciliation et historiques doivent rester source de vérité."],
      ["IA / Signaux", "Renforcé", "Scoring multi-facteurs branché, destinataire explicite, validation auditée et modèles système en lecture seule."],
      ["Temps réel / Ops", "Durable et supervisé", "Outbox, heartbeat Beat/worker, readiness stricte, métriques SLO, alertes dédupliquées et rétablissement."],
      ["Backtesting", "Renforcé", "Run unique, coûts configurables, checksum des données, métriques réconciliées et reprise des workers bloqués."],
      ["Sécurité", "Renforcée", "Secrets chiffrés, production durcie, stratégies/signaux cloisonnés, consentement d’auto-exécution et idempotence par compte."],
    ],
    [2100, 1700, 5226],
  ),
);

children.push(
  heading("2. Méthode et couverture", 1),
  para("L’audit a combiné lecture ciblée des services critiques, recherche de chemins concurrents, analyse des contrats de données broker, contrôles Django, compilation Python, contrôle des migrations et exécution de la suite de tests."),
  bullet("Exécution et ordres : états, transactions, idempotence, fills, cash lock, annulation et réconciliation."),
  bullet("Brokers : Deriv, Binance et MT5, avec contrôle des adapters, du gateway, des erreurs et des contraintes de précision."),
  bullet("Risk / PnL : logique fail-closed, limites, ledger, positions, realized/unrealized PnL et kill switch."),
  bullet("IA : extraction de features, scoring multi-facteurs, régime, patterns, feedback et traçabilité."),
  bullet("Temps réel : consumers authentifiés, groupes Channels, broadcasts et dépendance Redis."),
  bullet("Asynchrone : tâches Celery, idempotence, erreurs et chemins de maintenance."),
  bullet("Sécurité : paramètres production, secrets, cookies, TLS, exposition API et journalisation."),
  heading("Validation exécutée", 2),
  table(
    ["Contrôle", "Résultat"],
    [
      ["Compilation Python", "Succès"],
      ["Django system check", "0 erreur"],
      ["Migrations — dry run", "Aucun changement non généré"],
      ["Suite pytest", "333 tests collectés ; suite verte avec 1 test ignoré"],
      ["Check production", "Valide avec une SECRET_KEY forte ; l’ancienne clé locale faible est désormais bloquée"],
      ["Contrôle whitespace/diff", "Succès"],
    ],
    [3600, 5426],
  ),
);

children.push(
  heading("3. Correctifs critiques appliqués", 1),
  table(
    ["Sévérité", "Défaut", "Correction"],
    [
      ["P0", "Le démarrage production appelait env.bool, inexistant.", "Utilisation du helper réel et blocage des clés secrètes faibles."],
      ["P0", "La synchronisation Deriv construisait BrokerPositionDTO avec des champs invalides, puis retournait silencieusement une liste vide.", "Mapping corrigé vers entry_price, average_entry_price, margin_used et metadata, avec test."],
      ["P0", "Un ordre Paper sans prix pouvait être rempli à zéro et corrompre PnL et positions.", "Rejet explicite si le prix de référence n’est pas strictement positif."],
      ["P0", "Les mutations Binance étaient rejouées automatiquement en cas de timeout, avec risque d’état ambigu ou de duplication.", "Un seul envoi ; récupération ultérieure via clientOrderId et réconciliation."],
      ["P1", "Les adapters Live contournaient le Gateway et le client pouvait se connecter avant le contrôle Redis du circuit.", "Gateway systématique et construction différée ; une mutation échoue avant tout I/O si l’état partagé du circuit est indisponible, tandis que les lectures de reprise restent permises."],
      ["P1", "Deux orchestrateurs et des exécuteurs spécialisés écrivaient dans des modèles d’ordre concurrents ou appelaient les brokers directement.", "execution.Order est l’unique writer de production ; ExecuteSignal et DerivExecutor sont des façades compatibles vers l’OMS, les interfaces historiques sont read-only et un test statique bloque toute régression."],
      ["P1", "Un commit pouvait réussir alors que la commande Celery ou le broadcast Redis était perdu.", "Outbox transactionnelle, relay périodique, backoff exponentiel, verrouillage et dead-letter administrable."],
      ["P1", "Un worker perdu après SUBMITTING laissait l’ordre bloqué ; une relivraison ne pouvait pas déterminer si le broker avait été appelé.", "Revendication atomique, Recovery Worker périodique, replay Paper uniquement et conversion Live en UNKNOWN_BROKER_STATE sans second envoi."],
      ["P1", "La réconciliation ne lisait que les ordres encore ouverts ; un ordre rempli rapidement pouvait rester inconnu et une annulation distante laisser du cash verrouillé.", "Lookup ciblé Binance/MT5/Deriv, fills réconciliés, libération terminale idempotente, appels réseau hors transaction et kill switch si l’état reste inconnu au-delà du SLO."],
      ["P1", "La readiness ne prouvait ni le fonctionnement de Beat/worker ni les SLO métier ; Flower était déclaré sans dépendance installée et publié sans authentification.", "Snapshot opérationnel 30 s, métriques Prometheus, alertes avec reprise, diagnostic staff/CLI, sondes Docker worker/Beat, Flower 2.0.1 obligatoire et Basic Auth fail-closed."],
      ["P0", "Un contrat Deriv sortait du suivi périodique dès que l’achat remplissait l’ordre ; son règlement recherchait en plus la position du mauvais côté.", "Suivi des contrats ouverts par BrokerExternalRef indépendamment du statut FILLED, clôture de la position d’ouverture et comptabilisation idempotente du cash retourné et du PnL."],
      ["P1", "Deux workers pouvaient créer le même fill malgré un test applicatif.", "Lock avant relecture, contrainte unique conditionnelle et migration de déduplication."],
      ["P1", "Le retry du gateway rejouait aussi les erreurs de validation non transitoires.", "Classification explicite des exceptions retryables."],
      ["P1", "Le nouveau scoring IA existait sans être utilisé par la génération réelle.", "Connexion du pipeline features → régime → patterns → scoring multi-facteurs."],
      ["P1", "Les SL/TP/trailing étaient calculés mais ni persistés ni exécutés ; une clôture pouvait aussi débiter le cash une seconde fois.", "PositionProtectionService, réservation unique, ordre reduce-only ciblé et comptabilité de sortie corrigée."],
      ["P1", "Le backtesting créait un run temporaire, ignorait ses paramètres persistés et ne conservait ni journal de trades ni preuve des données.", "Run unique revendiqué atomiquement, coûts spread/slippage, validation OHLCV, checksum, journal borné et invariants equity/PnL/frais."],
      ["P0", "Tout utilisateur authentifié pouvait modifier une stratégie globale, approuver un signal tiers ou l’associer à son ordre.", "Ownership Strategy/Signal, querysets cloisonnés, modèles système read-only, validation auditée et contrôles ordre/signal/actif/sens. Les clés d’idempotence sont aussi isolées par compte et endpoint."],
      ["P0", "Une stratégie Live ne portait ni utilisateur d’exécution, ni portefeuille, ni broker ; une liaison devenue invalide pouvait encore atteindre le worker.", "StrategyDeployment actif et unique, mode cohérent, broker Live vérifié, auto-exécution opt-in, revalidation au dernier kilomètre et référence persistée sur le run et l’ordre."],
    ],
    [1100, 3470, 4456],
  ),
  heading("Fichiers principaux modifiés", 2),
  bullet("core/outbox.py, monitoring.py, metrics.py et tasks.py : Outbox, snapshot opérationnel, heartbeat, métriques et alertes avec reprise."),
  bullet("infrastructure/broker_clients/*, execution/reconciliation.py et portfolio/services.py : gateway différé, lookup ciblé, réconciliation terminale et cash idempotent."),
  bullet("execution/protection.py, services_close.py, trading/tasks.py et brokers/services/deriv_sync.py : protections reduce-only et cycle Deriv jusqu’au règlement."),
  bullet("trading/services/* et leo_backtesting/* : scoring multi-facteurs branché et backtesting reproductible/auditable."),
  bullet("strategies/models.py, views.py, signal_review.py et deployment.py : ownership, validation et déploiement user/portfolio/broker."),
  bullet("settings, Docker, règles Prometheus, migrations 0003 à 0007 et tests_phase/* : déploiement supervisé et garanties critiques."),
);

children.push(
  heading("4. Risques résiduels prioritaires", 1),
  table(
    ["Priorité", "Risque", "Action recommandée"],
    [
      ["P2", "Deriv fetch_open_orders retourne vide ; la vérité des contrats est désormais maintenue par BrokerExternalRef et les tâches dédiées, mais pas exposée comme collection d’ordres distants normalisée.", "Ajouter un DTO de contrat distant et des métriques d’âge/retard de règlement sans dupliquer l’OMS."],
      ["P2", "L’Outbox actuelle relaie vers Celery et Channels mais ne constitue pas encore un journal interservices longue durée.", "Ajouter Redis Streams seulement lorsque replay métier, projections multiples ou services séparés le justifient."],
      ["P1", "Les protections automatiques sont validées en Paper ; MT5 statique est déclaré natif, Binance/Deriv et trailing MT5 restent explicitement désactivés.", "Valider puis activer chaque capacité sur comptes demo, sans fallback générique dangereux."],
      ["P1", "Les appels Live ne sont pas validés par des tests d’intégration sur comptes de démonstration.", "Pipeline nightly sandbox/demo avec limites minimales et réconciliation obligatoire."],
      ["P2", "Le moteur de backtesting est fiable mais reste limité à SMA Cross et à une approximation du slippage par spread additionnel.", "Ajouter un registre de stratégies, bid/ask historique, latence, partial fills, walk-forward et Monte Carlo."],
      ["P1", "Les pannes Redis, timeout, réponse perdue et worker interrompu sont couvertes de façon déterministe, mais pas encore sur des comptes broker de démonstration.", "Rejouer ces scénarios chaque nuit sur sandbox/demo avec ordre minimal, limites strictes et réconciliation obligatoire."],
      ["P2", "Plusieurs except Exception restent très larges et peuvent masquer les défauts métier.", "Introduire une taxonomie BrokerError / RiskError / DataError et limiter les catches best-effort."],
      ["P2", "Dépendances vieillissantes signalées : STATICFILES_STORAGE, python-json-logger, websockets et SSL local LibreSSL.", "Planifier la montée de version Python/Django et le nettoyage des warnings."],
      ["P3", "Le dossier staticfiles absent produit des warnings en tests.", "Créer le répertoire au build ou ajuster la configuration de test."],
    ],
    [1100, 3850, 4076],
  ),
);

children.push(
  pageBreak(),
  heading("5. Architecture cible", 1),
  para("Pour LeoTrade, Redis Streams est le meilleur premier bus événementiel : il réutilise Redis déjà présent, réduit la complexité opérationnelle et apporte groupes de consommateurs, replay et backpressure. Kafka devient pertinent lorsque le volume, la rétention ou le nombre d’équipes dépasse les capacités d’un Redis Streams correctement dimensionné."),
  heading("Schéma logique", 2),
  table(
    ["Étape", "Composant", "Événement / contrat"],
    [
      ["1", "Market Data Ingestion", "market.candle.closed.v1"],
      ["2", "Feature & Regime Engine", "market.features.ready.v1"],
      ["3", "Signal Engine", "signal.created.v1"],
      ["4", "Risk Engine", "risk.decision.created.v1"],
      ["5", "Approval Service", "order.intent.approved.v1"],
      ["6", "Execution Engine / OMS", "order.submitted.v1, order.fill.v1"],
      ["7", "Broker Gateway", "broker.ack.v1, broker.error.v1"],
      ["8", "Portfolio Engine", "position.updated.v1, pnl.updated.v1"],
      ["9", "Realtime Projection", "dashboard.delta.v1"],
      ["10", "Journal / Learning", "trade.closed.v1, model.feedback.v1"],
    ],
    [900, 3050, 5076],
  ),
  para(""),
  callout(
    "Principe de cohérence",
    "PostgreSQL reste la source de vérité. Toute mutation critique écrit son état et un événement outbox dans la même transaction. Le relay actuel publie vers Celery et Channels avec event_id, retry exponentiel et dead-letter. Redis Streams devient l’étape suivante si un journal interservices rejouable est nécessaire.",
    colors.lightBlue,
    colors.blue,
  ),
  heading("Séparation des moteurs", 2),
  table(
    ["Moteur", "Responsabilité", "Ne doit pas faire"],
    [
      ["Signal Engine", "Features, régime, patterns, score, expiration.", "Calculer le sizing final ou appeler un broker."],
      ["Risk Engine", "Limites, exposition, sizing, kill switch, décision auditée.", "Générer un signal ou soumettre un ordre."],
      ["Execution Engine", "State machine OMS, idempotence, routage, fills, protection.", "Modifier le PnL directement sans événement de fill."],
      ["Portfolio Engine", "Positions, ledger, realized/unrealized PnL, snapshots.", "Appeler le broker pour créer un ordre."],
      ["Broker Gateway", "Adaptation, capacités, circuit breaker, normalisation.", "Prendre des décisions de risque."],
    ],
    [1800, 3700, 3526],
  ),
  heading("State machine ordre cible", 2),
  para("Flux nominal : DRAFT → RISK_PENDING → APPROVED → SUBMITTING → ACKNOWLEDGED → PARTIALLY_FILLED → FILLED. États terminaux : REJECTED, CANCELLED, EXPIRED ou FAILED. UNKNOWN_BROKER_STATE impose une réconciliation."),
);

children.push(
  heading("6. Architecture multi-broker", 1, { pageBreakBefore: true }),
  para("Chaque adapter doit exposer le même contrat et déclarer ses capacités. Les différences de produit ne doivent pas remonter dans le cœur métier sous forme de if broker == ... dispersés."),
  table(
    ["Capacité", "Binance Spot", "MT5", "Deriv"],
    [
      ["Market / Limit", "Oui", "Oui", "Contrats via proposal/buy"],
      ["Stop loss natif", "Selon type d’ordre", "Oui", "Selon contrat / update"],
      ["Trailing natif", "Variable", "Oui selon terminal", "À modéliser par type de contrat"],
      ["Positions", "Holdings reconstitués", "positions_get", "Portfolio de contrats"],
      ["Idempotence", "newClientOrderId", "magic + commentaire + reconciliation", "BrokerExternalRef + transaction_id"],
      ["Réconciliation", "Ordres + trades + balances", "orders/deals/positions", "Contrats + transactions + balance"],
    ],
    [2100, 2300, 2200, 2426],
  ),
  heading("Règles d’adapter", 2),
  bullet("Aucune mutation broker ne doit être rejouée aveuglément."),
  bullet("Un timeout après envoi produit UNKNOWN_BROKER_STATE, jamais FAILED définitif immédiat."),
  bullet("Les quantités, ticks, notionnels et devises sont normalisés avant soumission."),
  bullet("Les payloads bruts sont conservés pour audit, avec redaction des secrets."),
  bullet("Chaque méthode expose timeout, métriques, circuit state et correlation_id."),
  bullet("Les tests d’intégration utilisent les comptes demo/testnet officiels."),
  para([run("Références contrôlées : "), link("Binance Spot REST", "https://developers.binance.com/en/docs/products/spot/rest-api"), run(" · "), link("Deriv trading WebSocket", "https://developers.deriv.com/docs/trading/"), run(" · "), link("MT5 order_send", "https://www.mql5.com/en/docs/python_metatrader5/mt5ordersend_py")]),
);

children.push(
  heading("7. IA et Auto-learning Strategy Engine", 1),
  heading("Pipeline recommandé", 2),
  numbered("Construire les features techniques et de microstructure par version de schéma."),
  numbered("Détecter le régime de marché et les patterns interprétables."),
  numbered("Calculer un score multi-facteurs directionnel et un niveau de risque."),
  numbered("Appliquer une calibration de probabilité par modèle, symbole, timeframe et régime."),
  numbered("Passer le signal au Risk Engine, qui reste souverain sur le sizing."),
  numbered("Après clôture, écrire outcome, PnL, R-multiple, MFE, MAE, slippage et latence."),
  numbered("Réentraîner hors ligne, valider walk-forward, puis déployer en shadow avant promotion."),
  heading("ML simple à privilégier", 2),
  bullet("Baseline : LogisticRegression calibrée, avec features normalisées et classes BUY/SELL/HOLD."),
  bullet("Modèle arbre : HistGradientBoosting ou LightGBM si la dépendance est assumée."),
  bullet("Validation temporelle : jamais de split aléatoire sur séries financières."),
  bullet("Métriques : precision par classe, Brier score, calibration, expectancy, drawdown et turnover."),
  bullet("Garde-fou : un modèle ne peut augmenter les limites du Risk Engine."),
  heading("Confiance dynamique", 2),
  para("La confiance finale doit combiner confiance brute, calibration historique, qualité des données, adéquation au régime et performance récente. Le multiplicateur de feedback doit rester borné et revenir progressivement vers 1 pour éviter qu’une série courte ne domine le système."),
  callout(
    "Interdiction recommandée",
    "Pas d’apprentissage en ligne directement sur le chemin Live. Les nouveaux poids sont entraînés hors ligne, versionnés, évalués et promus explicitement après comparaison champion/challenger.",
    "FEE4E2",
    colors.red,
  ),
);

children.push(
  heading("8. Trading avancé et portefeuille", 1),
  heading("Ordres et protections", 2),
  para("Implémenté : état PositionProtection auditable, évaluation périodique toutes les 5 secondes, prix frais obligatoire, réservation d’une seule clôture active et exécution reduce-only ciblée. L’automatisation locale est activée en Paper ; les capacités Live non validées sont désactivées explicitement."),
  bullet("Stop loss initial obligatoire selon profil, sauf instruments dont le risque maximal est intrinsèquement borné."),
  bullet("Break-even après seuil R configurable, avec hystérésis pour éviter les oscillations."),
  bullet("Trailing ATR ou pourcentage, jamais déplacé dans le sens défavorable."),
  bullet("Take profit par paliers, avec gestion explicite des fractions déjà clôturées."),
  bullet("Ordres reduce-only pour toute fermeture afin d’éviter l’ouverture accidentelle d’une position opposée."),
  heading("Allocation du capital", 2),
  bullet("Risk budget par stratégie, classe d’actifs, broker et régime."),
  bullet("Plafond d’exposition corrélée, pas seulement par symbole."),
  bullet("Volatility targeting et limitation de levier effective après contraintes broker."),
  bullet("Cash lock idempotent avant soumission ; release uniquement sur preuve d’échec ou annulation."),
  heading("PnL", 2),
  para("Le ledger et les Trade fermés doivent rester la source de vérité du realized PnL. L’unrealized PnL se calcule sur le coût moyen et le dernier prix marqué, avec conversion FX explicite. Les imports broker dont le coût est inconnu doivent rester étiquetés UNKNOWN et ne pas produire un realized PnL inventé."),
);

children.push(
  heading("9. Temps réel et performance", 1),
  table(
    ["Sujet", "Cible"],
    [
      ["WebSocket", "Un consumer par domaine, authentification, groupes par user/portfolio, schémas versionnés."],
      ["Broadcast", "Après commit uniquement, payload delta, pas de snapshot complet à chaque fill."],
      ["Cache", "Redis pour latest quote, latest features, circuit state et projections dashboard."],
      ["Streaming", "Redis Streams par famille d’événements avec consumer groups et dead-letter stream."],
      ["Celery", "Queues séparées market, signals, execution, reconciliation, notifications, backtests."],
      ["Latence", "Mesurer tick→feature, feature→signal, approval→broker ack, ack→dashboard."],
      ["Backpressure", "Décimer les ticks UI, conserver les candles et événements métier complets."],
    ],
    [2200, 6826],
  ),
  heading("SLO proposés", 2),
  bullet("Disponibilité API trading : 99,9 % hors dépendance broker."),
  bullet("Signal validé → soumission broker p95 : moins de 500 ms hors validation humaine."),
  bullet("Broker ack → dashboard p95 : moins de 250 ms."),
  bullet("Réconciliation portefeuille : moins de 60 s de retard en Live."),
  bullet("Ordre broker inconnu : nouvelle entrée bloquée au plus tard après 5 minutes."),
  bullet("Aucun fill dupliqué ; aucun ordre Live sans décision de risque auditée."),
);

children.push(
  heading("10. Plugins et modules", 1),
  table(
    ["Module", "État actuel", "Prochaine étape"],
    [
      ["Backtesting", "Run unique, Outbox, coûts, checksum, journal et invariants comptables.", "Registre multi-stratégies, bid/ask, latence, walk-forward et Monte Carlo."],
      ["Paper Trading", "Présent ; garde-fou prix zéro ajouté.", "Order book simulé, partial fills, spread et événements de marché reproductibles."],
      ["Trade Journal", "Données disponibles via Trade, feedback et logs.", "Vue consolidée par stratégie avec MFE/MAE, screenshots et tags."],
      ["Alerting", "Façade opérationnelle Email/Telegram/Webhook, anti-tempête, retry et message de rétablissement.", "Accusé réception, calendrier d’astreinte et escalade multi-équipe."],
      ["Monitoring", "Snapshot 30 s, readiness Beat/worker, métriques métier, règles Prometheus, Sentry et logs structurés.", "Provisionner dashboards Grafana, Alertmanager et tracing OpenTelemetry."],
      ["Auto-learning", "Composants scoring/feedback présents.", "Registry de datasets, entraînement offline, validation et promotion contrôlée."],
    ],
    [1900, 3200, 3926],
  ),
);

children.push(
  heading("11. Sécurité et conformité", 1),
  bullet("Conserver les credentials chiffrés et séparer les clés de chiffrement de la base de données."),
  bullet("Utiliser des clés API broker sans retrait, avec IP allowlist et permissions minimales."),
  bullet("Utiliser en production une SECRET_KEY forte et unique ; ne jamais promouvoir la valeur locale de développement."),
  bullet("Journaliser toute lecture de secret, changement de risque, activation Live et override du kill switch."),
  bullet("Conserver les modèles système en lecture seule ; toute décision exécutable doit porter un utilisateur et une trace reviewed_by/reviewed_at."),
  bullet("Ajouter approbation forte ou 2FA pour activation Live, retrait et modification des limites."),
  bullet("Appliquer rate limit atomique Redis sur endpoints sensibles ; éviter get/set non atomique."),
  bullet("Mettre en place sauvegardes chiffrées, restauration testée et rétention du journal d’audit."),
  bullet("Effectuer une revue juridique selon les juridictions, la nature du conseil et l’exécution pour compte de tiers."),
  heading("Déploiement", 2),
  para("La production active TLS, HSTS, cookies Secure/HttpOnly, Redis, SECRET_KEY forte, workers séparés, readiness avec heartbeat et Flower authentifié. À compléter : migrations contrôlées, rollback automatisé, secrets manager et sauvegardes restaurées en exercice."),
);

children.push(
  heading("12. Feuille de route 90 jours", 1),
  table(
    ["Horizon", "Objectifs", "Critère de sortie"],
    [
      ["0–30 jours", "Rejouer la résilience en demo, tester les protections et brancher Alertmanager/Grafana.", "Convergence sans doublon ; alerte SLO puis rétablissement reçus."],
      ["31–60 jours", "Take-profit partiel, trailing Live par capacités, journal avancé et queues Celery séparées.", "Protection appliquée et auditée en Paper puis sur comptes demo."],
      ["61–90 jours", "ML calibré, walk-forward, champion/challenger, SLO, restauration et exercices de reprise.", "Promotion modèle gouvernée et rapport de résilience demo validé."],
      ["Après 90 jours", "Kafka si nécessaire, multi-région, DR, conformité et pentest externe.", "RTO/RPO démontrés et validation sécurité indépendante."],
    ],
    [1300, 4500, 3226],
  ),
);

children.push(
  heading("13. Checklist avant Live", 1),
  bullet("Appliquer les migrations listées et vérifier makemigrations --check."),
  bullet("Configurer SECRET_KEY et FLOWER_BASIC_AUTH avec des secrets forts stockés hors dépôt."),
  bullet("Tester chaque broker sur compte demo/testnet avec ordre minimal, annulation et réconciliation."),
  bullet("Vérifier les limites de risque, kill switch, 2FA et permissions API sans retrait."),
  bullet("Confirmer writer OMS unique, prix Paper positif, fills uniques et suivi Deriv jusqu’au terminal."),
  bullet("Rejouer sur comptes demo les tests automatisés : panne Redis, timeout broker, worker tué et réponse perdue."),
  bullet("Brancher leotrade-alerts.yml à Prometheus/Alertmanager, tester la restauration puis déployer progressivement."),
  heading("Conclusion", 2),
  para("LeoTrade a dépassé le prototype : OMS unique, événements durables, reprise Live sans doublon, isolation, protections, backtesting et supervision métier. Priorité : brancher Alertmanager puis valider ces garanties sur comptes demo avant d’augmenter l’autonomie."),
);

const doc = new Document({
  creator: "OpenAI Codex",
  title: "LeoTrade — Intelligent Trading — Audit technique et architecture cible",
  description: "Audit production-ready de la plateforme LeoTrade",
  styles: {
    default: { document: { run: { font: "Arial", size: 21, color: colors.black } } },
    paragraphStyles: [
      {
        id: "Heading1",
        name: "Heading 1",
        basedOn: "Normal",
        next: "Normal",
        quickFormat: true,
        run: { font: "Arial", size: 32, bold: true, color: colors.navy },
        paragraph: { spacing: { before: 320, after: 180 }, outlineLevel: 0 },
      },
      {
        id: "Heading2",
        name: "Heading 2",
        basedOn: "Normal",
        next: "Normal",
        quickFormat: true,
        run: { font: "Arial", size: 26, bold: true, color: colors.blue },
        paragraph: { spacing: { before: 240, after: 130 }, outlineLevel: 1 },
      },
      {
        id: "Heading3",
        name: "Heading 3",
        basedOn: "Normal",
        next: "Normal",
        quickFormat: true,
        run: { font: "Arial", size: 22, bold: true, color: colors.blue },
        paragraph: { spacing: { before: 180, after: 100 }, outlineLevel: 2 },
      },
    ],
  },
  numbering: {
    config: [
      {
        reference: "audit-bullets",
        levels: [
          { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 260 } } } },
          { level: 1, format: LevelFormat.BULLET, text: "◦", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 980, hanging: 260 } } } },
        ],
      },
      {
        reference: "audit-numbers",
        levels: [
          { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 560, hanging: 300 } } } },
        ],
      },
      {
        reference: "audit-roadmap-numbers",
        levels: [
          { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 560, hanging: 300 } } } },
        ],
      },
    ],
  },
  sections: [
    {
      properties: {
        page: {
          size: { width: 11906, height: 16838 },
          margin: { top: 1220, right: 1440, bottom: 1220, left: 1440 },
        },
      },
      headers: {
        default: new Header({ children: [
          new Paragraph({
            border: { bottom: { style: BorderStyle.SINGLE, size: 5, color: colors.cyan, space: 1 } },
            children: [run("LEOTRADE  ·  INTELLIGENT TRADING  ·  AUDIT & ARCHITECTURE", { bold: true, size: 16, color: colors.gray })],
          }),
        ] }),
      },
      footers: {
        default: new Footer({ children: [
          new Paragraph({
            alignment: AlignmentType.RIGHT,
            children: [run("Confidentiel  ·  Page ", { size: 16, color: colors.gray }), new TextRun({ children: [PageNumber.CURRENT], font: "Arial", size: 16, color: colors.gray })],
          }),
        ] }),
      },
      children,
    },
  ],
});

Packer.toBuffer(doc).then((buffer) => {
  fs.writeFileSync(OUTPUT, buffer);
  process.stdout.write(`${OUTPUT}\n`);
});
