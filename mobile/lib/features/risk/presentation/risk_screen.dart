import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/format.dart';
import '../../../core/network/api_client.dart';
import '../../../core/theme/app_theme.dart';
import '../../../shared/widgets/leo_fab.dart';
import '../../../shared/widgets/states.dart';
import '../../portfolio/data/portfolio_repository.dart';
import '../../portfolio/domain/models.dart' as pf;
import '../data/risk_repository.dart';
import '../domain/models.dart';

class RiskScreen extends ConsumerStatefulWidget {
  const RiskScreen({super.key});

  @override
  ConsumerState<RiskScreen> createState() => _RiskScreenState();
}

class _RiskScreenState extends ConsumerState<RiskScreen> {
  int? _selectedId;

  @override
  Widget build(BuildContext context) {
    final portfolios = ref.watch(portfoliosProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Risque')),
      floatingActionButton: const LeoFab(page: 'risque'),
      body: portfolios.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => ErrorStateView(
          message: error is ApiError ? error.message : 'Chargement impossible.',
          onRetry: () => ref.invalidate(portfoliosProvider),
        ),
        data: (list) {
          if (list.isEmpty) {
            return const Padding(
              padding: EdgeInsets.only(top: 60),
              child: EmptyStateView(
                icon: Icons.shield_outlined,
                title: 'Aucun portefeuille à surveiller',
                description:
                    'Le contrôle du risque s\'applique à un portefeuille. '
                    'Crées-en un depuis la section Portefeuille pour voir tes '
                    'limites.',
              ),
            );
          }

          final active = list.firstWhere(
            (p) => p.id == _selectedId,
            orElse: () => list.firstWhere((p) => p.isDefault, orElse: () => list.first),
          );

          return RefreshIndicator(
            onRefresh: () async {
              ref.invalidate(riskSummaryProvider(active.id));
              await ref.read(riskSummaryProvider(active.id).future);
            },
            child: ListView(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 96),
              children: [
                if (list.length > 1) ...[
                  _PortfolioPicker(
                    portfolios: list,
                    activeId: active.id,
                    onSelect: (id) => setState(() => _selectedId = id),
                  ),
                  const SizedBox(height: 16),
                ],
                _RiskBody(portfolio: active),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _PortfolioPicker extends StatelessWidget {
  const _PortfolioPicker({
    required this.portfolios,
    required this.activeId,
    required this.onSelect,
  });

  final List<pf.Portfolio> portfolios;
  final int activeId;
  final ValueChanged<int> onSelect;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 36,
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
              child: Text(
                portfolio.name,
                style: TextStyle(
                  color: selected ? AppColors.foreground : AppColors.muted,
                  fontSize: 13,
                ),
              ),
            ),
          );
        },
      ),
    );
  }
}

class _RiskBody extends ConsumerWidget {
  const _RiskBody({required this.portfolio});

  final pf.Portfolio portfolio;

