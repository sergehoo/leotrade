// Modèles du domaine portefeuille, alignés sur api/serializers/portfolio.py.
//
// Les montants restent en String de bout en bout : le backend calcule en
// Decimal, Dart n'a pas d'équivalent natif, et les convertir en double pour
// les transporter rouvrirait les erreurs d'arrondi que ce choix élimine.
// Voir core/format.dart, qui ne parse qu'à l'affichage.

enum TradingMode { paper, live }

TradingMode tradingModeFrom(String? raw) =>
    raw == 'LIVE' ? TradingMode.live : TradingMode.paper;

class Portfolio {
  const Portfolio({
    required this.id,
    required this.name,
    required this.baseCurrency,
    required this.tradingMode,
    required this.isSimulated,
    required this.isDefault,
    required this.isActive,
    required this.equity,
    required this.brokerName,
  });

  factory Portfolio.fromJson(Map<String, dynamic> json) => Portfolio(
        id: json['id'] as int,
        name: json['name'] as String? ?? '',
        baseCurrency: json['base_currency'] as String? ?? 'USD',
        tradingMode: tradingModeFrom(json['trading_mode'] as String?),
        // Défaut prudent : en l'absence d'information, on ne prétend pas
        // qu'un portefeuille est simulé — l'erreur inverse ferait baisser
        // la garde sur de l'argent réel.
        isSimulated: json['is_simulated'] as bool? ?? false,
        isDefault: json['is_default'] as bool? ?? false,
        isActive: json['is_active'] as bool? ?? true,
        equity: '${json['equity'] ?? ''}',
        brokerName: json['broker_name'] as String?,
      );

  final int id;
  final String name;
  final String baseCurrency;
  final TradingMode tradingMode;
  final bool isSimulated;
  final bool isDefault;
  final bool isActive;
  final String equity;
  final String? brokerName;

  bool get isLive => tradingMode == TradingMode.live;
}

class PortfolioSummary {
  const PortfolioSummary({
    required this.portfolioId,
    required this.baseCurrency,
    required this.isSimulated,
    required this.equity,
    required this.availableCash,
    required this.lockedCash,
    required this.unrealizedPnl,
    required this.realizedPnl,
    required this.totalPnl,
    required this.totalPnlPercent,
    required this.exposureValue,
    required this.exposurePercent,
    required this.openPositions,
    required this.longPositions,
    required this.shortPositions,
  });

  factory PortfolioSummary.fromJson(Map<String, dynamic> json) => PortfolioSummary(
        portfolioId: json['portfolio_id'] as int,
        baseCurrency: json['base_currency'] as String? ?? 'USD',
        isSimulated: json['is_simulated'] as bool? ?? false,
        equity: '${json['equity'] ?? ''}',
        availableCash: '${json['available_cash'] ?? ''}',
        lockedCash: '${json['locked_cash'] ?? ''}',
        unrealizedPnl: '${json['unrealized_pnl'] ?? ''}',
        realizedPnl: '${json['realized_pnl'] ?? ''}',
        totalPnl: '${json['total_pnl'] ?? ''}',
        totalPnlPercent: '${json['total_pnl_percent'] ?? ''}',
        exposureValue: '${json['exposure_value'] ?? ''}',
        exposurePercent: '${json['exposure_percent'] ?? ''}',
        openPositions: json['open_positions'] as int? ?? 0,
        longPositions: json['long_positions'] as int? ?? 0,
        shortPositions: json['short_positions'] as int? ?? 0,
      );

  final int portfolioId;
  final String baseCurrency;
  final bool isSimulated;
  final String equity;
  final String availableCash;
  final String lockedCash;
  final String unrealizedPnl;
  final String realizedPnl;
  final String totalPnl;
  final String totalPnlPercent;
  final String exposureValue;
  final String exposurePercent;
  final int openPositions;
  final int longPositions;
  final int shortPositions;
}

enum PositionSide { long, short }

PositionSide positionSideFrom(String? raw) =>
    raw == 'SHORT' ? PositionSide.short : PositionSide.long;

class Position {
  const Position({
    required this.id,
    required this.symbol,
    required this.side,
    required this.quantity,
    required this.averageEntryPrice,
    required this.currentPrice,
    required this.exposureValue,
    required this.unrealizedPnl,
    this.assetName,
  });

  factory Position.fromJson(Map<String, dynamic> json) => Position(
        id: json['id'] as int,
        symbol: json['symbol'] as String? ?? '',
        side: positionSideFrom(json['side'] as String?),
        quantity: '${json['quantity'] ?? ''}',
        averageEntryPrice: '${json['average_entry_price'] ?? ''}',
        currentPrice: '${json['current_price'] ?? ''}',
        exposureValue: '${json['exposure_value'] ?? ''}',
        unrealizedPnl: '${json['unrealized_pnl'] ?? ''}',
        assetName: json['asset_name'] as String?,
      );

  final int id;
  final String symbol;
  final PositionSide side;
  final String quantity;
  final String averageEntryPrice;
  final String currentPrice;
  final String exposureValue;
  final String unrealizedPnl;
  final String? assetName;

  bool get isLong => side == PositionSide.long;
}
