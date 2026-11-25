import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/format.dart';
import '../../../core/network/api_client.dart';
import '../../../core/theme/app_theme.dart';
import '../../../shared/widgets/states.dart';
import '../../auth/domain/models.dart';
import '../../auth/presentation/auth_controller.dart';
import '../data/context_repository.dart';

class DashboardScreen extends ConsumerWidget {
  const DashboardScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final contextAsync = ref.watch(appContextProvider);
    final user = ref.watch(authControllerProvider.select((s) => s.user));

    return Scaffold(
      appBar: AppBar(
        title: const Text('Tableau de bord'),
        actions: [
          IconButton(
            tooltip: 'Déconnexion',
            onPressed: () => ref.read(authControllerProvider.notifier).signOut(),
            icon: const Icon(Icons.logout),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () async => ref.refresh(appContextProvider.future),
        child: contextAsync.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (error, _) => ListView(
            children: [
              const SizedBox(height: 80),
              ErrorStateView(
                message: error is ApiError
                    ? error.message
                    : 'Une erreur inattendue est survenue.',
                onRetry: () => ref.invalidate(appContextProvider),
              ),
            ],
          ),
          data: (data) => ListView(
            padding: const EdgeInsets.all(16),
            children: [
              if (user != null && user.kycStatus != KycStatus.approved) ...[
                NoticeBanner(
                  tone: user.kycStatus == KycStatus.rejected
                      ? NoticeTone.danger
                      : NoticeTone.warning,
                  title: kycStatusLabel(user.kycStatus),
                  message: user.kycStatus == KycStatus.rejected &&
                          user.kycRejectionReason.isNotEmpty
                      ? user.kycRejectionReason
                      : "Trading réel et retraits indisponibles tant que "
                          "l'identité n'est pas validée.",
                ),
                const SizedBox(height: 14),
              ],

              if (!data.tradingEnabled) ...[
                const NoticeBanner(
                  tone: NoticeTone.danger,
                  title: 'Trading suspendu sur la plateforme',
                  message: "L'ouverture de nouvelles positions est désactivée "
                      'pour tous les comptes. Les positions existantes restent '
                      'visibles et peuvent être clôturées.',
                ),
                const SizedBox(height: 14),
              ],

              _ModeChip(isLive: data.isLive),
              const SizedBox(height: 14),

              if (data.portfolio != null)
                _PortfolioCard(portfolio: data.portfolio!)
              else
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 24),
                  child: EmptyStateView(
                    icon: Icons.account_balance_wallet_outlined,
                    title: 'Aucun portefeuille configuré',
                    description:
                        'Un portefeuille est rattaché à un compte broker. '
                        'Connectez d\'abord un broker — en mode simulation si '
                        'vous découvrez la plateforme — puis créez le '
                        'portefeuille correspondant.',
                  ),
                ),

              if (data.wallet != null) ...[
                const SizedBox(height: 14),
                _WalletCard(wallet: data.wallet!),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _ModeChip extends StatelessWidget {
  const _ModeChip({required this.isLive});

  final bool isLive;

  @override
  Widget build(BuildContext context) {
    // Le mode réel est signalé en rouge : c'est de l'argent qui part.
    final color = isLive ? AppColors.loss : AppColors.info;
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.12),
          border: Border.all(color: color.withValues(alpha: 0.35)),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Text(
          isLive ? 'Mode réel' : 'Mode simulation',
          style: TextStyle(color: color, fontWeight: FontWeight.w600, fontSize: 12),
        ),
      ),
    );
  }
}

class _PortfolioCard extends StatelessWidget {
  const _PortfolioCard({required this.portfolio});

  final ContextPortfolio portfolio;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(portfolio.name,
                      style: Theme.of(context).textTheme.titleMedium),
                ),
                if (portfolio.brokerLabel != null)
                  Text(portfolio.brokerLabel!,
                      style: const TextStyle(color: AppColors.muted, fontSize: 12)),
              ],
            ),
            const SizedBox(height: 18),
            Wrap(
              spacing: 28,
              runSpacing: 18,
              children: [
                _Metric(
                  label: 'Valeur',
                  value: formatMoney(portfolio.currentBalance, portfolio.baseCurrency),
                ),
                _Metric(
                  label: 'Liquidités',
                  value: formatMoney(portfolio.availableCash, portfolio.baseCurrency),
                ),
                _Metric(
                  label: 'Immobilisé',
                  value: formatMoney(portfolio.lockedCash, portfolio.baseCurrency),
                  hint: 'Réservé par des ordres en attente.',
                ),
              ],
            ),
            if (!portfolio.isActive) ...[
              const SizedBox(height: 16),
              const NoticeBanner(
                tone: NoticeTone.warning,
                title: 'Portefeuille inactif',
                message: 'Aucun ordre ne peut être transmis depuis ce portefeuille.',
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _WalletCard extends StatelessWidget {
  const _WalletCard({required this.wallet});

  final ContextWallet wallet;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Portefeuille électronique',
                style: TextStyle(color: AppColors.muted, fontSize: 13)),
            const SizedBox(height: 16),
            Wrap(
              spacing: 28,
              runSpacing: 18,
              children: [
                _Metric(
                  label: 'Disponible',
                  value: formatMoney(wallet.availableBalance, wallet.currency),
                ),
                _Metric(
                  label: 'Verrouillé',
                  value: formatMoney(wallet.lockedBalance, wallet.currency),
                  hint: 'Fonds engagés dans un retrait en cours.',
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _Metric extends StatelessWidget {
  const _Metric({required this.label, required this.value, this.hint});

  final String label;
  final String value;
  final String? hint;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          label.toUpperCase(),
          style: const TextStyle(
            color: AppColors.muted,
            fontSize: 11,
            letterSpacing: 0.6,
          ),
        ),
        const SizedBox(height: 5),
        Text(
          value,
          style: const TextStyle(
            fontSize: 20,
            fontWeight: FontWeight.w600,
            fontFeatures: [FontFeature.tabularFigures()],
          ),
        ),
        if (hint != null) ...[
          const SizedBox(height: 3),
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 160),
            child: Text(hint!,
                style: const TextStyle(color: AppColors.muted, fontSize: 11, height: 1.35)),
          ),
        ],
      ],
    );
  }
}
