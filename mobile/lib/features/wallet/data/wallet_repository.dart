import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../../../core/network/page.dart';
import '../../auth/presentation/auth_controller.dart';
import '../domain/models.dart';

class WalletRepository {
  const WalletRepository(this._client);

  final ApiClient _client;

  Future<WalletSummary> summary() async => WalletSummary.fromJson(
        await _client.get<Map<String, dynamic>>('/wallet/summary/'),
      );

  /// Grand livre. La page par défaut vaut 25 : l'historique s'arrêtait
  /// là, sans que rien n'indique qu'il continuait.
  Future<Page<LedgerEntry>> ledger({int pageSize = 50}) async {
    return Page.fromJson(
      await _client.get<Map<String, dynamic>>(
        '/wallet/ledger/',
        query: {'page_size': pageSize},
      ),
      LedgerEntry.fromJson,
    );
  }

  /// Demandes de retrait et leur suivi.
  Future<Page<WithdrawalRequest>> withdrawals() async {
    return Page.fromJson(
      await _client.get<Map<String, dynamic>>(
        '/wallet/withdrawals/',
        query: const {'page_size': kMaxPageSize},
      ),
      WithdrawalRequest.fromJson,
    );
  }

  /// Demande de retrait : verrouille des fonds, n'en déplace aucun.
  /// Une revue humaine décide ensuite.
  Future<void> requestWithdrawal({
    required String amount,
    String? destinationMasked,
  }) =>
      _client.post<Map<String, dynamic>>(
        '/wallet/withdrawals/',
        data: {
          'amount': amount,
          'destination_type': 'BANK',
          if (destinationMasked != null && destinationMasked.isNotEmpty)
            'destination_masked': destinationMasked,
        },
      );
}

final walletRepositoryProvider = Provider<WalletRepository>(
  (ref) => WalletRepository(ref.watch(apiClientProvider)),
);

final walletSummaryProvider =
    FutureProvider.autoDispose<WalletSummary>((ref) async {
  final authenticated = ref.watch(
    authControllerProvider.select((state) => state.isAuthenticated),
  );
  if (!authenticated) throw const ApiError('Session fermée.');
  return ref.watch(walletRepositoryProvider).summary();
});

/// Nombre de mouvements demandés. Un bouton « Charger plus » l'augmente.
final ledgerPageSizeProvider = StateProvider.autoDispose<int>((_) => 50);

final walletLedgerProvider =
    FutureProvider.autoDispose<Page<LedgerEntry>>((ref) async {
  final authenticated = ref.watch(
    authControllerProvider.select((state) => state.isAuthenticated),
  );
  if (!authenticated) {
    return const Page(items: [], count: 0, hasMore: false);
  }
  return ref
      .watch(walletRepositoryProvider)
      .ledger(pageSize: ref.watch(ledgerPageSizeProvider));
});

final walletWithdrawalsProvider =
    FutureProvider.autoDispose<Page<WithdrawalRequest>>((ref) async {
  final authenticated = ref.watch(
    authControllerProvider.select((state) => state.isAuthenticated),
  );
  if (!authenticated) {
    return const Page(items: [], count: 0, hasMore: false);
  }
  return ref.watch(walletRepositoryProvider).withdrawals();
});
