import 'package:flutter_test/flutter_test.dart';
import 'package:leotrade/features/market/domain/models.dart';

Map<String, dynamic> _quoteJson({
  String? price = '100.00',
  String freshness = 'LIVE',
  Object? tradable = true,
  int? age = 60,
}) =>
    {
      'asset_id': 1,
      'symbol': 'BTCUSDT',
      'name': 'Bitcoin',
      'asset_class': 'CRYPTO',
      'source': 'BINANCE',
      'freshness': freshness,
      'freshness_label': 'x',
      if (tradable != null) 'is_tradable_quote': tradable,
      'price': price,
      'change_percent': '1.00',
      'as_of': '2026-11-26T09:00:00Z',
      'age_seconds': age,
    };

void main() {
  group('Freshness', () {
    test('une valeur inconnue ne passe jamais pour fraîche', () {
      // Prétendre « à jour » sur une classe qu'on ne comprend pas est
      // exactement l'erreur qui fait décider sur un prix périmé.
      expect(freshnessFrom('BIZARRE'), Freshness.noData);
      expect(freshnessFrom(null), Freshness.noData);
    });

    test('les classes connues sont reconnues', () {
      expect(freshnessFrom('LIVE'), Freshness.live);
      expect(freshnessFrom('DELAYED'), Freshness.delayed);
      expect(freshnessFrom('STALE'), Freshness.stale);
    });
  });

  group('Quote', () {
    test('un prix absent n\'est pas remplacé par un zéro', () {
      final quote = Quote.fromJson(_quoteJson(price: null, freshness: 'NO_DATA'));

      expect(quote.hasPrice, isFalse);
      expect(quote.price, isNull);
    });

    test('un cours périmé est signalé et non négociable', () {
      final quote = Quote.fromJson(
        _quoteJson(freshness: 'STALE', tradable: false, age: 150 * 86400),
      );

      expect(quote.isStale, isTrue);
      expect(quote.isTradableQuote, isFalse);
    });

    test('sans information, une cotation n\'est PAS présumée négociable', () {
      final quote = Quote.fromJson(_quoteJson(tradable: null));

      expect(quote.isTradableQuote, isFalse);
    });

    test('conserve le prix en chaîne, sans conversion', () {
      final quote = Quote.fromJson(_quoteJson(price: '0.00000123'));

      expect(quote.price, isA<String>());
      expect(quote.price, '0.00000123');
    });

    test('la source est portée par chaque cotation', () {
      expect(Quote.fromJson(_quoteJson()).source, 'BINANCE');
    });
  });

  group('Quote.ageLabel', () {
    test('rend une ancienneté lisible à chaque échelle', () {
      String label(int? seconds) =>
          Quote.fromJson(_quoteJson(age: seconds)).ageLabel;

      expect(label(30), contains('moins d\'une minute'));
      expect(label(600), 'il y a 10 min');
      expect(label(3 * 3600), 'il y a 3 h');
      expect(label(5 * 86400), 'il y a 5 j');
      expect(label(150 * 86400), 'il y a 5 mois');
    });

    test('un âge inconnu ne se déguise pas en « à l\'instant »', () {
      expect(Quote.fromJson(_quoteJson(age: null)).ageLabel, '—');
    });
  });
}
