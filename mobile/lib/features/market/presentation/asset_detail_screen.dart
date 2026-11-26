import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../../core/format.dart';
import '../../../core/network/api_client.dart';
import '../../../core/theme/app_theme.dart';
import '../../../shared/charts/candle_chart.dart';
import '../../../shared/widgets/leo_fab.dart';
import '../../../shared/widgets/states.dart';
import '../data/market_repository.dart';
import '../domain/models.dart';

const _timeframes = ['1h', '4h', '1d', '1w'];

class AssetDetailScreen extends ConsumerStatefulWidget {
  const AssetDetailScreen({super.key, required this.assetId, this.symbol});

  final int assetId;
  final String? symbol;

  @override
  ConsumerState<AssetDetailScreen> createState() => _AssetDetailScreenState();
}

class _AssetDetailScreenState extends ConsumerState<AssetDetailScreen> {
  String _timeframe = '1d';

  @override
  Widget build(BuildContext context) {
    final request = CandleRequest(widget.assetId, _timeframe);
    final quote = ref.watch(assetQuoteProvider(request));
    final history = ref.watch(candleHistoryProvider(request));

    return Scaffold(
      appBar: AppBar(title: Text(widget.symbol ?? 'Instrument')),
      floatingActionButton: const LeoFab(page: 'marches'),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 90),
        children: [
          // Le cours, avant le graphique : un historique sans prix courant
          // oblige à deviner où en est l'instrument.
          quote.when(
            loading: () => const SizedBox(
              height: 72,
              child: Center(child: CircularProgressIndicator()),
            ),
            // Une cotation indisponible ne doit pas emporter le graphique :
            // l'historique, lui, est peut-être lisible.
            error: (error, _) => NoticeBanner(
              tone: NoticeTone.warning,
              title: 'Cours indisponible',
              message: error is ApiError
                  ? error.message
                  : 'La cotation n\'a pas pu être chargée.',
            ),
            data: (data) => _QuoteHeader(quote: data),
          ),
          const SizedBox(height: 16),
          SizedBox(
            height: 38,
            child: ListView(
              scrollDirection: Axis.horizontal,
              children: [
                for (final code in _timeframes) ...[
                  _TimeframeChip(
                    label: code,
                    selected: code == _timeframe,
                    onTap: () => setState(() => _timeframe = code),
                  ),
                  const SizedBox(width: 8),
                ],
              ],
            ),
          ),
          const SizedBox(height: 16),
          history.when(
            loading: () => const Center(
              child: Padding(
                padding: EdgeInsets.all(40),
                child: CircularProgressIndicator(),
              ),
            ),
            error: (error, _) => ErrorStateView(
              message: error is ApiError ? error.message : 'Chargement impossible.',
              onRetry: () => ref.invalidate(candleHistoryProvider(request)),
            ),
            data: (data) => _HistoryBody(history: data),
          ),
        ],
      ),
    );
  }
}

