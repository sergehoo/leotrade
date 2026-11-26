import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/app_theme.dart';
import '../../../shared/widgets/markdown.dart';
import '../../../shared/widgets/states.dart';
import '../data/leo_controller.dart';
import '../domain/models.dart';

/// Conversation avec Leo.
///
/// Accessible depuis l'ensemble de l'application par le bouton flottant
/// de chaque écran : l'assistant sert à commenter ce que l'utilisateur
/// regarde, ce qui n'a plus de sens s'il faut quitter l'écran.
class LeoScreen extends ConsumerStatefulWidget {
  const LeoScreen({super.key, this.fromPage});

  /// Écran depuis lequel la conversation a été ouverte, transmis comme
  /// contexte à chaque message.
  final String? fromPage;

  @override
  ConsumerState<LeoScreen> createState() => _LeoScreenState();
}

class _LeoScreenState extends ConsumerState<LeoScreen> {
  final _input = TextEditingController();
  final _scroll = ScrollController();

  @override
  void dispose() {
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _send() {
    final text = _input.text;
    if (text.trim().isEmpty) return;

    // Le champ n'est vidé que si le message est VRAIMENT parti. Il était
    // effacé d'office : une connexion tombée faisait disparaître la
    // question sans rien dire.
    final sent = ref
        .read(leoControllerProvider.notifier)
        .send(text, page: widget.fromPage);
    if (!sent) return;

    _input.clear();
    _scrollToEnd();
  }

  void _scrollToEnd() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scroll.hasClients) return;
      _scroll.animateTo(
        _scroll.position.maxScrollExtent,
        duration: const Duration(milliseconds: 180),
        curve: Curves.easeOut,
      );
    });
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(leoControllerProvider);
    ref.listen(leoControllerProvider, (_, __) => _scrollToEnd());

    return Scaffold(
      appBar: AppBar(
        titleSpacing: 0,
        title: Row(
          children: [
            _LeoAvatar(speaking: state.thinking),
            const SizedBox(width: 10),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                const Text('Leo', style: TextStyle(fontSize: 16)),
                Text(
                  switch (state.connection) {
                    LeoConnection.online => 'En ligne',
                    LeoConnection.connecting => 'Connexion…',
                    LeoConnection.lost => 'Hors ligne — nouvelle tentative…',
                  },
                  style: TextStyle(
                    color: state.connection == LeoConnection.lost
                        ? AppColors.warning
                        : AppColors.muted,
                    fontSize: 11,
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
      body: Column(
        children: [
          if (state.error != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
              child: NoticeBanner(
                tone: NoticeTone.warning,
                message: state.error!,
              ),
            ),
          Expanded(
            child: state.turns.isEmpty && state.error == null
                ? const EmptyStateView(
                    icon: Icons.smart_toy_outlined,
                    title: 'Leo t\'écoute',
                    description:
                        'Pose-lui une question sur ton portefeuille, tes '
                        'positions ou tes limites de risque. Il voit l\'écran '
                        'que tu consultes.',
                  )
                // UNE zone de sélection pour toute la conversation :
                // on peut copier une phrase qui enjambe deux messages,
                // et il n'y a plus qu'une `SelectableRegion` montée au
                // lieu d'une par bulle.
                : SelectionArea(
                    child: ListView.builder(
                      controller: _scroll,
                      padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
                      itemCount: state.turns.length + (state.thinking ? 1 : 0),
                      itemBuilder: (_, index) {
                        if (index >= state.turns.length) {
                          return const _ThinkingRow();
                        }
                        return _TurnBubble(turn: state.turns[index]);
                      },
                    ),
                  ),
          ),
          if (state.actionRequest != null)
            _ActionRequestCard(request: state.actionRequest!),
          _Composer(
            controller: _input,
            enabled: state.connected,
            onSend: _send,
          ),
        ],
      ),
    );
  }
}

class _LeoAvatar extends StatelessWidget {
  const _LeoAvatar({required this.speaking});

  final bool speaking;

  @override
  Widget build(BuildContext context) {
    return AnimatedOpacity(
      opacity: speaking ? 0.55 : 1,
      duration: const Duration(milliseconds: 400),
      child: Container(
        width: 32,
        height: 32,
        decoration: BoxDecoration(
          color: AppColors.primary.withValues(alpha: 0.12),
          border: Border.all(color: AppColors.primary.withValues(alpha: 0.35)),
          shape: BoxShape.circle,
        ),
        child: const Icon(
          Icons.smart_toy_outlined,
          size: 17,
          color: AppColors.primary,
        ),
      ),
    );
  }
}

class _ThinkingRow extends StatelessWidget {
  const _ThinkingRow();

  @override
  Widget build(BuildContext context) {
    return const Padding(
      padding: EdgeInsets.symmetric(vertical: 10),
      child: Row(
        children: [
          SizedBox(
            height: 14,
            width: 14,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          SizedBox(width: 10),
          Text(
            'Leo réfléchit…',
            style: TextStyle(color: AppColors.muted, fontSize: 12),
          ),
        ],
      ),
    );
  }
}

class _TurnBubble extends ConsumerWidget {
  const _TurnBubble({required this.turn});

  final LeoTurn turn;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Align(
      alignment: turn.isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 10),
        constraints: BoxConstraints(
          maxWidth: MediaQuery.sizeOf(context).width * 0.82,
        ),
        decoration: BoxDecoration(
          color: turn.isUser
              ? AppColors.primary.withValues(alpha: 0.14)
              : AppColors.surface,
          border: Border.all(
            color: turn.isUser
                ? AppColors.primary.withValues(alpha: 0.25)
                : AppColors.border,
          ),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // L'utilisateur écrit du texte brut ; Leo répond en Markdown.
            // Sans rendu, les `**` et les séparateurs de tableau
            // s'affichaient tels quels.
            if (turn.isUser)
              // `Text` et non `SelectableText` : la sélection est déjà
              // assurée par la `SelectionArea` de l'écran, et imbriquer
              // les deux crée deux régions concurrentes.
              Text(
                turn.content,
                style: const TextStyle(fontSize: 14, height: 1.45),
              )
            else
              Markdown(turn.content),
            for (final action in turn.actions) ...[
              const SizedBox(height: 10),
              _ActionCard(action: action),
            ],
          ],
        ),
      ),
    );
  }
}

