import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

/// Coquille de navigation.
///
/// Avant elle, sept `IconButton` dans la barre du tableau de bord étaient le
/// seul chemin vers quoi que ce soit : chaque écran était un cul-de-sac, et
/// passer des marchés au risque demandait un retour. Sur un écran de 360
/// points, sept actions ne laissaient aucune place au titre.
///
/// Cinq destinations, pas sept : Leo vit dans un bouton flottant — il sert à
/// commenter l'écran courant, l'enfermer dans un onglet obligerait à quitter
/// celui dont on veut parler — et les brokers sont un écran de configuration,
/// atteint depuis le tableau de bord.
class AppShell extends StatelessWidget {
  const AppShell({super.key, required this.shell});

  final StatefulNavigationShell shell;

  static const _destinations = <_Destination>[
    _Destination('Tableau de bord', Icons.space_dashboard_outlined,
        Icons.space_dashboard),
    _Destination('Portefeuille', Icons.work_outline, Icons.work),
    _Destination('Marchés', Icons.show_chart, Icons.show_chart),
    _Destination('Risque', Icons.shield_outlined, Icons.shield),
    _Destination('Compte', Icons.account_balance_wallet_outlined,
        Icons.account_balance_wallet),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: shell,
      bottomNavigationBar: NavigationBar(
        selectedIndex: shell.currentIndex,
        // `initialLocation: true` quand on retouche l'onglet courant : c'est
        // le geste attendu pour revenir en tête de pile depuis le détail
        // d'un instrument.
        onDestinationSelected: (index) => shell.goBranch(
          index,
          initialLocation: index == shell.currentIndex,
        ),
        destinations: [
          for (final d in _destinations)
            NavigationDestination(
              icon: Icon(d.icon),
              selectedIcon: Icon(d.selectedIcon),
              label: d.label,
              // Le libellé est toujours affiché sous l'icône ; l'étiquette
              // sémantique répète le nom complet pour les lecteurs d'écran,
              // « Compte » seul étant ambigu à l'oreille.
              tooltip: d.label,
            ),
        ],
      ),
    );
  }
}

class _Destination {
  const _Destination(this.label, this.icon, this.selectedIcon);
  final String label;
  final IconData icon;
  final IconData selectedIcon;
}
