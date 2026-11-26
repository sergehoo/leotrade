import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../../auth/presentation/auth_controller.dart';
import '../domain/models.dart';

class MarketRepository {
  const MarketRepository(this._client);

  final ApiClient _client;

  Future<List<Quote>> quotes({String? search, String? assetClass, String timeframe = '1d'}) async {
    final body = await _client.get<Map<String, dynamic>>(
      '/market/assets/quotes/',
      query: {
        'timeframe': timeframe,
        if (search != null && search.isNotEmpty) 'search': search,
        if (assetClass != null && assetClass != 'ALL') 'asset_class': assetClass,
      },
    );
    final results = body['results'];
    if (results is! List) return const [];
    return results
        .whereType<Map<String, dynamic>>()
        .map(Quote.fromJson)
        .toList(growable: false);
  }

  Future<List<WatchlistEntry>> watchlist() async {
    final body = await _client.get<Map<String, dynamic>>('/market/watchlist/');
    final results = body['results'];
    if (results is! List) return const [];
    return results
        .whereType<Map<String, dynamic>>()
        .map(WatchlistEntry.fromJson)
        .toList(growable: false);
  }

  Future<void> follow(int assetId) => _client.post<Map<String, dynamic>>(
        '/market/watchlist/',
        data: {'asset': assetId},
      );

  Future<void> unfollow(int itemId) => _client.delete('/market/watchlist/$itemId/');
}

final marketRepositoryProvider = Provider<MarketRepository>(
  (ref) => MarketRepository(ref.watch(apiClientProvider)),
);

/// Critères de consultation du marché.
class MarketFilter {
  const MarketFilter({this.search = '', this.assetClass = 'ALL', this.timeframe = '1d'});

  final String search;
  final String assetClass;
  final String timeframe;

  MarketFilter copyWith({String? search, String? assetClass, String? timeframe}) =>
      MarketFilter(
        search: search ?? this.search,
        assetClass: assetClass ?? this.assetClass,
        timeframe: timeframe ?? this.timeframe,
      );

  @override
  bool operator ==(Object other) =>
      other is MarketFilter &&
      other.search == search &&
      other.assetClass == assetClass &&
      other.timeframe == timeframe;

  @override
  int get hashCode => Object.hash(search, assetClass, timeframe);
}

final marketFilterProvider = StateProvider<MarketFilter>((_) => const MarketFilter());

final marketQuotesProvider =
    FutureProvider.autoDispose<List<Quote>>((ref) async {
  final authenticated = ref.watch(
    authControllerProvider.select((state) => state.isAuthenticated),
  );
  if (!authenticated) throw const ApiError('Session fermée.');

  final filter = ref.watch(marketFilterProvider);
  return ref.watch(marketRepositoryProvider).quotes(
        search: filter.search,
        assetClass: filter.assetClass,
        timeframe: filter.timeframe,
      );
});

final watchlistProvider =
    FutureProvider.autoDispose<Map<int, int>>((ref) async {
  final authenticated = ref.watch(
    authControllerProvider.select((state) => state.isAuthenticated),
  );
  if (!authenticated) return const {};
  final entries = await ref.watch(marketRepositoryProvider).watchlist();
  return {for (final entry in entries) entry.assetId: entry.id};
});
