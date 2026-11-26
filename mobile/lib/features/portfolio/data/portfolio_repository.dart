import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../../auth/presentation/auth_controller.dart';
import '../domain/models.dart';

class PortfolioRepository {
  const PortfolioRepository(this._client);

  final ApiClient _client;

  Future<List<Portfolio>> list() async {
    final body = await _client.get<Map<String, dynamic>>('/portfolios/');
    final results = body['results'];
    if (results is! List) return const [];
    return results
        .whereType<Map<String, dynamic>>()
        .map(Portfolio.fromJson)
        .toList(growable: false);
  }

  Future<PortfolioSummary> summary(int id) async {
    return PortfolioSummary.fromJson(
      await _client.get<Map<String, dynamic>>('/portfolios/$id/summary/'),
    );
  }

  Future<List<Position>> openPositions(int portfolioId) async {
    final body = await _client.get<Map<String, dynamic>>(
      '/positions/',
      query: {'portfolio': portfolioId, 'status': 'OPEN'},
    );
    final results = body['results'];
    if (results is! List) return const [];
    return results
        .whereType<Map<String, dynamic>>()
        .map(Position.fromJson)
        .toList(growable: false);
  }

  /// Provisionne place locale + portefeuille + capital, en un appel.
  Future<Portfolio> provisionPaper() async {
    return Portfolio.fromJson(
      await _client.post<Map<String, dynamic>>(
        '/portfolios/provision-paper/',
        data: const <String, dynamic>{},
      ),
    );
  }

  /// Courbe de valorisation, verdict de traçabilité compris.
  ///
  /// Le mobile ne l'appelait pas : le widget `Sparkline` existait,
  /// documenté et testé, sans qu'aucun écran ne l'utilise. La courbe du
  /// lot « graphiques » n'avait été livrée que côté web.
  Future<EquityCurve> equityCurve(int id, {int limit = 365}) async {
    return EquityCurve.fromJson(
      await _client.get<Map<String, dynamic>>(
        '/portfolios/$id/equity-curve/',
        query: {'limit': limit},
      ),
    );
  }

  Future<void> refresh(int id) =>
      _client.post<Map<String, dynamic>>('/portfolios/$id/refresh/');

  /// Désigne le portefeuille par défaut.
  ///
  /// Ce choix détermine le mode de trading annoncé par l'application :
  /// `resolve_configured_trading_mode` lit le broker du portefeuille par
  /// défaut avant toute autre source.
  Future<void> setDefault(int id) =>
      _client.post<Map<String, dynamic>>('/portfolios/$id/set-default/');
}

final portfolioRepositoryProvider = Provider<PortfolioRepository>(
  (ref) => PortfolioRepository(ref.watch(apiClientProvider)),
);

final portfoliosProvider =
    FutureProvider.autoDispose<List<Portfolio>>((ref) async {
  final authenticated = ref.watch(
    authControllerProvider.select((state) => state.isAuthenticated),
  );
  if (!authenticated) throw const ApiError('Session fermée.');
  return ref.watch(portfolioRepositoryProvider).list();
});

final portfolioSummaryProvider =
    FutureProvider.autoDispose.family<PortfolioSummary, int>((ref, id) async {
  return ref.watch(portfolioRepositoryProvider).summary(id);
});

final equityCurveProvider =
    FutureProvider.autoDispose.family<EquityCurve, int>((ref, id) async {
  return ref.watch(portfolioRepositoryProvider).equityCurve(id);
});

final openPositionsProvider =
    FutureProvider.autoDispose.family<List<Position>, int>((ref, id) async {
  return ref.watch(portfolioRepositoryProvider).openPositions(id);
});
