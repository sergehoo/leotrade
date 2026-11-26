import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../../../core/format.dart';
import '../../../core/network/api_client.dart';
import '../../../core/theme/app_theme.dart';
import '../../../shared/widgets/leo_fab.dart';
import '../../../shared/widgets/states.dart';
import '../data/market_repository.dart';
import '../domain/models.dart';

/// Unités de temps proposées, alignées sur le sélecteur du web.
const _timeframes = <String, String>{
  '1h': '1 h',
  '4h': '4 h',
  '1d': '1 j',
  '1w': '1 sem',
};

const _classes = <String, String>{
  'ALL': 'Toutes',
  'CRYPTO': 'Crypto',
  'FOREX': 'Forex',
  'INDEX': 'Indices',
  'COMMODITY': 'Matières',
  'STOCK': 'Actions',
};

class MarketScreen extends ConsumerStatefulWidget {
  const MarketScreen({super.key});

  @override
  ConsumerState<MarketScreen> createState() => _MarketScreenState();
}

class _MarketScreenState extends ConsumerState<MarketScreen> {
  final _search = TextEditingController();

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final quotes = ref.watch(marketQuotesProvider);
    final filter = ref.watch(marketFilterProvider);
    final watchlist = ref.watch(watchlistProvider).valueOrNull ?? const <int, int>{};