/// Action proposée par Leo.
///
/// Rien n'est exécuté sans un geste explicite : l'assistant propose, il ne
/// dispose pas.
class _ActionCard extends ConsumerStatefulWidget {
  const _ActionCard({required this.action});

  final LeoAction action;

  @override
  ConsumerState<_ActionCard> createState() => _ActionCardState();
}

class _ActionCardState extends ConsumerState<_ActionCard> {
  bool _pending = false;

  void _decide(bool confirm) {
    // Le statut n'est plus forcé ici : il vient du serveur, par
    // `action_update`. L'écran affichait « Confirmée » sans avoir rien
    // obtenu.
    final sent = ref
        .read(leoControllerProvider.notifier)
        .decideAction(widget.action.id, confirm: confirm);
    if (mounted) setState(() => _pending = sent);
  }

  @override
  Widget build(BuildContext context) {
    final action = widget.action;
    // Le statut affiché suit l'état réel de l'action.
    if (!action.isPending && _pending) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) setState(() => _pending = false);
      });
    }

    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: AppColors.warning.withValues(alpha: 0.07),
        border: Border.all(color: AppColors.warning.withValues(alpha: 0.35)),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            action.type,
            style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600),
          ),
          if (action.rationale.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(
              action.rationale,
              style: const TextStyle(
                color: AppColors.muted,
                fontSize: 11,
                height: 1.4,
              ),
            ),
          ],
          const SizedBox(height: 8),
          if (!action.isPending)
            Text(
              action.status == 'CONFIRMED' ? 'Confirmée.' : 'Annulée.',
              style: const TextStyle(color: AppColors.muted, fontSize: 11),
            )
          else
            _DecisionButtons(
              pending: _pending,
              confirmLabel: 'Confirmer',
              onDecide: _decide,
            ),
        ],
      ),
    );
  }
}

/// Deux boutons de décision, qui tiennent sur un téléphone.
///
/// Le thème impose `minimumSize: Size.fromHeight(48)` aux `FilledButton`,
/// c'est-à-dire une largeur minimale INFINIE. Dans un `Row`, deux boutons
/// réclamant chacun une largeur infinie débordent : la carte s'affichait
/// barrée de jaune et noir, et « Annuler » sortait de l'écran. `Wrap` les
/// laisse se replier, et la contrainte de largeur est levée ici seulement.
class _DecisionButtons extends StatelessWidget {
  const _DecisionButtons({
    required this.pending,
    required this.onDecide,
    required this.confirmLabel,
    this.danger = false,
  });

  final bool pending;
  final void Function(bool confirm) onDecide;
  final String confirmLabel;
  final bool danger;

