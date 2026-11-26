import 'dart:async';
import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../../../core/config/env.dart';
import '../../auth/presentation/auth_controller.dart';
import '../domain/models.dart';

/// Marqueur du sous-protocole JWT — doit correspondre à core/ws_auth.py.
const String kJwtSubprotocol = 'leotrade.jwt';

/// Délais de reconnexion, en secondes. La dernière valeur est répétée.
const List<int> kReconnectDelays = [1, 2, 5, 10, 30];

/// Ouverture de la liaison, isolée derrière un provider.
///
/// Seule couture de test du protocole de Leo : c'est par cette socket que
/// transitent les confirmations d'opérations, donc le chemin qu'il faut
/// pouvoir éprouver sans serveur.
typedef LeoChannelFactory = WebSocketChannel Function(
  Uri uri,
  List<String> protocols,
);

final leoChannelFactoryProvider = Provider<LeoChannelFactory>(
  (_) => (uri, protocols) =>
      WebSocketChannel.connect(uri, protocols: protocols),
);

class LeoController extends AutoDisposeNotifier<LeoState> {
  WebSocketChannel? _channel;
  StreamSubscription<dynamic>? _subscription;
  Timer? _reconnect;
  int _attempts = 0;

  /// Vrai dès que le démontage a eu lieu : plus aucune reconnexion.
  bool _disposed = false;

  @override
  LeoState build() {
    ref.onDispose(_teardown);
    Future.microtask(connect);
    return const LeoState();
  }

  Future<void> connect() async {
    if (_disposed) return;
    _reconnect?.cancel();

    final authenticated = ref.read(authControllerProvider).isAuthenticated;
    if (!authenticated) {
      // Pas de reconnexion : rien ne changera tant que la session est
      // fermée, et réessayer en boucle masquerait la cause.
      state = state.copyWith(
        connection: LeoConnection.lost,
        thinking: false,
        error: 'Session fermée.',
      );
      return;
    }

    final token = ref.read(tokenStoreProvider).accessToken;
    if (token == null || token.isEmpty) {
      // Ouvrir une connexion vouée au refus produirait une boucle de
      // reconnexion silencieuse.
      state = state.copyWith(
        connection: LeoConnection.lost,
        thinking: false,
        error: 'Session expirée. Reconnecte-toi.',
      );
      return;
    }

    state = state.copyWith(connection: LeoConnection.connecting);

    final uri = Uri.parse('${Env.wsBaseUrl}/ws/assistant/chat/');
    try {
      // Le jeton voyage dans le sous-protocole, pas dans l'URL : une
      // chaîne de requête se retrouve dans les journaux d'accès du
      // serveur, des proxies et des CDN, bien au-delà de sa validité.
      final channel = ref.read(leoChannelFactoryProvider)(
        uri,
        [kJwtSubprotocol, token],
      );
      _channel = channel;
      _subscription = channel.stream.listen(
        _onMessage,
        onError: (_) => _onDisconnected('Connexion à Leo interrompue.'),
        onDone: () => _onDisconnected(null),
        cancelOnError: true,
      );
      _attempts = 0;
      state = state.copyWith(
        connection: LeoConnection.online,
        clearError: true,
      );
    } catch (_) {
      _onDisconnected('Impossible de joindre Leo.');
    }
  }

  /// La socket est tombée : l'annoncer, puis réessayer.
  ///
  /// Sans cela, l'en-tête restait sur « Connexion… » indéfiniment et le
  /// champ de saisie restait grisé : l'écran annonçait une reconnexion que
  /// personne ne tentait.
  void _onDisconnected(String? message) {
    _subscription?.cancel();
    _subscription = null;
    _channel = null;
    if (_disposed) return;

    state = state.copyWith(
      connection: LeoConnection.lost,
      thinking: false,
      error: message ?? state.error,
    );
    _scheduleReconnect();
  }

  void _scheduleReconnect() {
    _reconnect?.cancel();
    final index = _attempts < kReconnectDelays.length
        ? _attempts
        : kReconnectDelays.length - 1;
    _attempts++;
    _reconnect = Timer(
      Duration(seconds: kReconnectDelays[index]),
      () => connect(),
    );
  }

  /// Envoie un message. Retourne false si rien n'est parti.
  ///
  /// Le booléen existe pour que l'écran garde le texte saisi : l'effacer
  /// après un envoi qui n'a pas eu lieu perd la question sans le dire.
  bool send(String text, {String? page}) {
    final trimmed = text.trim();
    if (trimmed.isEmpty) return false;

    final channel = _channel;
    if (channel == null || state.connection != LeoConnection.online) {
      // Écrire dans un sink fermé ne lève pas toujours : le message
      // s'affichait comme envoyé et n'arrivait jamais.
      state = state.copyWith(
        error: 'Leo est hors ligne. Ton message n\'a pas été envoyé.',
      );
      return false;
    }

    try {
      channel.sink.add(jsonEncode({
        'type': 'chat',
        'message': trimmed,
        // L'écran courant permet à Leo de commenter ce que l'utilisateur a
        // sous les yeux plutôt que de demander de quoi on parle.
        if (page != null) 'context': {'page': page},
      }));
    } catch (_) {
      _onDisconnected('Leo est hors ligne. Ton message n\'a pas été envoyé.');
      return false;
    }

    state = state.copyWith(
      turns: [
        ...state.turns,
        LeoTurn(
          id: 'local-${DateTime.now().microsecondsSinceEpoch}',
          role: LeoRole.user,
          content: trimmed,
        ),
      ],
      clearError: true,
    );
    return true;
  }