    return Scaffold(
      appBar: AppBar(title: const Text('Marchés')),
      floatingActionButton: const LeoFab(page: 'marches'),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
            child: TextField(
              controller: _search,
              onSubmitted: (value) => ref
                  .read(marketFilterProvider.notifier)
                  .update((state) => state.copyWith(search: value)),
              decoration: const InputDecoration(
                hintText: 'Rechercher un symbole…',
                prefixIcon: Icon(Icons.search, size: 18),
                isDense: true,
              ),
            ),
          ),
          SizedBox(
            height: 56,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.fromLTRB(16, 6, 16, 6),
              children: [
                for (final entry in _classes.entries) ...[
                  _Chip(
                    label: entry.value,
                    selected: filter.assetClass == entry.key,
                    onTap: () => ref
                        .read(marketFilterProvider.notifier)
                        .update((state) => state.copyWith(assetClass: entry.key)),
                  ),
                  const SizedBox(width: 8),
                ],
              ],
            ),
          ),
          // L'unité de temps était figée à 1 j : la variation affichée
          // était toujours journalière, et le sélecteur du web n'avait
          // pas d'équivalent ici. Elle détermine la variation ET la
          // fraîcheur annoncée par le serveur.
          SizedBox(
            height: 50,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 6),
              children: [
                const Padding(
                  padding: EdgeInsets.only(right: 8),
                  child: Center(
                    child: Text(
                      'Variation sur',
                      style: TextStyle(color: AppColors.muted, fontSize: 11),
                    ),
                  ),
                ),
                for (final code in _timeframes.entries) ...[
                  _Chip(
                    label: code.value,
                    selected: filter.timeframe == code.key,
                    onTap: () => ref
                        .read(marketFilterProvider.notifier)
                        .update((state) => state.copyWith(timeframe: code.key)),
                  ),
                  const SizedBox(width: 8),
                ],
              ],
            ),
          ),
          Expanded(
            child: quotes.when(
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (error, _) => ErrorStateView(
                message: error is ApiError ? error.message : 'Chargement impossible.',
                onRetry: () => ref.invalidate(marketQuotesProvider),
              ),
              data: (page) {
                final rows = page.items;
                if (rows.isEmpty) {
                  return const Padding(
                    padding: EdgeInsets.only(top: 48),
                    child: EmptyStateView(
                      icon: Icons.show_chart,
                      title: 'Aucun instrument',
                      description:
                          'Aucun instrument ne correspond à ces critères. Le '
                          'catalogue est alimenté par les connecteurs de données.',
                    ),
                  );
                }

                final stale = rows.where((row) => row.isStale).length;
                // Une liste coupée sans un mot se lit comme une liste
                // complète : l'instrument absent passe pour inexistant.
                final banners = (stale > 0 ? 1 : 0) + (page.hasMore ? 1 : 0);

                return RefreshIndicator(
                  onRefresh: () async {
                    ref.invalidate(marketQuotesProvider);
                    await ref.read(marketQuotesProvider.future);
                  },
                  child: ListView.builder(
                    padding: const EdgeInsets.fromLTRB(16, 8, 16, 90),
                    itemCount: rows.length + banners,
                    itemBuilder: (_, index) {
                      if (page.hasMore && index == banners - 1) {
                        return Padding(
                          padding: const EdgeInsets.only(bottom: 12),
                          child: NoticeBanner(
                            tone: NoticeTone.info,
                            title: 'Catalogue partiel',
                            message:
                                '${rows.length} instruments affichés sur '
                                '${page.count}. Affine la recherche ou le '
                                'filtre de classe pour atteindre les autres.',
                          ),
                        );
                      }
                      if (stale > 0 && index == 0) {
                        return Padding(
                          padding: const EdgeInsets.only(bottom: 12),
                          child: NoticeBanner(
                            tone: NoticeTone.warning,
                            title: 'Cours périmés',
                            message:
                                '$stale instrument${stale > 1 ? 's' : ''} sur '
                                '${rows.length} affiche${stale > 1 ? 'nt' : ''} un '
                                'cours trop ancien pour décider. La date de '
                                'chaque ligne indique de quand il date.',
                          ),
                        );
                      }
                      final quote = rows[index - banners];
                      return _QuoteTile(
                        quote: quote,
                        watchlistItemId: watchlist[quote.assetId],
                      );
                    },
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

class _Chip extends StatelessWidget {
  const _Chip({required this.label, required this.selected, required this.onTap});

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(8),
      child: Container(
        // 44 pt de hauteur utile : en dessous, la cible est trop petite
        // pour un pouce. Le libellé n'est plus rogné quand le texte
        // système est agrandi.
        constraints: const BoxConstraints(minHeight: 44),
        alignment: Alignment.center,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: BoxDecoration(
          color: selected ? AppColors.primary.withValues(alpha: 0.12) : Colors.transparent,
          border: Border.all(
            color: selected
                ? AppColors.primary.withValues(alpha: 0.40)
                : AppColors.border,
          ),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Text(
          label,
          style: TextStyle(
            color: selected ? AppColors.foreground : AppColors.muted,
            fontSize: 12,
          ),
        ),
      ),
    );
  }
}

class _QuoteTile extends ConsumerStatefulWidget {
  const _QuoteTile({required this.quote, required this.watchlistItemId});

  final Quote quote;
  final int? watchlistItemId;

  @override
  ConsumerState<_QuoteTile> createState() => _QuoteTileState();
}

class _QuoteTileState extends ConsumerState<_QuoteTile> {
  bool _busy = false;

  Future<void> _toggleFollow() async {
    setState(() => _busy = true);
    final repository = ref.read(marketRepositoryProvider);
    final messenger = ScaffoldMessenger.of(context);
    try {
      final itemId = widget.watchlistItemId;
      if (itemId != null) {
        await repository.unfollow(itemId);
      } else {
        await repository.follow(widget.quote.assetId);
      }
      ref.invalidate(watchlistProvider);
    } on ApiError catch (error) {
      messenger.showSnackBar(
        SnackBar(content: Text(error.message), backgroundColor: AppColors.loss),
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final quote = widget.quote;
    final followed = widget.watchlistItemId != null;

    // La couleur de la fraîcheur n'est pas décorative : elle dit si on
    // peut décider sur ce chiffre.
    final freshnessColor = switch (quote.freshness) {
      Freshness.live => AppColors.gain,
      Freshness.delayed => AppColors.warning,
      Freshness.stale => AppColors.loss,
      Freshness.noData => AppColors.muted,
    };

    final sign = signOf(quote.changePercent);
    final changeColor = switch (sign) {
      MoveSign.gain => AppColors.gain,
      MoveSign.loss => AppColors.loss,
      MoveSign.flat => AppColors.muted,
    };

    return InkWell(
      onTap: () => context.push(
        '/marches/${quote.assetId}?symbole=${Uri.encodeComponent(quote.symbol)}',
      ),
      borderRadius: BorderRadius.circular(12),
      child: Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.surface,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(quote.symbol,
                        style: const TextStyle(fontWeight: FontWeight.w600)),
                    if (quote.name.isNotEmpty && quote.name != quote.symbol)
                      Text(quote.name,
                          style: const TextStyle(color: AppColors.muted, fontSize: 11)),
                  ],
                ),
              ),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text(
                    quote.hasPrice ? quote.price! : 'Aucune donnée',
                    style: TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w600,
                      // Un cours périmé est grisé : il reste lisible mais ne
                      // doit pas se présenter comme un cours courant.
                      color: quote.hasPrice && !quote.isStale
                          ? AppColors.foreground
                          : AppColors.muted,
                    ),
                  ),
                  if (quote.changePercent != null)
                    Text(
                      formatPercent(quote.changePercent),
                      style: TextStyle(color: changeColor, fontSize: 12),
                    ),
                ],
              ),
              IconButton(
                onPressed: _busy ? null : _toggleFollow,
                tooltip: followed ? 'Ne plus suivre' : 'Suivre',
                icon: Icon(
                  followed ? Icons.star : Icons.star_border,
                  size: 20,
                  color: followed ? AppColors.warning : AppColors.muted,
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
                decoration: BoxDecoration(
                  color: freshnessColor.withValues(alpha: 0.14),
                  border: Border.all(color: freshnessColor.withValues(alpha: 0.35)),
                  borderRadius: BorderRadius.circular(5),
                ),
                child: Text(
                  quote.freshnessLabel,
                  style: TextStyle(
                    color: freshnessColor,
                    fontSize: 10,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  quote.asOf == null
                      ? quote.source
                      : '${DateFormat('dd/MM/yy HH:mm', 'fr_FR').format(quote.asOf!.toLocal())}'
                        ' · ${quote.ageLabel} · ${quote.source}',
                  style: const TextStyle(color: AppColors.muted, fontSize: 10),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
        ],
      ),
      ),
    );
  }
}
