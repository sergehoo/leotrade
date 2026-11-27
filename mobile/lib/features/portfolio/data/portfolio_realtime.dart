import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/realtime.dart';
import '../../auth/presentation/auth_controller.dart';

/// Correctif reçu en direct pour une position.
///
/// Chaque champ est nullable et n'est renseigné que si le serveur l'a
/// envoyé. Rien n'est complété, rien n'est déduit : un champ absent
/// laisse la valeur chargée en REST intacte, au lieu de la remplacer par
/// un zéro qui passerait pour une mesure.
class LivePosition {
  const LivePosition({
    required this.id,
    this.markPrice,
    this.unrealizedPnl,
    this.quantity,
  });

  factory LivePosition.fromJson(Map<String, dynamic> json) => LivePosition(
        id: json['id'] as int,
        markPrice: _text(json['mark_price']),
        unrealizedPnl: _text(json['unrealized_pnl']),
        quantity: _text(json['quantity']),
      );

  final int id;

  /// Montants en chaîne : calculés en Decimal côté serveur.
  final String? markPrice;
  final String? unrealizedPnl;
  final String? quantity;
}

/// Correctif reçu en direct pour la synthèse du portefeuille.
class LiveMetrics {
  const LiveMetrics({
    this.equity,
    this.availableCash,
    this.lockedCash,
    this.unrealizedPnl,
    this.realizedPnl,
  });

  factory LiveMetrics.fromJson(Map<String, dynamic> json) => LiveMetrics(
        equity: _text(json['equity']),
        availableCash: _text(json['available_cash']),
        lockedCash: _text(json['locked_cash']),
        unrealizedPnl: _text(json['unrealized_pnl']),
        realizedPnl: _text(json['realized_pnl']),
      );

  final String? equity;
  final String? availableCash;
  final String? lockedCash;
  final String? unrealizedPnl;
  final String? realizedPnl;
}

String? _text(Object? value) {
  if (value == null) return null;
  final text = '$value'.trim();
  return text.isEmpty ? null : text;
}

/// Ce que la liaison temps réel sait du portefeuille.
///
/// `lastEventAt` est aussi important que les chiffres : une liaison
/// ouverte qui ne reçoit rien ressemble, à l'écran, à une liaison qui
/// tient les prix à jour. Sur une plateforme de trading, croire qu'un
/// chiffre est courant alors qu'il date de l'ouverture de l'écran est
/// précisément l'erreur qu'on ne peut pas se permettre.
class PortfolioLive {
  const PortfolioLive({
    this.status = RealtimeStatus.connecting,
    this.positions = const {},
    this.metrics,
    this.lastEventAt,
    this.error,
  });

  final RealtimeStatus status;

  /// Correctifs de position, indexés par identifiant.
  final Map<int, LivePosition> positions;

  final LiveMetrics? metrics;

  /// Horodatage du dernier message REÇU — pas de la connexion.
  final DateTime? lastEventAt;

  final String? error;

  bool get isOnline => status == RealtimeStatus.online;

  /// Vrai quand la liaison tient mais que rien n'est encore arrivé.
  ///
  /// L'état normal en l'absence de producteur : le mark-to-market
  /// périodique est une tâche Celery, et les autres émetteurs ne parlent
  /// qu'au moment d'un ordre ou d'un recalcul.
  bool get isSilent => isOnline && lastEventAt == null;

  PortfolioLive copyWith({
    RealtimeStatus? status,
    Map<int, LivePosition>? positions,
    LiveMetrics? metrics,
    DateTime? lastEventAt,
    String? error,
    bool clearError = false,
  }) =>
      PortfolioLive(
        status: status ?? this.status,
        positions: positions ?? this.positions,
        metrics: metrics ?? this.metrics,
        lastEventAt: lastEventAt ?? this.lastEventAt,
        error: clearError ? null : (error ?? this.error),
      );
}

/// Liaison temps réel d'un portefeuille — `ws/portfolio/<id>/`.
///
/// Le canal existait côté serveur depuis l'origine, avec ses émetteurs :
/// `execution/outbox.py` au passage d'un ordre,
/// `PortfolioService.refresh_portfolio_metrics` après un recalcul,
/// `update_marks_task` pour le mark-to-market périodique. Aucun des deux
/// clients ne s'y connectait.
///
/// Les données REST restent la source : la socket ne fait que CORRIGER
/// des champs déjà chargés. Elle n'en fabrique aucun.
class PortfolioRealtime extends AutoDisposeFamilyNotifier<PortfolioLive, int> {
  RealtimeConnection? _link;

  @override
  PortfolioLive build(int portfolioId) {
    ref.onDispose(() => _link?.dispose());

    if (!ref.watch(
      authControllerProvider.select((state) => state.isAuthenticated),
    )) {
      return const PortfolioLive(
        status: RealtimeStatus.lost,
        error: 'Session fermée.',
      );
    }

    Future.microtask(() => _open(portfolioId));
    return const PortfolioLive();
  }

  void _open(int portfolioId) {
    _link?.dispose();
    _link = RealtimeConnection(
      path: '/ws/portfolio/$portfolioId/',
      connect: ref.read(realtimeChannelFactoryProvider),
      accessToken: () => ref.read(tokenStoreProvider).accessToken,
      onStatus: (status, error) => state = state.copyWith(
        status: status,
        error: error,
        clearError: status == RealtimeStatus.online && error == null,
      ),
      onMessage: _onMessage,
    )..open();
  }

  void _onMessage(Map<String, dynamic> message) {
    final payload = message['payload'];
    if (payload is! Map<String, dynamic>) return;

    switch (message['event'] as String?) {
      case 'connection.established':
        // La poignée de main n'est pas une mesure : elle ne compte pas
        // comme « dernière mise à jour ».
        break;

      case 'position.update':
        final raw = payload['position'];
        if (raw is! Map<String, dynamic> || raw['id'] is! int) return;
        final patch = LivePosition.fromJson(raw);
        state = state.copyWith(
          positions: {...state.positions, patch.id: patch},
          lastEventAt: DateTime.now(),
        );

      case 'portfolio.update':
        _onPortfolioUpdate(payload);

      default:
        break;
    }
  }

  void _onPortfolioUpdate(Map<String, dynamic> payload) {
    switch (payload['kind'] as String?) {
      case 'metrics_refresh':
        state = state.copyWith(
          metrics: LiveMetrics.fromJson(payload),
          lastEventAt: DateTime.now(),
        );

      case 'positions_snapshot':
        final raw = payload['positions'];
        if (raw is! List) return;
        final patches = <int, LivePosition>{};
        for (final entry in raw.whereType<Map<String, dynamic>>()) {
          if (entry['id'] is! int) continue;
          final patch = LivePosition.fromJson(entry);
          patches[patch.id] = patch;
        }
        state = state.copyWith(
          positions: patches,
          lastEventAt: DateTime.now(),
        );

      default:
        // Un événement d'une autre forme — un ordre passé, un instantané
        // créé — vaut quand même comme signe de vie, mais ne corrige
        // aucun chiffre : l'écran se rechargera par les providers REST.
        state = state.copyWith(lastEventAt: DateTime.now());
    }
  }
}

final portfolioRealtimeProvider = AutoDisposeNotifierProviderFamily<
    PortfolioRealtime, PortfolioLive, int>(PortfolioRealtime.new);
