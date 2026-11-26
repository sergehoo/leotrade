import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

/// Accès à Leo depuis n'importe quel écran.
///
/// Leo sert à commenter ce que l'utilisateur regarde ; l'enfermer dans un
/// onglet obligerait à quitter l'écran dont on veut parler. Le chemin
/// courant lui est transmis comme contexte.
class LeoFab extends StatelessWidget {
  const LeoFab({super.key, required this.page});

  /// Écran d'où part la conversation, repris dans le contexte du message.
  final String page;

  @override
  Widget build(BuildContext context) {
    return FloatingActionButton.extended(
      heroTag: 'leo-$page',
      onPressed: () => context.push('/leo?depuis=$page'),
      icon: const Icon(Icons.smart_toy_outlined),
      label: const Text('Leo'),
    );
  }
}
