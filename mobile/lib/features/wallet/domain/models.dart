// Modèles du portefeuille électronique, alignés sur
// wallet/services_summary.py.
//
// L'argent réel et le capital de trading sont deux réserves distinctes.
// Les additionner mentalement est l'erreur que ce découpage rend difficile.

class WalletSummary {
  const WalletSummary({
    required this.hasWallet,
    required this.currency,
    required this.availableBalance,
    required this.lockedBalance,
    required this.totalBalance,
    required this.simulatedTradingCapital,
    required this.liveTradingCapital,
    required this.pendingWithdrawalsCount,
    required this.pendingWithdrawalsAmount,
    required this.isReconciled,
    required this.unexplainedAmount,
    required this.ledgerEntryCount,
  });

  factory WalletSummary.fromJson(Map<String, dynamic> json) => WalletSummary(
        hasWallet: json['has_wallet'] as bool? ?? false,
        currency: json['currency'] as String? ?? 'USD',
        availableBalance: json['available_balance'] as String?,
        lockedBalance: json['locked_balance'] as String?,
        totalBalance: json['total_balance'] as String?,
        simulatedTradingCapital: json['simulated_trading_capital'] as String?,
        liveTradingCapital: json['live_trading_capital'] as String?,
        pendingWithdrawalsCount: json['pending_withdrawals_count'] as int? ?? 0,
        pendingWithdrawalsAmount: json['pending_withdrawals_amount'] as String?,
        // Défaut prudent inversé : en l'absence d'information on ne crie
        // pas à l'anomalie, mais `unexplainedAmount` reste nul et rien
        // n'est affirmé.
        isReconciled: json['is_reconciled'] as bool? ?? true,
        unexplainedAmount: json['unexplained_amount'] as String?,
        ledgerEntryCount: json['ledger_entry_count'] as int? ?? 0,
      );

  final bool hasWallet;
  final String currency;

  /// Argent réel.
  final String? availableBalance;
  final String? lockedBalance;
  final String? totalBalance;

  /// Capital dont les ordres n'atteignent aucun marché.
  final String? simulatedTradingCapital;

  /// Capital engagé sur un compte broker réel.
  final String? liveTradingCapital;

  final int pendingWithdrawalsCount;
  final String? pendingWithdrawalsAmount;

  /// Faux quand le grand livre n'explique pas tout le solde.
  final bool isReconciled;
  final String? unexplainedAmount;
  final int ledgerEntryCount;

  bool get hasUnexplainedFunds => !isReconciled;
}

enum LedgerEntryType { credit, debit, lock, unlock, fee, refund, unknown }

LedgerEntryType ledgerTypeFrom(String? raw) => switch (raw) {
      'CREDIT' => LedgerEntryType.credit,
      'DEBIT' => LedgerEntryType.debit,
      'LOCK' => LedgerEntryType.lock,
      'UNLOCK' => LedgerEntryType.unlock,
      'FEE' => LedgerEntryType.fee,
      'REFUND' => LedgerEntryType.refund,
      _ => LedgerEntryType.unknown,
    };

String ledgerTypeLabel(LedgerEntryType type) => switch (type) {
      LedgerEntryType.credit => 'Crédit',
      LedgerEntryType.debit => 'Débit',
      LedgerEntryType.lock => 'Verrouillage',
      LedgerEntryType.unlock => 'Déverrouillage',
      LedgerEntryType.fee => 'Frais',
      LedgerEntryType.refund => 'Remboursement',
      LedgerEntryType.unknown => 'Mouvement',
    };

class LedgerEntry {
  const LedgerEntry({
    required this.id,
    required this.type,
    required this.amount,
    required this.currency,
    required this.balanceAfter,
    required this.description,
    this.createdAt,
  });

  factory LedgerEntry.fromJson(Map<String, dynamic> json) => LedgerEntry(
        id: json['id'] as int,
        type: ledgerTypeFrom(json['entry_type'] as String?),
        amount: '${json['amount'] ?? ''}',
        currency: json['currency'] as String? ?? 'USD',
        balanceAfter: '${json['balance_after'] ?? ''}',
        description: json['description'] as String? ?? '',
        createdAt: DateTime.tryParse('${json['created_at'] ?? ''}'),
      );

  final int id;
  final LedgerEntryType type;
  final String amount;
  final String currency;

  /// Solde laissé derrière ce mouvement : c'est ce qui permet de
  /// vérifier la chaîne plutôt que de faire confiance à un total.
  final String balanceAfter;

  final String description;
  final DateTime? createdAt;
}
