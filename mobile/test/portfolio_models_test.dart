import 'package:flutter_test/flutter_test.dart';
import 'package:leotrade/features/portfolio/domain/models.dart';

Map<String, dynamic> _portfolioJson({
  bool? isSimulated = true,
  String mode = 'PAPER',
}) =>
    {
      'id': 3,
      'name': 'Portefeuille de simulation',
      'base_currency': 'USD',
      'trading_mode': mode,
      if (isSimulated != null) 'is_simulated': isSimulated,
      'is_default': true,
      'is_active': true,
      'equity': '10000.00',
      'broker_name': 'Simulation locale',
    };

void main() {
  group('Portfolio', () {
    test('lit le mode et le caractère simulé depuis le serveur', () {
      final portfolio = Portfolio.fromJson(_portfolioJson());

      expect(portfolio.isSimulated, isTrue);
      expect(portfolio.isLive, isFalse);
      expect(portfolio.baseCurrency, 'USD');
    });

    test('un portefeuille réel est reconnu comme tel', () {
      final portfolio =
          Portfolio.fromJson(_portfolioJson(isSimulated: false, mode: 'LIVE'));

      expect(portfolio.isLive, isTrue);
      expect(portfolio.isSimulated, isFalse);
    });

    test('en l\'absence d\'information, un portefeuille n\'est PAS présumé simulé', () {
      // L'erreur inverse ferait baisser la garde sur de l'argent réel :
      // mieux vaut afficher à tort l'avertissement « portefeuille réel »
      // que l'omettre à tort.
      final portfolio = Portfolio.fromJson(_portfolioJson(isSimulated: null));

      expect(portfolio.isSimulated, isFalse);
    });
  });

  group('PortfolioSummary', () {
    test('conserve les montants en chaîne, sans conversion', () {
      final summary = PortfolioSummary.fromJson({
        'portfolio_id': 3,
        'base_currency': 'USD',
        'is_simulated': true,
        'equity': '10000.00',
        'available_cash': '10000.00',
        'locked_cash': '0.00',
        'unrealized_pnl': '0.00',
        'realized_pnl': '0.00',
        'total_pnl': '0.00',
        'total_pnl_percent': '0.00',
        'exposure_value': '0.00',
        'exposure_percent': '0.00',
        'open_positions': 0,
        'long_positions': 0,
        'short_positions': 0,
      });

      // Le backend calcule en Decimal ; convertir ici rouvrirait les
      // erreurs d'arrondi que ce choix élimine.
      expect(summary.equity, isA<String>());
      expect(summary.equity, '10000.00');
      expect(summary.openPositions, 0);
    });

    test('une réponse incomplète ne fait pas échouer la lecture', () {
      final summary = PortfolioSummary.fromJson({
        'portfolio_id': 3,
        'base_currency': 'USD',
      });

      expect(summary.openPositions, 0);
      expect(summary.isSimulated, isFalse);
    });
  });

  group('Position', () {
    test('distingue long et short', () {
      final long = Position.fromJson({
        'id': 1, 'symbol': 'EURUSD', 'side': 'LONG',
        'quantity': '1.5', 'average_entry_price': '1.08',
        'current_price': '1.09', 'exposure_value': '1620.00',
        'unrealized_pnl': '15.00',
      });
      final short = Position.fromJson({
        'id': 2, 'symbol': 'EURUSD', 'side': 'SHORT',
        'quantity': '1.5', 'average_entry_price': '1.08',
        'current_price': '1.09', 'exposure_value': '1620.00',
        'unrealized_pnl': '-15.00',
      });

      expect(long.isLong, isTrue);
      expect(short.isLong, isFalse);
    });

    test('un sens inconnu est traité comme long, jamais comme une erreur', () {
      final position = Position.fromJson({
        'id': 1, 'symbol': 'EURUSD', 'side': 'INCONNU',
        'quantity': '1', 'average_entry_price': '1',
        'current_price': '1', 'exposure_value': '1', 'unrealized_pnl': '0',
      });

      expect(position.isLong, isTrue);
    });
  });
}
