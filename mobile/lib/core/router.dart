import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../features/auth/presentation/auth_controller.dart';
import '../features/auth/presentation/login_screen.dart';
import '../features/brokers/presentation/brokers_screen.dart';
import '../features/portfolio/presentation/portfolio_screen.dart';
import '../features/leo/presentation/leo_screen.dart';
import '../features/market/presentation/asset_detail_screen.dart';
import '../features/market/presentation/market_screen.dart';
import '../features/wallet/presentation/wallet_screen.dart';
import '../features/risk/presentation/risk_screen.dart';
import '../features/dashboard/presentation/dashboard_screen.dart';
import '../shared/widgets/app_shell.dart';

/// Écran d'attente pendant la reprise de session.
///
/// Distinct de l'écran de connexion : tant que la reprise n'a pas tranché,
/// afficher la connexion ferait clignoter l'application à chaque lancement
/// pour un utilisateur pourtant authentifié.
///
/// Il porte aussi le cas « serveur injoignable ». Ce cas n'est pas une
/// déconnexion : le jeton est intact, c'est le réseau qui manque. Demander
/// un mot de passe serait trompeur — il ne débloquerait rien.
class SplashScreen extends ConsumerWidget {
  const SplashScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final failure = ref.watch(
      authControllerProvider.select((state) => state.restoreFailure),
    );

    if (failure == null) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }

    return Scaffold(
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.cloud_off_outlined, size: 44),
              const SizedBox(height: 18),
              Text(
                'Session non reprise',
                style: Theme.of(context).textTheme.titleMedium,
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 8),
              Text(
                failure,
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodySmall,
              ),
              const SizedBox(height: 8),
              Text(
                'Ta connexion est conservée. Rien à ressaisir.',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodySmall,
              ),
              const SizedBox(height: 22),
              FilledButton.tonal(
                onPressed: () =>
                    ref.read(authControllerProvider.notifier).restore(),
                child: const Text('Réessayer'),
              ),
              TextButton(
                onPressed: () =>
                    ref.read(authControllerProvider.notifier).signOut(),
                child: const Text('Se connecter avec un autre compte'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

final _rootKey = GlobalKey<NavigatorState>();

final routerProvider = Provider<GoRouter>((ref) {
  final notifier = ValueNotifier<AuthState>(const AuthState());
  ref.listen<AuthState>(
    authControllerProvider,
    (_, next) => notifier.value = next,
    fireImmediately: true,
  );
  ref.onDispose(notifier.dispose);

  return GoRouter(
    navigatorKey: _rootKey,
    initialLocation: '/',
    refreshListenable: notifier,
    redirect: (context, state) {
      final auth = notifier.value;
      final atSplash = state.matchedLocation == '/demarrage';
      final atLogin = state.matchedLocation == '/connexion';

      // Tant que la reprise court — ou qu'elle a échoué faute de réseau,
      // jeton conservé — l'écran d'attente reste le bon : il explique et
      // propose de réessayer, là où l'écran de connexion mentirait sur la
      // cause.
      if (auth.restoring || auth.restoreUnavailable) {
        return atSplash ? null : '/demarrage';
      }
      if (!auth.isAuthenticated) return atLogin ? null : '/connexion';
      if (atLogin || atSplash) return '/';
      return null;
    },
    routes: [
      GoRoute(path: '/demarrage', builder: (_, __) => const SplashScreen()),
      GoRoute(path: '/connexion', builder: (_, __) => const LoginScreen()),

      // Hors de la coquille : écrans plein cadre, atteints depuis un écran
      // et quittés par un retour. Leur donner un onglet les mettrait au même
      // rang que le portefeuille, ce qu'ils ne sont pas.
      GoRoute(
        path: '/brokers',
        parentNavigatorKey: _rootKey,
        builder: (_, __) => const BrokersScreen(),
      ),
      GoRoute(
        path: '/leo',
        parentNavigatorKey: _rootKey,
        builder: (_, state) =>
            LeoScreen(fromPage: state.uri.queryParameters['depuis']),
      ),

      // La coquille : cinq destinations, chacune avec sa propre pile.
      //
      // `indexedStack` conserve l'état de chaque branche — position de
      // défilement, filtres de marché, portefeuille sélectionné. Repasser
      // par un onglet ne doit pas recharger ce qu'on y avait réglé.
      StatefulShellRoute.indexedStack(
        builder: (_, __, navigationShell) => AppShell(shell: navigationShell),
        branches: [
          StatefulShellBranch(routes: [
            GoRoute(path: '/', builder: (_, __) => const DashboardScreen()),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(
              path: '/portefeuille',
              builder: (_, __) => const PortfolioScreen(),
            ),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(
              path: '/marches',
              builder: (_, __) => const MarketScreen(),
              routes: [
                // Sous-route de l'onglet : la barre de navigation reste
                // visible sur le détail d'un instrument.
                GoRoute(
                  path: ':id',
                  builder: (_, state) => AssetDetailScreen(
                    assetId: int.tryParse(state.pathParameters['id'] ?? '') ?? 0,
                    symbol: state.uri.queryParameters['symbole'],
                  ),
                ),
              ],
            ),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(path: '/risque', builder: (_, __) => const RiskScreen()),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(
              path: '/portefeuille-electronique',
              builder: (_, __) => const WalletScreen(),
            ),
          ]),
        ],
      ),
    ],
  );
});