  void _onMessage(dynamic raw) {
    Map<String, dynamic> event;
    try {
      event = jsonDecode(raw as String) as Map<String, dynamic>;
    } catch (_) {
      // Un message illisible ne doit pas faire tomber la conversation.
      return;
    }

    switch (event['type'] as String?) {
      case 'session':
        final history = event['history'];
        state = state.copyWith(
          turns: history is List
              ? history
                  .whereType<Map<String, dynamic>>()
                  .map(LeoTurn.fromJson)
                  .where((turn) => turn.role != LeoRole.system)
                  .toList(growable: false)
              : const [],
          clearError: true,
        );
      case 'thinking':
        state = state.copyWith(thinking: true);
      case 'chunk':
        _appendChunk('${event['id']}', event['text'] as String? ?? '');
      case 'done':
        _finishTurn(
          '${event['id']}',
          event['actions'],
          fallbackContent: event['clean_content'] as String?,
          rawRequest: event['action_request'],
        );
      case 'action_update':
        _updateAction(event['action_id'] as int?, event['status'] as String?);
      case 'error':
        state = state.copyWith(
          thinking: false,
          error: event['message'] as String? ?? 'Erreur de l\'assistant.',
        );
      default:
        break;
    }
  }

  void _appendChunk(String id, String text) {
    final turns = [...state.turns];
    final index = turns.indexWhere((turn) => turn.id == id);
    if (index >= 0) {
      turns[index] = turns[index].copyWith(content: turns[index].content + text);
    } else {
      turns.add(LeoTurn(
        id: id,
        role: LeoRole.assistant,
        content: text,
        streaming: true,
      ));
    }
    state = state.copyWith(turns: turns, thinking: false);
  }

  void _finishTurn(
    String id,
    dynamic rawActions, {
    String? fallbackContent,
    dynamic rawRequest,
  }) {
    final actions = rawActions is List
        ? rawActions
            .whereType<Map<String, dynamic>>()
            .map(LeoAction.fromJson)
            .toList(growable: false)
        : const <LeoAction>[];

    final request = rawRequest is Map<String, dynamic>
        ? LeoActionRequest.fromJson(rawRequest)
        : null;

    final turns = [...state.turns];
    final index = turns.indexWhere((turn) => turn.id == id);

    if (index >= 0) {
      turns[index] = turns[index].copyWith(actions: actions, streaming: false);
    } else if ((fallbackContent ?? '').isNotEmpty) {
      // `done` sans `chunk` préalable : c'est ainsi que le serveur renvoie
      // le résultat d'un outil — y compris la confirmation d'une opération.
      // Sans ce repli, la réponse disparaissait sans un mot.
      turns.add(LeoTurn(
        id: id,
        role: LeoRole.assistant,
        content: fallbackContent!,
        actions: actions,
      ));
    }

    state = state.copyWith(
      thinking: false,
      turns: turns,
      actionRequest: request,
      // Une demande tranchée ne doit plus proposer de boutons.
      clearActionRequest: request == null ||
          (!request.isActionable && !request.awaitsSecondConfirmation),
    );
  }

  void _updateAction(int? actionId, String? status) {
    if (actionId == null || status == null) return;
    state = state.copyWith(
      turns: state.turns
          .map((turn) => turn.copyWith(
                actions: turn.actions
                    .map((action) => action.id == actionId
                        ? LeoAction(
                            id: action.id,
                            type: action.type,
                            status: status,
                            rationale: action.rationale,
                          )
                        : action)
                    .toList(growable: false),
              ))
          .toList(growable: false),
    );
  }

  /// Tranche une PROPOSITION attachée à un message (`AssistantAction`).
  ///
  /// Passe par la socket, qui est le canal prévu pour ce modèle. L'ancienne
  /// version postait l'identifiant sur `/assistant/action-requests/<id>/`,
  /// l'endpoint d'un AUTRE modèle (`AssistantActionRequest`) : deux
  /// séquences de clés primaires distinctes. Soit rien ne correspondait et
  /// le bouton était mort, soit une demande de l'utilisateur portait le
  /// même numéro — et c'est elle qui était confirmée et exécutée.
  ///
  /// Le statut n'est plus forcé localement : il est attendu du serveur via
  /// `action_update`. Afficher « Confirmée » sans l'avoir obtenu est, sur
  /// une action qui engage de l'argent, pire qu'une erreur.
  bool decideAction(int actionId, {required bool confirm}) =>
      _emit(confirm ? 'action_confirm' : 'action_reject', {
        'action_id': actionId,
      });

  /// Tranche une DEMANDE transactionnelle (`AssistantActionRequest`),
  /// celle que le Risk Engine met en attente.
  bool decideActionRequest(int requestId, {required bool confirm}) => _emit(
        confirm ? 'action_request_confirm' : 'action_request_cancel',
        {'request_id': requestId},
      );

  bool _emit(String type, Map<String, dynamic> payload) {
    final channel = _channel;
    if (channel == null || state.connection != LeoConnection.online) {
      state = state.copyWith(
        error: 'Leo est hors ligne : la décision n\'a pas été transmise.',
      );
      return false;
    }
    try {
      channel.sink.add(jsonEncode({'type': type, ...payload}));
      return true;
    } catch (_) {
      _onDisconnected('La décision n\'a pas été transmise.');
      return false;
    }
  }

  void _teardown() {
    _disposed = true;
    _reconnect?.cancel();
    _reconnect = null;
    _subscription?.cancel();
    _channel?.sink.close();
    _subscription = null;
    _channel = null;
  }
}

final leoControllerProvider =
    AutoDisposeNotifierProvider<LeoController, LeoState>(LeoController.new);
