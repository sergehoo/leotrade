import 'dart:async';
import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../../../core/config/env.dart';
import '../../../core/network/api_client.dart';
import '../../auth/presentation/auth_controller.dart';
import '../domain/models.dart';

/// Marqueur du sous-protocole JWT — doit correspondre à core/ws_auth.py.
const String kJwtSubprotocol = 'leotrade.jwt';

class LeoController extends AutoDisposeNotifier<LeoState> {
  WebSocketChannel? _channel;
  StreamSubscription<dynamic>? _subscription;

  @override
  LeoState build() {
    ref.onDispose(_teardown);
    Future.microtask(connect);
    return const LeoState();
  }

  Future<void> connect() async {
    final authenticated = ref.read(authControllerProvider).isAuthenticated;
    if (!authenticated) {
      state = state.copyWith(error: 'Session fermée.');
      return;
    }

    final token = ref.read(tokenStoreProvider).accessToken;
    if (token == null || token.isEmpty) {
      // Ouvrir une connexion vouée au refus produirait une boucle de
      // reconnexion silencieuse.
      state = state.copyWith(error: 'Session expirée. Reconnecte-toi.');
      return;
    }

    final uri = Uri.parse('${Env.wsBaseUrl}/ws/assistant/chat/');
    try {
      // Le jeton voyage dans le sous-protocole, pas dans l'URL : une
      // chaîne de requête se retrouve dans les journaux d'accès du
      // serveur, des proxies et des CDN, bien au-delà de sa validité.
      final channel = WebSocketChannel.connect(
        uri,
        protocols: [kJwtSubprotocol, token],
      );
      _channel = channel;
      _subscription = channel.stream.listen(
        _onMessage,
        onError: (_) => state = state.copyWith(
          connected: false,
          thinking: false,
          error: 'Connexion à Leo interrompue.',
        ),
        onDone: () => state = state.copyWith(connected: false, thinking: false),
      );
      state = state.copyWith(connected: true, clearError: true);
    } catch (_) {
      state = state.copyWith(error: 'Impossible de joindre Leo.');
    }
  }

  void send(String text, {String? page}) {
    final trimmed = text.trim();
    final channel = _channel;
    if (trimmed.isEmpty || channel == null) return;

    channel.sink.add(jsonEncode({
      'type': 'chat',
      'message': trimmed,
      // L'écran courant permet à Leo de commenter ce que l'utilisateur a
      // sous les yeux plutôt que de demander de quoi on parle.
      if (page != null) 'context': {'page': page},
    }));

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
        _finishTurn('${event['id']}', event['actions']);
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

  void _finishTurn(String id, dynamic rawActions) {
    final actions = rawActions is List
        ? rawActions
            .whereType<Map<String, dynamic>>()
            .map(LeoAction.fromJson)
            .toList(growable: false)
        : const <LeoAction>[];

    state = state.copyWith(
      thinking: false,
      turns: state.turns
          .map((turn) => turn.id == id
              ? turn.copyWith(actions: actions, streaming: false)
              : turn)
          .toList(growable: false),
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

  Future<void> decideAction(int actionId, {required bool confirm}) async {
    final client = ref.read(apiClientProvider);
    final suffix = confirm ? 'confirm' : 'cancel';
    try {
      await client.post<Map<String, dynamic>>(
        '/assistant/action-requests/$actionId/$suffix/',
      );
      _updateAction(actionId, confirm ? 'CONFIRMED' : 'REJECTED');
    } on ApiError catch (error) {
      state = state.copyWith(error: error.message);
    }
  }

  void _teardown() {
    _subscription?.cancel();
    _channel?.sink.close();
    _subscription = null;
    _channel = null;
  }
}

final leoControllerProvider =
    AutoDisposeNotifierProvider<LeoController, LeoState>(LeoController.new);
