import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../../auth/presentation/auth_controller.dart';

/// Contexte applicatif (GET /api/v1/context/).
///
/// Le mode de trading vient du serveur, dérivé des comptes broker. Il n'est
/// jamais stocké comme préférence locale : un client qui affiche « simulation »
/// pendant que le broker est en réel conduit à engager de l'argent par erreur.
class AppContext {
  const AppContext({
    required this.tradingMode,
    required this.configuredTradingMode,
    required this.liveBlockedReason,
    required this.tradingEnabled,
    required this.portfolio,
    required this.wallet,
  });

  factory AppContext.fromJson(Map<String, dynamic> json) => AppContext(
        tradingMode: json['trading_mode'] as String? ?? 'PAPER',
        // Repli sur le mode effectif : un serveur plus ancien n'envoie pas
        // ce champ, et supposer LIVE serait le mauvais côté de l'erreur.
        configuredTradingMode:
            json['configured_trading_mode'] as String? ??
                json['trading_mode'] as String? ??
                'PAPER',
        liveBlockedReason: json['live_blocked_reason'] as String? ?? '',
        tradingEnabled: json['trading_enabled'] as bool? ?? false,
        portfolio: json['portfolio'] is Map<String, dynamic>
            ? ContextPortfolio.fromJson(json['portfolio'] as Map<String, dynamic>)
            : null,
        wallet: json['wallet'] is Map<String, dynamic>
            ? ContextWallet.fromJson(json['wallet'] as Map<String, dynamic>)
            : null,
      );

  final String tradingMode;

  /// Mode demandé sur les comptes broker. Diffère de [tradingMode] quand un
  /// blocage serveur rend l'exécution réelle impossible.
  final String configuredTradingMode;

  /// Motif du blocage (`KYC_REQUIRED`), ou chaîne vide.
  final String liveBlockedReason;

  final bool tradingEnabled;
  final ContextPortfolio? portfolio;
  final ContextWallet? wallet;

  bool get isLive => tradingMode == 'LIVE';

  /// Le mode réel a été demandé mais le serveur le refuse. L'interface doit
  /// l'annoncer : laisser croire que la configuration a été ignorée sans
  /// raison est aussi trompeur qu'afficher « Mode réel » à tort.
  bool get isLiveDowngraded =>
      !isLive && configuredTradingMode == 'LIVE';
}

class ContextPortfolio {
  const ContextPortfolio({
    required this.id,
    required this.name,
    required this.baseCurrency,
    required this.currentBalance,
    required this.availableCash,
    required this.lockedCash,
    required this.isActive,
    required this.brokerLabel,
  });

  factory ContextPortfolio.fromJson(Map<String, dynamic> json) {
    final broker = json['broker_account'];
    return ContextPortfolio(
      id: json['id'] as int,
      name: json['name'] as String? ?? '',
      baseCurrency: json['base_currency'] as String? ?? 'USD',
      // Montants conservés en String : voir core/format.dart.
      currentBalance: '${json['current_balance'] ?? ''}',
      availableCash: '${json['available_cash'] ?? ''}',
      lockedCash: '${json['locked_cash'] ?? ''}',
      isActive: json['is_active'] as bool? ?? false,
      brokerLabel: broker is Map<String, dynamic>
          ? '${broker['broker']} · ${broker['name']}'
          : null,
    );
  }

  final int id;
  final String name;
  final String baseCurrency;
  final String currentBalance;
  final String availableCash;
  final String lockedCash;
  final bool isActive;
  final String? brokerLabel;
}

class ContextWallet {
  const ContextWallet({
    required this.currency,
    required this.availableBalance,
    required this.lockedBalance,
  });

  factory ContextWallet.fromJson(Map<String, dynamic> json) => ContextWallet(
        currency: json['currency'] as String? ?? 'USD',
        availableBalance: '${json['available_balance'] ?? ''}',
        lockedBalance: '${json['locked_balance'] ?? ''}',
      );

  final String currency;
  final String availableBalance;
  final String lockedBalance;
}

final appContextProvider = FutureProvider.autoDispose<AppContext>((ref) async {
  // Rattaché à l'authentification : une déconnexion invalide le contexte,
  // qui ne doit jamais rester affiché avec les données du compte précédent.
  final authenticated = ref.watch(
    authControllerProvider.select((state) => state.isAuthenticated),
  );
  if (!authenticated) throw const ApiError('Session fermée.');

  final client = ref.watch(apiClientProvider);
  return AppContext.fromJson(await client.get<Map<String, dynamic>>('/context/'));
});
