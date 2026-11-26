import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../../../core/network/page.dart';
import '../../auth/presentation/auth_controller.dart';
import '../domain/models.dart';

class MarketRepository {
  const MarketRepository(this._client);

  final ApiClient _client;

  Future<Page<Quote>> quotes({
    String? search,
    String? assetClass,
    String timeframe = '1d',
  }) async {
    return Page.fromJson(
      await _client.get<Map<String, dynamic>>(
        '/market/assets/quotes/',
        query: {
          'timeframe': timeframe,
          // La page par défaut vaut 25 : le catalogue était coupé là,
          // sans un mot. Le plafond serveur est 200 ; au-delà, l'écran le
          // dit au lieu de laisser croire que la liste est complète.
          'page_size': kMaxPageSize,
          if (search != null && search.isNotEmpty) 'search': search,
          if (assetClass != null && assetClass != 'ALL') 'asset_class': assetClass,
        },
      ),
      Quote.fromJson,
    );
  }

    /// [limit] vaut 300 comme côté web : deux fenêtres différentes
  /// cadrent deux amplitudes différentes pour le même instrument au même
  /// instant, et le même mouvement s'y dessine jusqu'à trois fois plus
  /// haut d'un support à l'autre.
  Future<CandleHistory> candles(int assetId, {String timeframe = '1d', int limit = 300}) async {
    return CandleHistory.fromJson(
      await _client.get<Map<String, dynamic>>(
        '/market/assets/$assetId/candles/',
        query: {'timeframe': timeframe, 'limit': limit},
      ),
    );
  }

  /// Cotation d'un instrument. Le détail d'un actif affichait son
  /// historique sans jamais dire à combien il cote — ni depuis quand.
  Future<Quote> quote(int assetId, {String timeframe = '1d'}) async {
    return Quote.fromJson(
      await _client.get<Map<String, dynamic>>(
        '/market/assets/$assetId/quote/',
        query: {'timeframe': timeframe},
      ),
    );
  }

  Future<Page<WatchlistEntry>> watchlist() async {
    return Page.fromJson(
      await _client.get<Map<String, dynamic>>(
        '/market/watchlist/',
        query: const {'page_size': kMaxPageSize},
      ),
      WatchlistEntry.fromJson,
    );
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
    FutureProvider.autoDispose<Page<Quote>>((ref) async {
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

/// Instruments suivis, indexés par identifiant d'actif.
final watchlistProvider =
    FutureProvider.autoDispose<Map<int, int>>((ref) async {
  final authenticated = ref.watch(
    authControllerProvider.select((state) => state.isAuthenticated),
  );
  if (!authenticated) return const {};
  final page = await ref.watch(marketRepositoryProvider).watchlist();
  return {for (final entry in page.items) entry.assetId: entry.id};
});


/// Requête d'historique : instrument + unité de temps.
class CandleRequest {
  const CandleRequest(this.assetId, this.timeframe);

  final int assetId;
  final String timeframe;

  @override
  bool operator ==(Object other) =>
      other is CandleRequest &&
      other.assetId == assetId &&
      other.timeframe == timeframe;

  @override
  int get hashCode => Object.hash(assetId, timeframe);
}

final assetQuoteProvider =
    FutureProvider.autoDispose.family<Quote, CandleRequest>(
  (ref, request) async => ref
      .watch(marketRepositoryProvider)
      .quote(request.assetId, timeframe: request.timeframe),
);

final candleHistoryProvider =
    FutureProvider.autoDispose.family<CandleHistory, CandleRequest>(
  (ref, request) async => ref
      .watch(marketRepositoryProvider)
      .candles(request.assetId, timeframe: request.timeframe),
);
