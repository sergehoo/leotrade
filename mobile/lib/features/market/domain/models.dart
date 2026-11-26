// Modèles des marchés, alignés sur market/services_quotes.py.
//
// Une cotation ne voyage jamais sans sa date, son âge et sa classe de
// fraîcheur. Un prix sans date est un prix qu'on croit courant, et c'est
// sur cette croyance qu'on décide.

enum Freshness { live, delayed, stale, noData }

Freshness freshnessFrom(String? raw) => switch (raw) {
      'LIVE' => Freshness.live,
      'DELAYED' => Freshness.delayed,
      'STALE' => Freshness.stale,
      // Valeur inconnue : on ne prétend pas que la donnée est fraîche.
      _ => Freshness.noData,
    };

class Quote {
  const Quote({
    required this.assetId,
    required this.symbol,
    required this.name,
    required this.assetClass,
    required this.source,
    required this.freshness,
    required this.freshnessLabel,
    required this.isTradableQuote,
    this.price,
    this.changePercent,
    this.asOf,
    this.ageSeconds,
    this.timeframe,
  });

  factory Quote.fromJson(Map<String, dynamic> json) => Quote(
        assetId: json['asset_id'] as int,
        symbol: json['symbol'] as String? ?? '',
        name: json['name'] as String? ?? '',
        assetClass: json['asset_class'] as String? ?? '',
        source: json['source'] as String? ?? '',
        freshness: freshnessFrom(json['freshness'] as String?),
        freshnessLabel: json['freshness_label'] as String? ?? 'Aucune donnée',
        // Défaut prudent : sans information, on n'autorise pas la décision.
        isTradableQuote: json['is_tradable_quote'] as bool? ?? false,
        price: json['price'] as String?,
        changePercent: json['change_percent'] as String?,
        asOf: DateTime.tryParse('${json['as_of'] ?? ''}'),
        ageSeconds: json['age_seconds'] as int?,
        timeframe: json['timeframe'] as String?,
      );

  final int assetId;
  final String symbol;
  final String name;
  final String assetClass;

  /// Place d'où vient le chiffre.
  final String source;

  final Freshness freshness;
  final String freshnessLabel;

  /// Faux dès que la cotation n'est plus à jour.
  final bool isTradableQuote;

  /// Montants en chaîne : calculés en Decimal côté serveur.
  final String? price;
  final String? changePercent;

  /// Horodatage de la bougie dont le prix est tiré.
  final DateTime? asOf;
  final int? ageSeconds;
  final String? timeframe;

  bool get hasPrice => price != null && price!.isNotEmpty;

  bool get isStale => freshness == Freshness.stale;

  /// Ancienneté en clair.
  String get ageLabel {
    final seconds = ageSeconds;
    if (seconds == null) return '—';
    if (seconds < 60) return 'il y a moins d\'une minute';
    final minutes = seconds ~/ 60;
    if (minutes < 60) return 'il y a $minutes min';
    final hours = minutes ~/ 60;
    if (hours < 24) return 'il y a $hours h';
    final days = hours ~/ 24;
    if (days < 31) return 'il y a $days j';
    return 'il y a ${days ~/ 30} mois';
  }
}

class WatchlistEntry {
  const WatchlistEntry({
    required this.id,
    required this.assetId,
    required this.symbol,
  });

  factory WatchlistEntry.fromJson(Map<String, dynamic> json) => WatchlistEntry(
        id: json['id'] as int,
        assetId: json['asset'] as int,
        symbol: json['symbol'] as String? ?? '',
      );

  final int id;
  final int assetId;
  final String symbol;
}
