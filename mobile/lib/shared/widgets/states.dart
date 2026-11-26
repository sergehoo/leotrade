import 'package:flutter/material.dart';

import '../../core/theme/app_theme.dart';

/// État vide.
///
/// Règle du projet : aucune donnée fictive, jamais de ligne de démonstration
/// pour remplir une liste. Un écran vide doit donc dire *pourquoi* il l'est
/// et *quoi faire* — sinon il passe pour une panne.
class EmptyStateView extends StatelessWidget {
  const EmptyStateView({
    super.key,
    required this.title,
    required this.description,
    this.icon = Icons.inbox_outlined,
    this.action,
  });

  final String title;
  final String description;
  final IconData icon;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 36, color: AppColors.muted),
            const SizedBox(height: 14),
            Text(
              title,
              style: Theme.of(context).textTheme.titleMedium,
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 8),
            Text(
              description,
              style: const TextStyle(color: AppColors.muted, height: 1.45),
              textAlign: TextAlign.center,
            ),
            if (action != null) ...[const SizedBox(height: 18), action!],
          ],
        ),
      ),
    );
  }
}

/// Échec de chargement : on montre le message réel du serveur.
class ErrorStateView extends StatelessWidget {
  const ErrorStateView({super.key, required this.message, this.onRetry});

  final String message;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.cloud_off_outlined, size: 36, color: AppColors.loss),
            const SizedBox(height: 14),
            Text('Chargement impossible',
                style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            Text(
              message,
              style: const TextStyle(color: AppColors.muted, height: 1.45),
              textAlign: TextAlign.center,
            ),
            if (onRetry != null) ...[
              const SizedBox(height: 18),
              OutlinedButton.icon(
                onPressed: onRetry,
                icon: const Icon(Icons.refresh),
                label: const Text('Réessayer'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// Bandeau d'information contextuelle (mode réel, KYC, kill switch).
class NoticeBanner extends StatelessWidget {
  const NoticeBanner({
    super.key,
    this.message,
    this.child,
    this.tone = NoticeTone.info,
    this.title,
  }) : assert(message != null || child != null,
            'Un bandeau sans message ni contenu n\'a rien à dire.');

  final String? message;

  /// Contenu riche, quand une simple chaîne ne suffit pas — les encadrés
  /// de Leo portent du Markdown complet.
  final Widget? child;

  final String? title;
  final NoticeTone tone;

  @override
  Widget build(BuildContext context) {
    final color = switch (tone) {
      NoticeTone.info => AppColors.info,
      NoticeTone.warning => AppColors.warning,
      NoticeTone.danger => AppColors.loss,
      NoticeTone.success => AppColors.gain,
    };
    final icon = switch (tone) {
      NoticeTone.info => Icons.info_outline,
      NoticeTone.warning => Icons.warning_amber_outlined,
      NoticeTone.danger => Icons.error_outline,
      NoticeTone.success => Icons.verified_outlined,
    };

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.10),
        border: Border.all(color: color.withValues(alpha: 0.35)),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 18, color: color),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (title != null)
                  Text(title!, style: const TextStyle(fontWeight: FontWeight.w600)),
                if (title != null) const SizedBox(height: 3),
                if (child != null)
                  child!
                else
                  Text(message!,
                      style: const TextStyle(color: AppColors.muted, height: 1.4)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

enum NoticeTone { info, warning, danger, success }