class _TimeframeChip extends StatelessWidget {
  const _TimeframeChip({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(8),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
        decoration: BoxDecoration(
          color: selected
              ? AppColors.primary.withValues(alpha: 0.12)
              : Colors.transparent,
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

class _HistoryBody extends StatelessWidget {
  const _HistoryBody({required this.history});

  final CandleHistory history;

  @override
  Widget build(BuildContext context) {
    if (!history.hasData) {
      return const Padding(
        padding: EdgeInsets.only(top: 40),
        child: EmptyStateView(
          icon: Icons.show_chart,
          title: 'Aucun historique',
          description:
              'Aucune bougie n\'est enregistrée pour cet instrument sur cette '
              'unité de temps.',
        ),
      );
    }

    final points = history.candles
        .map((row) => CandlePoint.tryParse(
              open: row['open'] as String?,
              high: row['high'] as String?,
              low: row['low'] as String?,
              close: row['close'] as String?,
            ))
        .whereType<CandlePoint>()
        .toList(growable: false);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (history.isStale) ...[
          NoticeBanner(
            tone: NoticeTone.warning,
            title: 'Ce graphique ne montre pas le marché actuel',
            message: history.asOf == null
                ? 'La série est trop ancienne pour refléter le marché.'
                : 'La dernière bougie date du '
                  '${DateFormat('dd/MM/yy HH:mm', 'fr_FR').format(history.asOf!.toLocal())}. '
                  'Ce qui s\'est passé depuis n\'apparaît nulle part sur ce '
                  'graphique.',
          ),
          const SizedBox(height: 14),
        ],
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: AppColors.surface,
            border: Border.all(color: AppColors.border),
            borderRadius: BorderRadius.circular(12),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              CandleChart(
                candles: points,
                semanticsSuffix: 'Fraîcheur : ${history.freshnessLabel}.',
              ),
              const SizedBox(height: 8),
              Text(
                '${points.length} bougie${points.length > 1 ? 's' : ''} · '
                '${history.source}'
                '${history.asOf != null ? ' · dernière le ${DateFormat('dd/MM/yy HH:mm', 'fr_FR').format(history.asOf!.toLocal())}' : ''}',
                style: const TextStyle(color: AppColors.muted, fontSize: 10),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

/// Cours courant, variation et fraîcheur.
///
/// La fraîcheur n'est jamais calculée ici : elle vient de
/// `market/services_quotes.py`, pour que le web et le mobile ne puissent
/// pas qualifier différemment la même donnée.
class _QuoteHeader extends StatelessWidget {
  const _QuoteHeader({required this.quote});

  final Quote quote;

  @override
  Widget build(BuildContext context) {
    final tone = switch (quote.freshness) {
      Freshness.live => AppColors.gain,
      Freshness.delayed => AppColors.warning,
      Freshness.stale => AppColors.loss,
      Freshness.noData => AppColors.muted,
    };
    final move = signOf(quote.changePercent);
    final moveColor = switch (move) {
      MoveSign.gain => AppColors.gain,
      MoveSign.loss => AppColors.loss,
      MoveSign.flat => AppColors.flat,
    };

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    quote.price ?? 'Aucune donnée',
                    style: const TextStyle(
                      fontSize: 26,
                      fontWeight: FontWeight.w600,
                      fontFeatures: [FontFeature.tabularFigures()],
                    ),
                  ),
                  if (quote.changePercent != null)
                    Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        // Le signe accompagne la couleur : lue seule, elle
                        // ne dit rien à qui ne distingue pas le rouge du
                        // vert.
                        Icon(
                          switch (move) {
                            MoveSign.gain => Icons.arrow_upward,
                            MoveSign.loss => Icons.arrow_downward,
                            MoveSign.flat => Icons.remove,
                          },
                          size: 13,
                          color: moveColor,
                        ),
                        const SizedBox(width: 3),
                        Text(
                          formatPercent(quote.changePercent),
                          style: TextStyle(
                            color: moveColor,
                            fontSize: 13,
                            fontFeatures: const [FontFeature.tabularFigures()],
                          ),
                        ),
                      ],
                    ),
                  const SizedBox(height: 4),
                  Text(
                    [quote.name, quote.assetClass, quote.source]
                        .where((part) => part.isNotEmpty)
                        .join(' · '),
                    style: const TextStyle(color: AppColors.muted, fontSize: 11),
                  ),
                ],
              ),
            ),
            const SizedBox(width: 10),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              decoration: BoxDecoration(
                color: tone.withValues(alpha: 0.14),
                border: Border.all(color: tone.withValues(alpha: 0.35)),
                borderRadius: BorderRadius.circular(999),
              ),
              child: Text(
                quote.freshnessLabel,
                style: TextStyle(
                  color: tone,
                  fontSize: 11,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
          ],
        ),
        if (quote.isStale) ...[
          const SizedBox(height: 10),
          NoticeBanner(
            tone: NoticeTone.danger,
            title: 'Cotation périmée',
            message: 'Dernière donnée du '
                '${quote.asOf != null ? DateFormat('dd/MM/yyyy à HH:mm', 'fr_FR').format(quote.asOf!.toLocal()) : 'date inconnue'} '
                '(${quote.ageLabel}). Ce qui s\'est passé depuis n\'est pas '
                'dans ce chiffre.',
          ),
        ],
      ],
    );
  }
}
