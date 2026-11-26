import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../../../core/network/api_client.dart';
import '../../../core/theme/app_theme.dart';
import '../../../shared/widgets/states.dart';
import '../../auth/presentation/auth_controller.dart';
import '../data/brokers_repository.dart';
import '../domain/models.dart';
import 'broker_form_sheet.dart';

class BrokersScreen extends ConsumerWidget {
  const BrokersScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final accountsAsync = ref.watch(brokerAccountsProvider);
    final healthAsync = ref.watch(brokerHealthProvider);
    final canTradeLive = ref.watch(
      authControllerProvider
          .select((state) => state.user?.capabilities.canTradeLive ?? false),
    );

    Future<void> refresh() async {
      ref.invalidate(brokerAccountsProvider);
      ref.invalidate(brokerHealthProvider);
      await ref.read(brokerAccountsProvider.future);
    }

    Future<void> openForm({BrokerAccount? account}) async {
      final saved = await showBrokerFormSheet(
        context,
        account: account,
        canTradeLive: canTradeLive,
      );
      if (saved == true) await refresh();
    }

    return Scaffold(
      appBar: AppBar(
        title: const Text('Brokers'),
        actions: [
          IconButton(
            tooltip: 'Leo',
            onPressed: () => context.push('/leo?depuis=brokers'),
            icon: const Icon(Icons.smart_toy_outlined),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => openForm(),
        icon: const Icon(Icons.add),
        label: const Text('Ajouter'),
      ),
      body: RefreshIndicator(
        onRefresh: refresh,
        child: accountsAsync.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (error, _) => ListView(
            children: [
              const SizedBox(height: 80),
              ErrorStateView(
                message: error is ApiError
                    ? error.message
                    : 'Une erreur inattendue est survenue.',
                onRetry: refresh,
              ),
            ],
          ),
          data: (accounts) {
            final health = healthAsync.valueOrNull ?? const <int, BrokerHealth>{};

            return ListView(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 96),
              children: [
                if (!canTradeLive) ...[
                  const NoticeBanner(
                    title: 'Mode Live verrouillé',
                    tone: NoticeTone.info,
                    message:
                        'Ton KYC n\'est pas encore approuvé : les comptes restent '
                        'limités au mode Paper. La simulation fonctionne sans '
                        'restriction.',
                  ),
                  const SizedBox(height: 16),
                ],
                if (accounts.isEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 48),
                    child: EmptyStateView(
                      icon: Icons.power_outlined,
                      title: 'Aucun compte broker',
                      description:
                          'Un compte broker est le prérequis de toute exécution, '
                          'y compris en simulation. Ajoute ton premier compte '
                          'pour commencer.',
                      action: FilledButton.icon(
                        onPressed: () => openForm(),
                        icon: const Icon(Icons.add),
                        label: const Text('Ajouter un compte'),
                      ),
                    ),
                  )
                else
                  for (final account in accounts) ...[
                    _BrokerCard(
                      account: account,
                      health: health[account.id],
                      onEdit: () => openForm(account: account),
                      onChanged: refresh,
                    ),
                    const SizedBox(height: 12),
                  ],
              ],
            );
          },
        ),
      ),
    );
  }
}

class _BrokerCard extends ConsumerStatefulWidget {
  const _BrokerCard({
    required this.account,
    required this.health,
    required this.onEdit,
    required this.onChanged,
  });

  final BrokerAccount account;
  final BrokerHealth? health;
  final VoidCallback onEdit;
  final Future<void> Function() onChanged;

  @override
  ConsumerState<_BrokerCard> createState() => _BrokerCardState();
}

class _BrokerCardState extends ConsumerState<_BrokerCard> {
  bool _busy = false;

  BrokerAccount get _account => widget.account;

