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

/// Demande de retrait, telle que le serveur la suit.
///
/// Le mobile jetait la réponse 201 et n'affichait jamais la suite : une
/// demande partie disparaissait de l'écran, et son refus comme son
/// paiement restaient invisibles. Les libellés sont ceux du web
/// (`WITHDRAWAL_LABELS`), pour que le même statut ne se dise pas de deux
/// façons.
enum WithdrawalStatus {
  pending,
  underReview,
  approved,
  rejected,
  paid,
  failed,
  cancelled,
  unknown,
}

WithdrawalStatus withdrawalStatusFrom(String? raw) => switch (raw) {
      'PENDING' => WithdrawalStatus.pending,
      'UNDER_REVIEW' => WithdrawalStatus.underReview,
      'APPROVED' => WithdrawalStatus.approved,
      'REJECTED' => WithdrawalStatus.rejected,
      'PAID' => WithdrawalStatus.paid,
      'FAILED' => WithdrawalStatus.failed,
      'CANCELLED' => WithdrawalStatus.cancelled,
      _ => WithdrawalStatus.unknown,
    };

String withdrawalStatusLabel(WithdrawalStatus status, String raw) =>
    switch (status) {
      WithdrawalStatus.pending => 'En attente de revue',
      WithdrawalStatus.underReview => 'En cours d\'examen',
      WithdrawalStatus.approved => 'Approuvée',
      WithdrawalStatus.rejected => 'Refusée',
      WithdrawalStatus.paid => 'Payée',
      WithdrawalStatus.failed => 'Échouée',
      WithdrawalStatus.cancelled => 'Annulée',
      // Un statut inconnu est montré tel quel plutôt que traduit à tort.
      WithdrawalStatus.unknown => raw,
    };

class WithdrawalRequest {
  const WithdrawalRequest({
    required this.id,
    required this.amount,
    required this.feeAmount,
    required this.currency,
    required this.status,
    required this.statusLabel,
    required this.destinationMasked,
    required this.failureReason,
    required this.createdAt,
    required this.reviewedAt,
  });

  factory WithdrawalRequest.fromJson(Map<String, dynamic> json) {
    final raw = json['status'] as String? ?? '';
    final status = withdrawalStatusFrom(raw);
    return WithdrawalRequest(
      id: json['id'] as int,
      amount: '${json['amount'] ?? ''}',
      feeAmount: '${json['fee_amount'] ?? ''}',
      currency: json['currency'] as String? ?? '',
      status: status,
      statusLabel: withdrawalStatusLabel(status, raw),
      destinationMasked: json['destination_masked'] as String?,
      failureReason: json['failure_reason'] as String? ?? '',
      createdAt: DateTime.tryParse('${json['created_at'] ?? ''}'),
      reviewedAt: DateTime.tryParse('${json['reviewed_at'] ?? ''}'),
    );
  }

  final int id;
  final String amount;
  final String feeAmount;
  final String currency;
  final WithdrawalStatus status;
  final String statusLabel;
  final String? destinationMasked;
  final String failureReason;
  final DateTime? createdAt;
  final DateTime? reviewedAt;

  /// Les fonds sont encore verrouillés : rien n'est tranché.
  bool get isOpen =>
      status == WithdrawalStatus.pending ||
      status == WithdrawalStatus.underReview ||
      status == WithdrawalStatus.approved;

  bool get isRefused =>
      status == WithdrawalStatus.rejected || status == WithdrawalStatus.failed;
}
