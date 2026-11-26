import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../../core/format.dart';
import '../../../core/network/api_client.dart';
import '../../../core/theme/app_theme.dart';
import '../../../shared/widgets/leo_fab.dart';
import '../../../shared/widgets/states.dart';
import '../../auth/presentation/auth_controller.dart';
import '../data/wallet_repository.dart';
import '../domain/models.dart';

class WalletScreen extends ConsumerWidget {
  const WalletScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final summary = ref.watch(walletSummaryProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Portefeuille électronique')),
      floatingActionButton: const LeoFab(page: 'portefeuille-electronique'),
      body: summary.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => ErrorStateView(
          message: error is ApiError ? error.message : 'Chargement impossible.',
          onRetry: () => ref.invalidate(walletSummaryProvider),
        ),
        data: (data) {
          if (!data.hasWallet) {
            return const Padding(
              padding: EdgeInsets.only(top: 60),
              child: EmptyStateView(
                icon: Icons.account_balance_wallet_outlined,
                title: 'Aucun portefeuille électronique',
                description:
                    'Ton portefeuille sera créé automatiquement au premier '
                    'approvisionnement.',
              ),
            );
          }

          return RefreshIndicator(
            onRefresh: () async {
              ref.invalidate(walletSummaryProvider);
              ref.invalidate(walletLedgerProvider);
              ref.invalidate(walletWithdrawalsProvider);
              await ref.read(walletSummaryProvider.future);
            },
            child: ListView(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 90),
              children: [
                if (data.hasUnexplainedFunds) ...[
                  NoticeBanner(
                    tone: NoticeTone.warning,
                    title: 'Une partie de ce solde n\'est pas tracée',
                    message:
                        '${formatMoney(data.unexplainedAmount, data.currency)} '
                        'n\'apparaissent pas dans l\'historique des mouvements. '
                        'Ce montant existe sur ton solde mais aucune opération '
                        'ne l\'explique. Signale-le au support avant d\'engager '
                        'ces fonds.',
                  ),
                  const SizedBox(height: 16),
                ],

                const _SectionTitle('Argent réel'),
                const SizedBox(height: 8),
                _Metric(
                  label: 'Solde total',
                  value: formatMoney(data.totalBalance, data.currency),
                  hint: 'Disponible et verrouillé réunis',
                ),
                const SizedBox(height: 10),
                _Metric(
                  label: 'Disponible',
                  value: formatMoney(data.availableBalance, data.currency),
                  hint: 'Mobilisable immédiatement',
                ),
                const SizedBox(height: 10),
                _Metric(
                  label: 'Verrouillé',
                  value: formatMoney(data.lockedBalance, data.currency),
                  hint: data.pendingWithdrawalsCount > 0
                      ? '${data.pendingWithdrawalsCount} retrait(s) en attente'
                      : 'Aucun engagement en cours',
                  icon: Icons.lock_outline,
                ),

                const SizedBox(height: 20),
                const _SectionTitle('Capital de trading'),
                const SizedBox(height: 8),
                _Metric(
                  label: 'En simulation',
                  value: formatMoney(
                    data.simulatedTradingCapital,
                    data.currency,
                  ),
                  hint: 'N\'atteint aucun marché — cet argent n\'existe pas',
                  muted: true,
                ),
                const SizedBox(height: 10),
                _Metric(
                  label: 'Engagé en réel',
                  value: formatMoney(data.liveTradingCapital, data.currency),
                  hint: 'Portefeuilles branchés sur un broker réel',
                ),

                const SizedBox(height: 20),
                _WithdrawButton(summary: data),

                const SizedBox(height: 24),
                const _SectionTitle('Demandes de retrait'),
                const SizedBox(height: 8),
                const _WithdrawalsList(),

                const SizedBox(height: 24),
                const _SectionTitle('Historique des mouvements'),
                const SizedBox(height: 8),
                const _LedgerList(),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle(this.label);

  final String label;

  @override
  Widget build(BuildContext context) =>
      Text(label, style: Theme.of(context).textTheme.titleSmall);
}

class _Metric extends StatelessWidget {
  const _Metric({
    required this.label,
    required this.value,
    this.hint,
    this.icon,
    this.muted = false,
  });

  final String label;
  final String value;
  final String? hint;
  final IconData? icon;
  final bool muted;

  @override
  Widget build(BuildContext context) {
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
              if (icon != null) ...[
                Icon(icon, size: 13, color: AppColors.muted),
                const SizedBox(width: 5),
              ],
              Text(
                label,
                style: const TextStyle(color: AppColors.muted, fontSize: 12),
              ),
            ],
          ),
          const SizedBox(height: 5),
          Text(
            value,
            style: TextStyle(
              fontSize: 19,
              fontWeight: FontWeight.w600,
              // Le capital simulé est grisé : il ne doit pas se lire comme
              // de l'argent disponible.
              color: muted ? AppColors.muted : AppColors.foreground,
            ),
          ),
          if (hint != null) ...[
            const SizedBox(height: 3),
            Text(
              hint!,
              style: const TextStyle(color: AppColors.muted, fontSize: 11),
            ),
          ],
        ],
      ),
    );
  }
}

