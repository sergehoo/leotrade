import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../features/auth/presentation/auth_controller.dart';
import '../features/auth/presentation/login_screen.dart';
import '../features/brokers/presentation/brokers_screen.dart';
import '../features/portfolio/presentation/portfolio_screen.dart';
import '../features/leo/presentation/leo_screen.dart';
import '../features/risk/presentation/risk_screen.dart';
import '../features/dashboard/presentation/dashboard_screen.dart';

/// Écran d'attente pendant la reprise de session.
///
/// Distinct de l'écran de connexion : tant que la reprise n'a pas tranché,
/// afficher la connexion ferait clignoter l'application à chaque lancement
/// pour un utilisateur pourtant authentifié.
class _SplashScreen extends StatelessWidget {
  const _SplashScreen();

  @override
  Widget build(BuildContext context) =>
      const Scaffold(body: Center(child: CircularProgressIndicator()));
}

final routerProvider = Provider<GoRouter>((ref) {
  final notifier = ValueNotifier<AuthState>(const AuthState());
  ref.listen<AuthState>(
    authControllerProvider,
    (_, next) => notifier.value = next,
    fireImmediately: true,
  );
  ref.onDispose(notifier.dispose);

  return GoRouter(
    initialLocation: '/',
    refreshListenable: notifier,
    redirect: (context, state) {
      final auth = notifier.value;
      final atSplash = state.matchedLocation == '/demarrage';
      final atLogin = state.matchedLocation == '/connexion';

      if (auth.restoring) return atSplash ? null : '/demarrage';
      if (!auth.isAuthenticated) return atLogin ? null : '/connexion';
      if (atLogin || atSplash) return '/';
      return null;
    },
    routes: [
      GoRoute(path: '/demarrage', builder: (_, __) => const _SplashScreen()),
      GoRoute(path: '/connexion', builder: (_, __) => const LoginScreen()),
      GoRoute(path: '/', builder: (_, __) => const DashboardScreen()),
      GoRoute(path: '/brokers', builder: (_, __) => const BrokersScreen()),
      GoRoute(path: '/portefeuille', builder: (_, __) => const PortfolioScreen()),
      GoRoute(path: '/risque', builder: (_, __) => const RiskScreen()),
      GoRoute(
        path: '/leo',
        builder: (_, state) => LeoScreen(fromPage: state.uri.queryParameters['depuis']),
      ),
    ],
  );
});
