import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../../auth/presentation/auth_controller.dart';
import '../domain/models.dart';

class RiskRepository {
  const RiskRepository(this._client);

  final ApiClient _client;

  Future<RiskSummary> summary(int portfolioId) async {
    return RiskSummary.fromJson(
      await _client.get<Map<String, dynamic>>('/risk-utils/summary/$portfolioId/'),
    );
  }

  Future<void> refreshStates(int portfolioId) =>
      _client.post<Map<String, dynamic>>(
        '/risk-utils/refresh-states/',
        data: {'portfolio_id': portfolioId},
      );

  Future<void> setPreservationFlag(int profileId, String field, bool value) =>
      _client.patch<Map<String, dynamic>>(
        '/risk-profiles/$profileId/',
        data: {field: value},
      );

  /// Lever un arrêt d'urgence rouvre l'exécution : l'appel ne doit jamais
  /// partir sans confirmation explicite côté interface.
  Future<int> resolveKillSwitch(int portfolioId) async {
    final body = await _client.post<Map<String, dynamic>>(
      '/kill-switch-events/resolve-for-portfolio/',
      data: {'portfolio_id': portfolioId},
    );
    return body['resolved_count'] as int? ?? 0;
  }
}

final riskRepositoryProvider = Provider<RiskRepository>(
  (ref) => RiskRepository(ref.watch(apiClientProvider)),
);

final riskSummaryProvider =
    FutureProvider.autoDispose.family<RiskSummary, int>((ref, portfolioId) async {
  final authenticated = ref.watch(
    authControllerProvider.select((state) => state.isAuthenticated),
  );
  if (!authenticated) throw const ApiError('Session fermée.');
  return ref.watch(riskRepositoryProvider).summary(portfolioId);
});