class _WithdrawButton extends ConsumerWidget {
  const _WithdrawButton({required this.summary});

  final WalletSummary summary;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final canWithdraw = ref.watch(
      authControllerProvider.select(
        (state) => state.user?.capabilities.canWithdraw ?? false,
      ),
    );

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (!canWithdraw) ...[
          const NoticeBanner(
            tone: NoticeTone.warning,
            title: 'Vérification d\'identité requise',
            message:
                'Les retraits sont bloqués tant que ton dossier KYC n\'est pas '
                'approuvé.',
          ),
          const SizedBox(height: 10),
        ],
        OutlinedButton.icon(
          onPressed: canWithdraw
              ? () => _openWithdrawSheet(context, ref, summary)
              : null,
          icon: const Icon(Icons.download_outlined),
          label: const Text('Demander un retrait'),
        ),
      ],
    );
  }
}

Future<void> _openWithdrawSheet(
  BuildContext context,
  WidgetRef ref,
  WalletSummary summary,
) async {
  final amount = TextEditingController();
  final destination = TextEditingController();
  final messenger = ScaffoldMessenger.of(context);

  final sent = await showModalBottomSheet<bool>(
    context: context,
    isScrollControlled: true,
    backgroundColor: AppColors.surface,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(18)),
    ),
    builder: (sheetContext) => _WithdrawSheet(
      summary: summary,
      amount: amount,
      destination: destination,
    ),
  );

  amount.dispose();
  destination.dispose();

  if (sent == true) {
    ref.invalidate(walletSummaryProvider);
    ref.invalidate(walletLedgerProvider);
    ref.invalidate(walletWithdrawalsProvider);
    messenger.showSnackBar(
      const SnackBar(
        content: Text(
          'Demande enregistrée. Les fonds sont verrouillés en attente de revue.',
        ),
      ),
    );
  }
}

class _WithdrawSheet extends ConsumerStatefulWidget {
  const _WithdrawSheet({
    required this.summary,
    required this.amount,
    required this.destination,
  });

  final WalletSummary summary;
  final TextEditingController amount;
  final TextEditingController destination;

  @override
  ConsumerState<_WithdrawSheet> createState() => _WithdrawSheetState();
}

class _WithdrawSheetState extends ConsumerState<_WithdrawSheet> {
  bool _sending = false;
  String? _error;