  Future<void> _confirmResolve(BuildContext context, WidgetRef ref, String reason) async {
    // Capturé AVANT l'await : après la fermeture du dialogue, le contexte
    // peut avoir été démonté et son utilisation devient invalide.
    final messenger = ScaffoldMessenger.of(context);

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: AppColors.surface,
        title: const Text('Lever l\'arrêt d\'urgence ?'),
        content: Text(
          'L\'ouverture de nouvelles positions redeviendra possible '
          'immédiatement.\n\n'
          'Motif : ${reason.isEmpty ? 'une limite de risque a été franchie' : reason}\n\n'
          'La cause ne disparaît pas en levant l\'arrêt.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('Annuler'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: AppColors.loss),
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text('Lever l\'arrêt'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;

    try {
      final count =
          await ref.read(riskRepositoryProvider).resolveKillSwitch(portfolio.id);
      ref.invalidate(riskSummaryProvider(portfolio.id));
      messenger.showSnackBar(
        SnackBar(
          content: Text(
            count > 0
                ? 'Arrêt d\'urgence levé.'
                : 'Aucun arrêt d\'urgence actif.',
          ),
        ),
      );
    } on ApiError catch (error) {
      messenger.showSnackBar(
        SnackBar(content: Text(error.message), backgroundColor: AppColors.loss),
      );
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final summary = ref.watch(riskSummaryProvider(portfolio.id));

    return summary.when(
      loading: () => const Center(
        child: Padding(padding: EdgeInsets.all(32), child: CircularProgressIndicator()),
      ),
      error: (error, _) => ErrorStateView(
        message: error is ApiError ? error.message : 'Chargement impossible.',
        onRetry: () => ref.invalidate(riskSummaryProvider(portfolio.id)),
      ),
      data: (data) {
        final profile = data.profile;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (data.killSwitchActive) ...[
              NoticeBanner(
                tone: NoticeTone.danger,
                title: 'Arrêt d\'urgence actif',
                message: data.killSwitchReason.isEmpty
                    ? 'Une limite de risque a été franchie. Aucune nouvelle '
                      'position ne peut être ouverte.'
                    : data.killSwitchReason,
              ),
              const SizedBox(height: 10),
              OutlinedButton(
                onPressed: () => _confirmResolve(context, ref, data.killSwitchReason),
                child: const Text('Lever l\'arrêt d\'urgence'),
              ),
              const SizedBox(height: 16),
            ],

            if (profile != null) ...[
              _PreservationBanner(profile: profile),
              const SizedBox(height: 16),
            ],

            for (final limit in data.limits) ...[
              _LimitCard(limit: limit),
              const SizedBox(height: 10),
            ],

            _PositionsCard(summary: data),

            if (profile != null) ...[
              const SizedBox(height: 20),
              _PreservationPanel(portfolioId: portfolio.id, profile: profile),
            ],
          ],
        );
      },
    );
  }
}

class _PreservationBanner extends StatelessWidget {
  const _PreservationBanner({required this.profile});

  final RiskProfileSummary profile;

  @override
  Widget build(BuildContext context) {
    return NoticeBanner(
      tone: profile.preservationMode ? NoticeTone.success : NoticeTone.warning,
      title: profile.preservationMode
          ? 'Préservation du capital active'
          : 'Préservation désactivée',
      message: profile.preservationMode
          ? 'L\'univers est restreint aux instruments dont l\'espérance n\'est '
            'pas structurellement négative.'
          : 'Les instruments à espérance négative peuvent être négociés. '
            'Sur la durée, ils perdent par construction.',
    );
  }
}

/// Jauge d'une limite.
///
/// La couleur suit la consommation, pas la nature de la limite : à 90 % d'une
/// limite de perte, l'utilisateur doit voir du rouge même si rien n'est
/// encore bloqué.
class _LimitCard extends StatelessWidget {
  const _LimitCard({required this.limit});

  final RiskLimit limit;

  @override
  Widget build(BuildContext context) {
    final color = limit.isBreached
        ? AppColors.loss
        : limit.isNearLimit
            ? AppColors.warning
            : AppColors.gain;

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
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(limit.label,
                  style: const TextStyle(color: AppColors.muted, fontSize: 12)),
              if (limit.isBreached)
                _Tag(label: 'Dépassée', color: AppColors.loss)
              else if (limit.isNearLimit)
                _Tag(label: 'Proche', color: AppColors.warning),
            ],
          ),
          const SizedBox(height: 6),
          Row(
            crossAxisAlignment: CrossAxisAlignment.baseline,
            textBaseline: TextBaseline.alphabetic,
            children: [
              Text(
                formatPercent(limit.consumedPercent),
                style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
              ),
              const SizedBox(width: 5),
              Text(
                '/ ${formatPercent(limit.limitPercent)}',
                style: const TextStyle(color: AppColors.muted, fontSize: 13),
              ),
            ],
          ),
          const SizedBox(height: 10),
          if (!limit.hasLimit)
            const Text(
              'Aucune limite définie — rien ne sera bloqué.',
              style: TextStyle(color: AppColors.muted, fontSize: 11),
            )
          else ...[
            ClipRRect(
              borderRadius: BorderRadius.circular(3),
              child: LinearProgressIndicator(
                value: (limit.usage / 100).clamp(0.0, 1.0),
                minHeight: 6,
                backgroundColor: AppColors.border,
                valueColor: AlwaysStoppedAnimation(color),
              ),
            ),
            const SizedBox(height: 6),
            Text(
              '${formatPercent(limit.usagePercent)} de la limite',
              style: const TextStyle(color: AppColors.muted, fontSize: 11),
            ),
          ],
        ],
      ),
    );
  }
}