  @override
  Widget build(BuildContext context) {
    // 44 pt : au-dessus du seuil de cible tactile, sans la largeur infinie
    // du thème.
    final size = const Size(0, 44);

    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        FilledButton(
          onPressed: pending ? null : () => onDecide(true),
          style: FilledButton.styleFrom(
            minimumSize: size,
            backgroundColor: danger ? AppColors.loss : null,
            foregroundColor: danger ? AppColors.foreground : null,
          ),
          child: Text(confirmLabel),
        ),
        OutlinedButton(
          onPressed: pending ? null : () => onDecide(false),
          style: OutlinedButton.styleFrom(minimumSize: size),
          child: const Text('Annuler'),
        ),
      ],
    );
  }
}

/// Demande de confirmation transactionnelle mise en attente par le Risk
/// Engine.
///
/// Elle n'était pas lue du tout : la clé `action_request` du message
/// `done` était ignorée, et aucune carte n'apparaissait pour les
/// opérations qui passent par le moteur de risque — c'est-à-dire
/// précisément celles qui engagent de l'argent.
class _ActionRequestCard extends ConsumerStatefulWidget {
  const _ActionRequestCard({required this.request});

  final LeoActionRequest request;

  @override
  ConsumerState<_ActionRequestCard> createState() => _ActionRequestCardState();
}

class _ActionRequestCardState extends ConsumerState<_ActionRequestCard> {
  bool _pending = false;

  void _decide(bool confirm) {
    final sent = ref
        .read(leoControllerProvider.notifier)
        .decideActionRequest(widget.request.id, confirm: confirm);
    if (mounted) setState(() => _pending = sent);
  }

  @override
  Widget build(BuildContext context) {
    final request = widget.request;
    final live = request.isLive;
    final tone = live ? AppColors.loss : AppColors.warning;

    return Container(
      margin: const EdgeInsets.fromLTRB(12, 0, 12, 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: tone.withValues(alpha: 0.08),
        border: Border.all(color: tone.withValues(alpha: 0.4)),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                live ? Icons.warning_amber_rounded : Icons.help_outline,
                size: 16,
                color: tone,
              ),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  live
                      ? 'Confirmation — ARGENT RÉEL'
                      : 'Confirmation — simulation',
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    color: tone,
                  ),
                ),
              ),
            ],
          ),
          if (request.summary.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(
              request.summary,
              style: const TextStyle(fontSize: 13, height: 1.4),
            ),
          ],
          if (request.riskSummary.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(
              request.riskSummary,
              style: const TextStyle(
                color: AppColors.muted,
                fontSize: 11,
                height: 1.4,
              ),
            ),
          ],
          if (request.errorMessage.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(
              request.errorMessage,
              style: const TextStyle(color: AppColors.loss, fontSize: 11),
            ),
          ],
          if (request.awaitsSecondConfirmation &&
              request.confirmationsReceived > 0) ...[
            const SizedBox(height: 6),
            Text(
              'Deuxième confirmation requise '
              '(${request.confirmationsReceived}/2).',
              style: TextStyle(color: tone, fontSize: 11),
            ),
          ],
          const SizedBox(height: 10),
          _DecisionButtons(
            pending: _pending,
            danger: live,
            confirmLabel:
                request.awaitsSecondConfirmation &&
                    request.confirmationsReceived > 0
                ? 'Confirmer définitivement'
                : 'Confirmer',
            onDecide: _decide,
          ),
        ],
      ),
    );
  }
}

class _Composer extends StatelessWidget {
  const _Composer({
    required this.controller,
    required this.enabled,
    required this.onSend,
  });

  final TextEditingController controller;
  final bool enabled;
  final VoidCallback onSend;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: EdgeInsets.fromLTRB(
        12,
        8,
        12,
        8 + MediaQuery.viewInsetsOf(context).bottom * 0,
      ),
      decoration: const BoxDecoration(
        border: Border(top: BorderSide(color: AppColors.border)),
      ),
      child: SafeArea(
        top: false,
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Expanded(
              child: TextField(
                controller: controller,
                minLines: 1,
                maxLines: 4,
                // La touche « envoyer » du clavier contournait le seul
                // garde-fou : le bouton était grisé, pas le champ.
                enabled: enabled,
                textInputAction: TextInputAction.send,
                onSubmitted: enabled ? (_) => onSend() : null,
                decoration: InputDecoration(
                  hintText: enabled ? 'Écris à Leo…' : 'Leo est hors ligne',
                  isDense: true,
                ),
              ),
            ),
            const SizedBox(width: 8),
            IconButton.filled(
              onPressed: enabled ? onSend : null,
              icon: const Icon(Icons.send, size: 18),
              tooltip: 'Envoyer',
            ),
          ],
        ),
      ),
    );
  }
}
