import 'package:flutter_test/flutter_test.dart';
import 'package:leotrade/features/market/domain/models.dart';
import 'package:leotrade/shared/charts/candle_chart.dart';

void main() {
  group('CandlePoint.tryParse', () {
    test('lit une bougie complète', () {
      final point = CandlePoint.tryParse(
        open: '100.5', high: '102', low: '99', close: '101',
      );

      expect(point, isNotNull);
      expect(point!.isUp, isTrue);
    });

    test('une bougie incomplète est écartée, pas dessinée à zéro', () {
      // Une valeur manquante interprétée comme 0 écraserait toute
      // l'échelle verticale du graphique.
      expect(CandlePoint.tryParse(open: '100', high: null, low: '99', close: '101'),
          isNull);
      expect(CandlePoint.tryParse(open: '100', high: '', low: '99', close: '101'),
          isNull);
    });

    test('une valeur illisible est écartée', () {
      expect(
        CandlePoint.tryParse(open: 'n/a', high: '102', low: '99', close: '101'),
        isNull,
      );
    });

    test('distingue hausse et baisse', () {
      final up = CandlePoint.tryParse(
          open: '100', high: '102', low: '99', close: '101')!;
      final down = CandlePoint.tryParse(
          open: '101', high: '102', low: '99', close: '100')!;

      expect(up.isUp, isTrue);
      expect(down.isUp, isFalse);
    });

    test('une bougie plate compte comme une hausse, jamais comme indéfinie', () {
      final flat = CandlePoint.tryParse(
          open: '100', high: '100', low: '100', close: '100')!;

      expect(flat.isUp, isTrue);
    });
  });

  group('CandleHistory', () {
    Map<String, dynamic> json({
      String freshness = 'LIVE',
      List<Map<String, dynamic>>? candles,
    }) =>
        {
          'symbol': 'BTCUSDT',
          'source': 'BINANCE',
          'timeframe': '1d',
          'freshness': freshness,
          'freshness_label': 'x',
          'as_of': '2026-03-29T23:59:59Z',
          'age_seconds': 8 * 30 * 86400,
          'candles': candles ??
              [
                {
                  'open_time': '2026-03-29T00:00:00Z',
                  'open': '100', 'high': '102', 'low': '99', 'close': '101',
                },
              ],
        };

    test('signale une série périmée', () {
      final history = CandleHistory.fromJson(json(freshness: 'STALE'));

      expect(history.isStale, isTrue);
      expect(history.asOf, isNotNull);
    });

    test('une série vide se dit, sans bougie inventée', () {
      final history = CandleHistory.fromJson(json(candles: []));

      expect(history.hasData, isFalse);
      expect(history.candles, isEmpty);
    });

    test('une fraîcheur inconnue ne passe pas pour fraîche', () {
      final history = CandleHistory.fromJson(json(freshness: 'BIZARRE'));

      expect(history.freshness, Freshness.noData);
    });

    test('un champ candles absent ne fait pas échouer la lecture', () {
      final history = CandleHistory.fromJson({
        'symbol': 'X', 'source': 'Y', 'freshness': 'LIVE',
      });

      expect(history.hasData, isFalse);
    });
  });
}