class _PositionsCard extends StatelessWidget {
  const _PositionsCard({required this.summary});

  final RiskSummary summary;

  @override
  Widget build(BuildContext context) {
    final max = summary.maxOpenPositions;
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
          const Text('Positions ouvertes',
              style: TextStyle(color: AppColors.muted, fontSize: 12)),
          const SizedBox(height: 6),
          Row(
            crossAxisAlignment: CrossAxisAlignment.baseline,
            textBaseline: TextBaseline.alphabetic,
            children: [
              Text('${summary.openPositions}',
                  style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600)),
              if (max > 0) ...[
                const SizedBox(width: 5),
                Text('/ $max',
                    style: const TextStyle(color: AppColors.muted, fontSize: 13)),
              ],
            ],
          ),
          const SizedBox(height: 4),
          Text(
            max > 0
                ? '${(max - summary.openPositions).clamp(0, max)} encore ouvrable(s)'
                : 'Aucun plafond défini',
            style: const TextStyle(color: AppColors.muted, fontSize: 11),
          ),
        ],
      ),
    );
  }
}

class _PreservationPanel extends ConsumerStatefulWidget {
  const _PreservationPanel({required this.portfolioId, required this.profile});

  final int portfolioId;
  final RiskProfileSummary profile;

  @override
  ConsumerState<_PreservationPanel> createState() => _PreservationPanelState();
}

class _PreservationPanelState extends ConsumerState<_PreservationPanel> {
  bool _saving = false;

  Future<void> _set(String field, bool value) async {
    setState(() => _saving = true);
    final messenger = ScaffoldMessenger.of(context);
    try {
      await ref
          .read(riskRepositoryProvider)
          .setPreservationFlag(widget.profile.id, field, value);
      ref.invalidate(riskSummaryProvider(widget.portfolioId));
      messenger.showSnackBar(
        const SnackBar(content: Text('Politique de préservation mise à jour.')),
      );
    } on ApiError catch (error) {
      messenger.showSnackBar(
        SnackBar(content: Text(error.message), backgroundColor: AppColors.loss),
      );
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final profile = widget.profile;

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
          Text('Préservation du capital',
              style: Theme.of(context).textTheme.titleSmall),
          const SizedBox(height: 4),
          Text(
            'Profil « ${profile.name} ». Ces réglages sont appliqués par le '
            'serveur avant chaque ordre, pas seulement affichés ici.',
            style: const TextStyle(color: AppColors.muted, fontSize: 11, height: 1.4),
          ),
          const SizedBox(height: 10),
          SwitchListTile.adaptive(
            value: profile.preservationMode,
            onChanged: _saving ? null : (v) => _set('preservation_mode', v),
            contentPadding: EdgeInsets.zero,
            title: const Text('Mode préservation'),
            subtitle: const Text(
              'Restreint l\'univers aux instruments dont l\'espérance n\'est '
              'pas structurellement négative.',
              style: TextStyle(color: AppColors.muted, fontSize: 11),
            ),
          ),
          SwitchListTile.adaptive(
            value: profile.allowVolatile,
            onChanged: _saving ? null : (v) => _set('allow_volatile_instruments', v),
            contentPadding: EdgeInsets.zero,
            title: const Text('Instruments à volatilité élevée'),
            subtitle: const Text(
              'Crypto, FX exotique, matières premières.',
              style: TextStyle(color: AppColors.muted, fontSize: 11),
            ),
          ),
          SwitchListTile.adaptive(
            value: profile.allowSpeculative,
            onChanged: _saving ? null : (v) => _set('allow_speculative_instruments', v),
            contentPadding: EdgeInsets.zero,
            title: const Text('Instruments à espérance négative'),
            subtitle: const Text(
              'Synthétiques Deriv et assimilés. Sur la durée, ces instruments '
              'perdent par construction.',
              style: TextStyle(color: AppColors.muted, fontSize: 11),
            ),
          ),
        ],
      ),
    );
  }
}

class _Tag extends StatelessWidget {
  const _Tag({required this.label, required this.color});

  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.14),
        border: Border.all(color: color.withValues(alpha: 0.35)),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        label,
        style: TextStyle(color: color, fontSize: 10, fontWeight: FontWeight.w600),
      ),
    );
  }
}
