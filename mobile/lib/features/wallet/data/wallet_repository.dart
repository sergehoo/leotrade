import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../../auth/presentation/auth_controller.dart';
import '../domain/models.dart';

class WalletRepository {
  const WalletRepository(this._client);

  final ApiClient _client;

  Future<WalletSummary> summary() async => WalletSummary.fromJson(
        await _client.get<Map<String, dynamic>>('/wallet/summary/'),
      );

  Future<List<LedgerEntry>> ledger() async {
    final body = await _client.get<Map<String, dynamic>>('/wallet/ledger/');
    final results = body['results'];
    if (results is! List) return const [];
    return results
        .whereType<Map<String, dynamic>>()
        .map(LedgerEntry.fromJson)
        .toList(growable: false);
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

final walletLedgerProvider =
    FutureProvider.autoDispose<List<LedgerEntry>>((ref) async {
  final authenticated = ref.watch(
    authControllerProvider.select((state) => state.isAuthenticated),
  );
  if (!authenticated) return const [];
  return ref.watch(walletRepositoryProvider).ledger();
});
