import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/format.dart';
import '../../../core/network/api_client.dart';
import '../../../core/theme/app_theme.dart';
import '../../../shared/widgets/leo_fab.dart';
import '../../../shared/widgets/states.dart';
import '../data/portfolio_repository.dart';
import '../domain/models.dart';

class PortfolioScreen extends ConsumerStatefulWidget {
  const PortfolioScreen({super.key});

  @override
  ConsumerState<PortfolioScreen> createState() => _PortfolioScreenState();
}

class _PortfolioScreenState extends ConsumerState<PortfolioScreen> {
  int? _selectedId;
  bool _provisioning = false;

  Future<void> _refreshAll() async {
    ref.invalidate(portfoliosProvider);
    ref.invalidate(portfolioSummaryProvider);
    ref.invalidate(openPositionsProvider);
    await ref.read(portfoliosProvider.future);
  }

  Future<void> _provision() async {
    setState(() => _provisioning = true);
    try {
      final portfolio = await ref.read(portfolioRepositoryProvider).provisionPaper();
      await _refreshAll();
      if (!mounted) return;
      setState(() => _selectedId = portfolio.id);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('« ${portfolio.name} » créé avec son capital de départ.')),
      );
    } on ApiError catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(error.message), backgroundColor: AppColors.loss),
      );
    } finally {
      if (mounted) setState(() => _provisioning = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final portfolios = ref.watch(portfoliosProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Portefeuille')),
      floatingActionButton: const LeoFab(page: 'portefeuille'),
      body: RefreshIndicator(
        onRefresh: _refreshAll,
        child: portfolios.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (error, _) => ListView(
            children: [
              const SizedBox(height: 80),
              ErrorStateView(
                message: error is ApiError
                    ? error.message
                    : 'Une erreur inattendue est survenue.',
                onRetry: _refreshAll,
              ),
            ],
          ),
          data: (list) {
            if (list.isEmpty) {
              return ListView(
                children: [
                  const SizedBox(height: 60),
                  EmptyStateView(
                    icon: Icons.work_outline,
                    title: 'Aucun portefeuille',
                    description:
                        'Un portefeuille de simulation te permet d\'utiliser '
                        'toute la plateforme sans ouvrir de compte chez un '
                        'courtier. Aucun ordre n\'atteindra un marché réel.',
                    action: FilledButton.icon(
                      onPressed: _provisioning ? null : _provision,
                      icon: _provisioning
                          ? const SizedBox(
                              height: 16,
                              width: 16,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.add),
                      label: const Text('Créer un portefeuille de simulation'),
                    ),
                  ),
                ],
              );
            }

            final active = list.firstWhere(
              (p) => p.id == _selectedId,
              orElse: () => list.firstWhere(
                (p) => p.isDefault,
                orElse: () => list.first,
              ),
            );

            return ListView(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 32),
              children: [
                if (list.length > 1) ...[
                  _PortfolioSwitcher(
                    portfolios: list,
                    activeId: active.id,
                    onSelect: (id) => setState(() => _selectedId = id),
                  ),
                  const SizedBox(height: 16),
                ],
                if (!active.isSimulated) ...[
                  const NoticeBanner(
                    tone: NoticeTone.warning,
                    title: 'Portefeuille réel',
                    message:
                        'Les ordres passés depuis ce portefeuille atteignent le '
                        'marché et engagent de l\'argent réel.',
                  ),
                  const SizedBox(height: 16),
                ],
                _SummarySection(portfolio: active),
                const SizedBox(height: 20),
                _PositionsSection(portfolio: active),
                const SizedBox(height: 20),
                OutlinedButton.icon(
                  onPressed: _provisioning ? null : _provision,
                  icon: const Icon(Icons.add),
                  label: const Text('Nouveau portefeuille de simulation'),
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}

class _PortfolioSwitcher extends StatelessWidget {
  const _PortfolioSwitcher({
    required this.portfolios,
    required this.activeId,
    required this.onSelect,
  });

  final List<Portfolio> portfolios;
  final int activeId;
  final ValueChanged<int> onSelect;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 38,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: portfolios.length,
        separatorBuilder: (_, __) => const SizedBox(width: 8),
        itemBuilder: (_, index) {
          final portfolio = portfolios[index];
          final selected = portfolio.id == activeId;
          return InkWell(
            onTap: () => onSelect(portfolio.id),
            borderRadius: BorderRadius.circular(8),
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
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
              child: Row(
                children: [
                  Text(
                    portfolio.name,
                    style: TextStyle(
                      color: selected ? AppColors.foreground : AppColors.muted,
                      fontSize: 13,
                    ),
                  ),
                  const SizedBox(width: 6),
                  // Le mode décide si un ordre engage de l'argent réel : il
                  // doit être lisible partout où un portefeuille est nommé.
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                    decoration: BoxDecoration(
                      color: (portfolio.isSimulated ? AppColors.muted : AppColors.loss)
                          .withValues(alpha: 0.15),
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: Text(
                      portfolio.isSimulated ? 'Simu' : 'Réel',
                      style: TextStyle(
                        color: portfolio.isSimulated ? AppColors.muted : AppColors.loss,
                        fontSize: 10,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          );
        },
      ),
    );
  }
}

class _SummarySection extends ConsumerWidget {
  const _SummarySection({required this.portfolio});

  final Portfolio portfolio;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final summary = ref.watch(portfolioSummaryProvider(portfolio.id));

    return summary.when(
      loading: () => const Center(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: CircularProgressIndicator(),
        ),
      ),
      error: (error, _) => ErrorStateView(
        message: error is ApiError ? error.message : 'Synthèse indisponible.',
        onRetry: () => ref.invalidate(portfolioSummaryProvider(portfolio.id)),
      ),
      data: (data) {
        final currency = data.baseCurrency;
        return Column(
          children: [
            Row(
              children: [
                Expanded(
                  child: _MetricCard(
                    label: 'Valorisation',
                    value: formatMoney(data.equity, currency),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: _MetricCard(
                    label: 'Résultat total',
                    value: formatMoney(data.totalPnl, currency),
                    hint: formatPercent(data.totalPnlPercent),
                    sign: signOf(data.totalPnl),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Row(
              children: [
                Expanded(
                  child: _MetricCard(
                    label: 'Latent',
                    value: formatMoney(data.unrealizedPnl, currency),
                    sign: signOf(data.unrealizedPnl),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: _MetricCard(
                    label: 'Réalisé',
                    value: formatMoney(data.realizedPnl, currency),
                    sign: signOf(data.realizedPnl),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Row(
              children: [
                Expanded(
                  child: _MetricCard(
                    label: 'Liquidités',
                    value: formatMoney(data.availableCash, currency),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: _MetricCard(
                    label: 'Exposition',
                    value: formatMoney(data.exposureValue, currency),
                    hint: formatPercent(data.exposurePercent),
                  ),
                ),
              ],
            ),
          ],
        );
      },
    );
  }
}

class _MetricCard extends StatelessWidget {
  const _MetricCard({
    required this.label,
    required this.value,
    this.hint,
    this.sign = MoveSign.flat,
  });

  final String label;
  final String value;
  final String? hint;
  final MoveSign sign;

  @override
  Widget build(BuildContext context) {
    // Vert et rouge réservés au P&L et au risque : jamais décoratifs.
    final color = switch (sign) {
      MoveSign.gain => AppColors.gain,
      MoveSign.loss => AppColors.loss,
      MoveSign.flat => AppColors.foreground,
    };

    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.surface,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: const TextStyle(color: AppColors.muted, fontSize: 11)),
          const SizedBox(height: 5),
          Text(
            value,
            style: TextStyle(color: color, fontSize: 17, fontWeight: FontWeight.w600),
          ),
          if (hint != null) ...[
            const SizedBox(height: 3),
            Text(hint!, style: const TextStyle(color: AppColors.muted, fontSize: 11)),
          ],
        ],
      ),
    );
  }
}

class _PositionsSection extends ConsumerWidget {
  const _PositionsSection({required this.portfolio});

  final Portfolio portfolio;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final positions = ref.watch(openPositionsProvider(portfolio.id));

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Positions ouvertes', style: Theme.of(context).textTheme.titleSmall),
        const SizedBox(height: 10),
        positions.when(
          loading: () => const Center(
            child: Padding(
              padding: EdgeInsets.all(20),
              child: CircularProgressIndicator(),
            ),
          ),
          error: (error, _) => ErrorStateView(
            message: error is ApiError ? error.message : 'Positions indisponibles.',
            onRetry: () => ref.invalidate(openPositionsProvider(portfolio.id)),
          ),
          data: (list) {
            if (list.isEmpty) {
              return const Padding(
                padding: EdgeInsets.symmetric(vertical: 16),
                child: EmptyStateView(
                  icon: Icons.work_outline,
                  title: 'Aucune position ouverte',
                  description:
                      'Les positions apparaîtront ici dès qu\'un ordre sera '
                      'exécuté sur ce portefeuille.',
                ),
              );
            }
            return Column(
              children: [
                for (final position in list) ...[
                  _PositionTile(position: position, currency: portfolio.baseCurrency),
                  const SizedBox(height: 8),
                ],
              ],
            );
          },
        ),
      ],
    );
  }
}

class _PositionTile extends StatelessWidget {
  const _PositionTile({required this.position, required this.currency});

  final Position position;
  final String currency;

  @override
  Widget build(BuildContext context) {
    final sign = signOf(position.unrealizedPnl);
    final pnlColor = switch (sign) {
      MoveSign.gain => AppColors.gain,
      MoveSign.loss => AppColors.loss,
      MoveSign.flat => AppColors.muted,
    };

    return Container(
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
                    Text(
                      position.symbol,
                      style: const TextStyle(fontWeight: FontWeight.w600),
                    ),
                    if (position.assetName != null)
                      Text(
                        position.assetName!,
                        style: const TextStyle(color: AppColors.muted, fontSize: 11),
                      ),
                  ],
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: (position.isLong ? AppColors.info : AppColors.warning)
                      .withValues(alpha: 0.14),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  position.isLong ? 'Long' : 'Short',
                  style: TextStyle(
                    color: position.isLong ? AppColors.info : AppColors.warning,
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: _Cell(label: 'Quantité', value: position.quantity),
              ),
              Expanded(
                child: _Cell(
                  label: 'Entrée',
                  value: formatMoney(position.averageEntryPrice, currency),
                ),
              ),
              Expanded(
                child: _Cell(
                  label: 'Latent',
                  value: formatMoney(position.unrealizedPnl, currency),
                  color: pnlColor,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _Cell extends StatelessWidget {
  const _Cell({required this.label, required this.value, this.color});

  final String label;
  final String value;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: const TextStyle(color: AppColors.muted, fontSize: 10)),
        const SizedBox(height: 3),
        Text(
          value,
          style: TextStyle(
            color: color ?? AppColors.foreground,
            fontSize: 12,
            fontWeight: FontWeight.w500,
          ),
        ),
      ],
    );
  }
}