  void _toast(String message, {bool danger = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: danger ? AppColors.loss : AppColors.surfaceHigh,
      ),
    );
  }

  Future<void> _run(Future<void> Function() action, {required String success}) async {
    setState(() => _busy = true);
    try {
      await action();
      await widget.onChanged();
      _toast(success);
    } on ApiError catch (error) {
      // La liste est rafraîchie même en cas d'échec : le serveur a
      // persisté le nouvel état de connexion, l'écran doit le refléter.
      await widget.onChanged();
      _toast(
        error.code == 'MISSING_SECRETS'
            ? 'Identifiants incomplets : renseigne-les avant de tester.'
            : error.message,
        danger: true,
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _confirmDelete() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: AppColors.surface,
        title: Text('Supprimer « ${_account.name} » ?'),
        content: const Text(
          'Cette action est irréversible. Les identifiants chiffrés sont '
          'détruits avec le compte.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('Annuler'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: AppColors.loss),
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text('Supprimer'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;

    final repository = ref.read(brokersRepositoryProvider);
    await _run(() => repository.remove(_account.id), success: 'Compte supprimé.');
  }

  @override
  Widget build(BuildContext context) {
    final repository = ref.read(brokersRepositoryProvider);

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.surface,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Wrap(
                      spacing: 8,
                      runSpacing: 6,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: [
                        Text(
                          _account.name,
                          style: Theme.of(context).textTheme.titleMedium,
                        ),
                        if (_account.isDefault)
                          const _Chip(label: 'Par défaut', color: AppColors.info),
                        _ModeChip(mode: _account.mode),
                        if (!_account.isActive)
                          const _Chip(label: 'Inactif', color: AppColors.muted),
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(
                      [
                        brokerKindLabel(_account.broker),
                        if (_account.login != null) _account.login!,
                        if (_account.server != null) _account.server!,
                      ].join(' · '),
                      style: const TextStyle(color: AppColors.muted, fontSize: 13),
                    ),
                  ],
                ),
              ),
              PopupMenuButton<String>(
                enabled: !_busy,
                color: AppColors.surfaceHigh,
                onSelected: (value) => switch (value) {
                  'edit' => widget.onEdit(),
                  'default' => _run(
                      () => repository.setDefault(_account.id).then((_) {}),
                      success: '« ${_account.name} » est le compte par défaut.',
                    ),
                  'delete' => _confirmDelete(),
                  _ => null,
                },
                itemBuilder: (_) => [
                  const PopupMenuItem(value: 'edit', child: Text('Modifier')),
                  if (!_account.isDefault)
                    const PopupMenuItem(
                      value: 'default',
                      child: Text('Définir par défaut'),
                    ),
                  const PopupMenuItem(
                    value: 'delete',
                    child: Text('Supprimer', style: TextStyle(color: AppColors.loss)),
                  ),
                ],
              ),
            ],
          ),

          if (_account.missingSecrets.isNotEmpty) ...[
            const SizedBox(height: 14),
            NoticeBanner(
              tone: NoticeTone.warning,
              title: 'Identifiants incomplets',
              message:
                  '${_account.missingSecrets.map(secretFieldLabel).join(', ')} — '
                  'aucune connexion réelle n\'aboutira tant que ces champs sont vides.',
            ),
          ],

          if (_account.hasError && (_account.lastConnectionError ?? '').isNotEmpty) ...[
            const SizedBox(height: 14),
            NoticeBanner(
              tone: NoticeTone.danger,
              title: 'Dernière connexion en échec',
              message: _account.lastConnectionError!,
            ),
          ],

          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: _Metric(
                  label: 'Connexion',
                  value: _account.connected ? 'Établie' : 'Jamais vérifiée',
                  color: _account.connected ? AppColors.gain : AppColors.muted,
                ),
              ),
              Expanded(
                child: _Metric(
                  label: 'Dernier test',
                  value: _formatDate(_account.lastConnectedAt),
                ),
              ),
              Expanded(
                child: _Metric(
                  label: 'Circuit',
                  value: widget.health == null
                      ? '—'
                      : circuitStateLabel(widget.health!.circuitState),
                  color: widget.health == null
                      ? null
                      : _circuitColor(widget.health!.circuitState),
                ),
              ),
            ],
          ),

          const SizedBox(height: 16),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              onPressed: _busy
                  ? null
                  : () => _run(
                        () => repository.testConnection(_account.id),
                        success: 'Connexion établie avec « ${_account.name} ».',
                      ),
              icon: _busy
                  ? const SizedBox(
                      height: 16,
                      width: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.bolt_outlined),
              label: const Text('Tester la connexion'),
            ),
          ),
        ],
      ),
    );
  }

  static String _formatDate(DateTime? value) {
    if (value == null) return '—';
    return DateFormat('dd/MM HH:mm', 'fr_FR').format(value.toLocal());
  }

  static Color _circuitColor(CircuitState state) => switch (state) {
        CircuitState.closed => AppColors.gain,
        CircuitState.halfOpen => AppColors.warning,
        CircuitState.open => AppColors.loss,
        CircuitState.unavailable => AppColors.muted,
      };
}

class _Metric extends StatelessWidget {
  const _Metric({required this.label, required this.value, this.color});

  final String label;
  final String value;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: const TextStyle(color: AppColors.muted, fontSize: 11)),
        const SizedBox(height: 3),
        Text(
          value,
          style: TextStyle(
            color: color ?? AppColors.foreground,
            fontSize: 13,
            fontWeight: FontWeight.w500,
          ),
        ),
      ],
    );
  }
}

class _Chip extends StatelessWidget {
  const _Chip({required this.label, required this.color, this.icon});

  final String label;
  final Color color;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        border: Border.all(color: color.withValues(alpha: 0.35)),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[
            Icon(icon, size: 12, color: color),
            const SizedBox(width: 4),
          ],
          Text(
            label,
            style: TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.w600),
          ),
        ],
      ),
    );
  }
}

/// Le mode Live engage de l'argent réel : il doit se distinguer d'un coup
/// d'œil, sans reposer sur la seule lecture du mot.
class _ModeChip extends StatelessWidget {
  const _ModeChip({required this.mode});

  final TradingMode mode;

  @override
  Widget build(BuildContext context) {
    return mode == TradingMode.live
        ? const _Chip(
            label: 'Live',
            color: AppColors.warning,
            icon: Icons.warning_amber_outlined,
          )
        : const _Chip(label: 'Paper', color: AppColors.muted);
  }
}
