// Modèles du Risk Control, alignés sur risk/services_summary.py.
//
// Les pourcentages restent en String comme les montants : ils sont calculés
// en Decimal côté serveur, et c'est le même raisonnement qui s'applique.

/// Une limite et la part déjà consommée.
class RiskLimit {
  const RiskLimit({
    required this.key,
    required this.label,
    required this.consumedPercent,
    required this.limitPercent,
    required this.usagePercent,
  });

  factory RiskLimit.fromJson(Map<String, dynamic> json) => RiskLimit(
        key: json['key'] as String? ?? '',
        label: json['label'] as String? ?? '',
        consumedPercent: '${json['consumed_percent'] ?? '0'}',
        limitPercent: '${json['limit_percent'] ?? '0'}',
        // null = aucune limite posée. Afficher « 0 % utilisé » laisserait
        // croire à une protection qui n'existe pas.
        usagePercent: json['usage_percent'] == null
            ? null
            : '${json['usage_percent']}',
      );

  final String key;
  final String label;
  final String consumedPercent;
  final String limitPercent;
  final String? usagePercent;

  bool get hasLimit => usagePercent != null;

  double get usage => double.tryParse(usagePercent ?? '') ?? 0;

  bool get isBreached => hasLimit && usage >= 100;

  bool get isNearLimit => hasLimit && usage >= 75 && usage < 100;
}

class RiskProfileSummary {
  const RiskProfileSummary({
    required this.id,
    required this.name,
    required this.preservationMode,
    required this.allowVolatile,
    required this.allowSpeculative,
    required this.requireStopLoss,
    required this.killSwitchEnabled,
    required this.maxRiskPerTrade,
    required this.maxOpenPositions,
  });

  factory RiskProfileSummary.fromJson(Map<String, dynamic> json) =>
      RiskProfileSummary(
        id: json['id'] as int,
        name: json['name'] as String? ?? '',
        // Défauts prudents : en l'absence d'information, on ne prétend pas
        // qu'une protection est active ni qu'un instrument risqué est permis.
        preservationMode: json['preservation_mode'] as bool? ?? true,
        allowVolatile: json['allow_volatile_instruments'] as bool? ?? false,
        allowSpeculative: json['allow_speculative_instruments'] as bool? ?? false,
        requireStopLoss: json['require_stop_loss'] as bool? ?? true,
        killSwitchEnabled: json['kill_switch_enabled'] as bool? ?? true,
        maxRiskPerTrade: '${json['max_risk_per_trade'] ?? ''}',
        maxOpenPositions: json['max_open_positions'] as int? ?? 0,
      );

  final int id;
  final String name;
  final bool preservationMode;
  final bool allowVolatile;
  final bool allowSpeculative;
  final bool requireStopLoss;
  final bool killSwitchEnabled;
  final String maxRiskPerTrade;
  final int maxOpenPositions;
}

class RiskSummary {
  const RiskSummary({
    required this.portfolioId,
    required this.profile,
    required this.killSwitchActive,
    required this.killSwitchReason,
    required this.killSwitchReasonCode,
    required this.limits,
    required this.openPositions,
    required this.maxOpenPositions,
  });

  factory RiskSummary.fromJson(Map<String, dynamic> json) {
    final rawLimits = json['limits'];
    return RiskSummary(
      portfolioId: json['portfolio_id'] as int,
      profile: json['profile'] is Map<String, dynamic>
          ? RiskProfileSummary.fromJson(json['profile'] as Map<String, dynamic>)
          : null,
      killSwitchActive: json['kill_switch_active'] as bool? ?? false,
      killSwitchReason: json['kill_switch_reason'] as String? ?? '',
      killSwitchReasonCode: json['kill_switch_reason_code'] as String? ?? '',
      limits: rawLimits is List
          ? rawLimits
              .whereType<Map<String, dynamic>>()
              .map(RiskLimit.fromJson)
              .toList(growable: false)
          : const [],
      openPositions: json['open_positions'] as int? ?? 0,
      maxOpenPositions: json['max_open_positions'] as int? ?? 0,
    );
  }

  final int portfolioId;
  final RiskProfileSummary? profile;
  final bool killSwitchActive;
  final String killSwitchReason;
  final String killSwitchReasonCode;
  final List<RiskLimit> limits;
  final int openPositions;
  final int maxOpenPositions;

  /// Au moins une limite franchie, kill switch compris.
  bool get hasBreach =>
      killSwitchActive || limits.any((limit) => limit.isBreached);
}