  Future<void> _submit() async {
    setState(() {
      _sending = true;
      _error = null;
    });
    try {
      await ref
          .read(walletRepositoryProvider)
          .requestWithdrawal(
            amount: widget.amount.text.trim(),
            destinationMasked: widget.destination.text.trim(),
          );
      if (mounted) Navigator.of(context).pop(true);
    } on ApiError catch (error) {
      if (!mounted) return;
      setState(() {
        _sending = false;
        _error = error.message;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    // La feuille ne se referme plus pendant l'envoi : la demande partait,
    // l'écran n'en gardait aucune trace, et le solde affiché restait
    // l'ancien. Sur un retrait, croire que rien n'est parti conduit à
    // recommencer.
    return PopScope(
      canPop: !_sending,
      child: Padding(
        padding: EdgeInsets.only(
          bottom: MediaQuery.viewInsetsOf(context).bottom,
        ),
        child: SafeArea(
          // Défilement : clavier ouvert sur un écran court, le bouton
          // « Demander le retrait » sortait de l'écran sans recours.
          child: SingleChildScrollView(
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    'Demander un retrait',
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                  const SizedBox(height: 6),
                  const Text(
                    'Les fonds sont verrouillés immédiatement, puis versés après '
                    'revue. Rien n\'est envoyé à ce stade.',
                    style: TextStyle(
                      color: AppColors.muted,
                      height: 1.4,
                      fontSize: 12,
                    ),
                  ),
                  const SizedBox(height: 18),
                  if (_error != null) ...[
                    NoticeBanner(tone: NoticeTone.danger, message: _error!),
                    const SizedBox(height: 14),
                  ],
                  TextField(
                    controller: widget.amount,
                    keyboardType: const TextInputType.numberWithOptions(
                      decimal: true,
                    ),
                    decoration: InputDecoration(
                      labelText: 'Montant (${widget.summary.currency})',
                      helperText:
                          'Disponible : ${formatMoney(widget.summary.availableBalance, widget.summary.currency)} — '
                          'entre 5 et 100 000 par opération.',
                      helperMaxLines: 2,
                    ),
                  ),
                  const SizedBox(height: 14),
                  TextField(
                    controller: widget.destination,
                    decoration: const InputDecoration(
                      labelText: 'Destination (facultatif)',
                      hintText: '•••• 4242',
                      helperText:
                          'Indique seulement les derniers chiffres — un numéro '
                          'complet sera refusé.',
                      helperMaxLines: 2,
                    ),
                  ),
                  const SizedBox(height: 22),
                  FilledButton(
                    onPressed: _sending ? null : _submit,
                    child: _sending
                        ? const SizedBox(
                            height: 18,
                            width: 18,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Text('Demander le retrait'),
                  ),
                  TextButton(
                    onPressed: _sending
                        ? null
                        : () => Navigator.of(context).pop(false),
                    child: const Text('Annuler'),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _LedgerList extends ConsumerWidget {
  const _LedgerList();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ledger = ref.watch(walletLedgerProvider);

    return ledger.when(
      loading: () => const Center(
        child: Padding(
          padding: EdgeInsets.all(20),
          child: CircularProgressIndicator(),
        ),
      ),
      error: (error, _) => ErrorStateView(
        message: error is ApiError ? error.message : 'Historique indisponible.',
        onRetry: () => ref.invalidate(walletLedgerProvider),
      ),
      data: (page) {
        final entries = page.items;
        if (entries.isEmpty) {
          return const Padding(
            padding: EdgeInsets.symmetric(vertical: 16),
            child: EmptyStateView(
              icon: Icons.receipt_long_outlined,
              title: 'Aucun mouvement',
              description:
                  'Les crédits, débits et verrouillages apparaîtront ici, '
                  'chacun avec le solde qu\'il laisse derrière lui.',
            ),
          );
        }
        return Column(
          children: [
            for (final entry in entries) ...[
              _LedgerTile(entry: entry),
              const SizedBox(height: 8),
            ],
            if (page.hasMore) ...[
              const SizedBox(height: 4),
              // Un historique coupé sans un mot se lit comme un historique
              // complet : le mouvement manquant passe pour inexistant.
              Text(
                '${entries.length} mouvements sur ${page.count}.',
                style: const TextStyle(color: AppColors.muted, fontSize: 11),
              ),
              const SizedBox(height: 8),
              OutlinedButton(
                onPressed: () => ref
                    .read(ledgerPageSizeProvider.notifier)
                    .update((size) => size + 50),
                child: const Text('Charger plus'),
              ),
            ],
          ],
        );
      },
    );
  }
}

/// Suivi des demandes de retrait.
///
/// Le mobile jetait la réponse 201 et n'affichait jamais la suite : une
/// demande partie disparaissait de l'écran. Son refus comme son paiement
/// restaient invisibles, alors que le web les montre.
class _WithdrawalsList extends ConsumerWidget {
  const _WithdrawalsList();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final withdrawals = ref.watch(walletWithdrawalsProvider);

    return withdrawals.when(
      loading: () => const Padding(
        padding: EdgeInsets.symmetric(vertical: 16),
        child: Center(child: CircularProgressIndicator()),
      ),
      error: (error, _) => ErrorStateView(
        message: error is ApiError ? error.message : 'Suivi indisponible.',
        onRetry: () => ref.invalidate(walletWithdrawalsProvider),
      ),
      data: (page) {
        if (page.isEmpty) {
          return const Text(
            'Aucune demande de retrait.',
            style: TextStyle(color: AppColors.muted, fontSize: 12),
          );
        }
        return Column(
          children: [
            for (final request in page.items) ...[
              _WithdrawalTile(request: request),
              const SizedBox(height: 8),
            ],
          ],
        );
      },
    );
  }
}

class _WithdrawalTile extends StatelessWidget {
  const _WithdrawalTile({required this.request});

  final WithdrawalRequest request;

  @override
  Widget build(BuildContext context) {
    final tone = request.isRefused
        ? AppColors.loss
        : request.status == WithdrawalStatus.paid
        ? AppColors.gain
        : AppColors.warning;

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.surface,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  formatMoney(request.amount, request.currency),
                  style: const TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w600,
                    fontFeatures: [FontFeature.tabularFigures()],
                  ),
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: tone.withValues(alpha: 0.14),
                  border: Border.all(color: tone.withValues(alpha: 0.35)),
                  borderRadius: BorderRadius.circular(999),
                ),
                child: Text(
                  request.statusLabel,
                  style: TextStyle(
                    color: tone,
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            [
              if (request.createdAt != null)
                'Demandé le ${DateFormat('dd/MM/yyyy à HH:mm', 'fr_FR').format(request.createdAt!.toLocal())}',
              if ((request.destinationMasked ?? '').isNotEmpty)
                'vers ${request.destinationMasked}',
            ].join(' · '),
            style: const TextStyle(color: AppColors.muted, fontSize: 11),
          ),
          if (request.isOpen) ...[
            const SizedBox(height: 4),
            const Text(
              'Les fonds restent verrouillés tant que la revue n\'a pas tranché.',
              style: TextStyle(color: AppColors.muted, fontSize: 11),
            ),
          ],
          if (request.failureReason.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(
              request.failureReason,
              style: const TextStyle(color: AppColors.loss, fontSize: 11),
            ),
          ],
        ],
      ),
    );
  }
}

class _LedgerTile extends StatelessWidget {
  const _LedgerTile({required this.entry});

  final LedgerEntry entry;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.surface,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  ledgerTypeLabel(entry.type),
                  style: const TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                if (entry.description.isNotEmpty)
                  Text(
                    entry.description,
                    style: const TextStyle(
                      color: AppColors.muted,
                      fontSize: 11,
                    ),
                  ),
                if (entry.createdAt != null)
                  Text(
                    DateFormat(
                      'dd/MM/yy HH:mm',
                      'fr_FR',
                    ).format(entry.createdAt!.toLocal()),
                    style: const TextStyle(
                      color: AppColors.muted,
                      fontSize: 10,
                    ),
                  ),
              ],
            ),
          ),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                formatMoney(entry.amount, entry.currency),
                style: const TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                ),
              ),
              Text(
                'solde ${formatMoney(entry.balanceAfter, entry.currency)}',
                style: const TextStyle(color: AppColors.muted, fontSize: 10),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
