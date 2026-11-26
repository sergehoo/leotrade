import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/app_theme.dart';
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
    ref.read(leoControllerProvider.notifier).send(text, page: widget.fromPage);
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
                  state.connected ? 'En ligne' : 'Connexion…',
                  style: const TextStyle(color: AppColors.muted, fontSize: 11),
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
              child: NoticeBanner(tone: NoticeTone.warning, message: state.error!),
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
                : ListView.builder(
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
        child: const Icon(Icons.smart_toy_outlined, size: 17, color: AppColors.primary),
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
          SizedBox(height: 14, width: 14, child: CircularProgressIndicator(strokeWidth: 2)),
          SizedBox(width: 10),
          Text('Leo réfléchit…',
              style: TextStyle(color: AppColors.muted, fontSize: 12)),
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
            SelectableText(
              turn.content,
              style: const TextStyle(fontSize: 14, height: 1.45),
            ),
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

  Future<void> _decide(bool confirm) async {
    setState(() => _pending = true);
    await ref
        .read(leoControllerProvider.notifier)
        .decideAction(widget.action.id, confirm: confirm);
    if (mounted) setState(() => _pending = false);
  }

  @override
  Widget build(BuildContext context) {
    final action = widget.action;

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
          Text(action.type,
              style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600)),
          if (action.rationale.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(action.rationale,
                style: const TextStyle(color: AppColors.muted, fontSize: 11, height: 1.4)),
          ],
          const SizedBox(height: 8),
          if (!action.isPending)
            Text(
              action.status == 'CONFIRMED' ? 'Confirmée.' : 'Annulée.',
              style: const TextStyle(color: AppColors.muted, fontSize: 11),
            )
          else
            Row(
              children: [
                FilledButton(
                  onPressed: _pending ? null : () => _decide(true),
                  style: FilledButton.styleFrom(
                    visualDensity: VisualDensity.compact,
                  ),
                  child: const Text('Confirmer'),
                ),
                const SizedBox(width: 8),
                OutlinedButton(
                  onPressed: _pending ? null : () => _decide(false),
                  style: OutlinedButton.styleFrom(
                    visualDensity: VisualDensity.compact,
                  ),
                  child: const Text('Annuler'),
                ),
              ],
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
        12, 8, 12, 8 + MediaQuery.viewInsetsOf(context).bottom * 0,
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
                textInputAction: TextInputAction.send,
                onSubmitted: (_) => onSend(),
                decoration: const InputDecoration(
                  hintText: 'Écris à Leo…',
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
