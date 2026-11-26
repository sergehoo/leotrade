import 'package:flutter_test/flutter_test.dart';
import 'package:leotrade/features/wallet/domain/models.dart';

Map<String, dynamic> _summaryJson({
  Object? reconciled = true,
  String? unexplained = '0.00',
  String? available = '300.00',
  String? simulated = '10000.00',
}) =>
    {
      'has_wallet': true,
      'currency': 'USD',
      'available_balance': available,
      'locked_balance': '0.00',
      'total_balance': available,
      'simulated_trading_capital': simulated,
      'live_trading_capital': '0.00',
      'pending_withdrawals_count': 0,
      'pending_withdrawals_amount': '0.00',
      if (reconciled != null) 'is_reconciled': reconciled,
      'unexplained_amount': unexplained,
      'ledger_entry_count': 1,
    };

void main() {
  group('WalletSummary', () {
    test('sépare l\'argent réel du capital simulé', () {
      // Les additionner mentalement est l'erreur que ce découpage rend
      // difficile : 300 USD réels ne sont pas 10 300.
      final summary = WalletSummary.fromJson(_summaryJson());

      expect(summary.availableBalance, '300.00');
      expect(summary.simulatedTradingCapital, '10000.00');
      expect(summary.liveTradingCapital, '0.00');
    });

    test('signale un solde que le grand livre n\'explique pas', () {
      final summary = WalletSummary.fromJson(
        _summaryJson(reconciled: false, unexplained: '20000.00'),
      );

      expect(summary.hasUnexplainedFunds, isTrue);
      expect(summary.unexplainedAmount, '20000.00');
    });

    test('un portefeuille cohérent ne déclenche aucune alerte', () {
      final summary = WalletSummary.fromJson(_summaryJson());

      expect(summary.hasUnexplainedFunds, isFalse);
    });

    test('une absence de portefeuille se dit, sans zéros inventés', () {
      final summary = WalletSummary.fromJson({'has_wallet': false});

      expect(summary.hasWallet, isFalse);
      expect(summary.availableBalance, isNull);
      expect(summary.simulatedTradingCapital, isNull);
    });

    test('les montants restent en chaîne', () {
      final summary = WalletSummary.fromJson(_summaryJson(available: '0.01'));

      expect(summary.availableBalance, isA<String>());
      expect(summary.availableBalance, '0.01');
    });
  });

  group('LedgerEntry', () {
    Map<String, dynamic> entryJson(String type) => {
          'id': 1,
          'entry_type': type,
          'amount': '100.00',
          'currency': 'USD',
          'balance_after': '400.00',
          'description': 'Test',
          'created_at': '2026-11-26T09:00:00Z',
        };

    test('reconnaît les types de mouvement', () {
      expect(LedgerEntry.fromJson(entryJson('CREDIT')).type, LedgerEntryType.credit);
      expect(LedgerEntry.fromJson(entryJson('LOCK')).type, LedgerEntryType.lock);
      expect(LedgerEntry.fromJson(entryJson('FEE')).type, LedgerEntryType.fee);
    });

    test('un type inconnu reste affichable, sans être inventé', () {
      final entry = LedgerEntry.fromJson(entryJson('BIZARRE'));

      expect(entry.type, LedgerEntryType.unknown);
      expect(ledgerTypeLabel(entry.type), 'Mouvement');
    });

    test('porte le solde laissé derrière le mouvement', () {
      // C'est ce champ qui permet de vérifier la chaîne plutôt que de
      // faire confiance à un total.
      final entry = LedgerEntry.fromJson(entryJson('CREDIT'));

      expect(entry.balanceAfter, '400.00');
    });
  });
}
