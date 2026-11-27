import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/realtime.dart';
import '../../auth/presentation/auth_controller.dart';
import '../domain/models.dart';

class LeoController extends AutoDisposeNotifier<LeoState> {
  RealtimeConnection? _link;

  @override
  LeoState build() {
    ref.onDispose(() => _link?.dispose());
    Future.microtask(connect);
    return const LeoState();
  }

  Future<void> connect() async {
    if (!ref.read(authControllerProvider).isAuthenticated) {
      // Pas de reconnexion : rien ne changera tant que la session est
      // fermée, et réessayer en boucle masquerait la cause.
      state = state.copyWith(
        connection: LeoConnection.lost,
        thinking: false,
        error: 'Session fermée.',
      );
      return;
    }

    _link?.dispose();
    _link = RealtimeConnection(
      path: '/ws/assistant/chat/',
      connect: ref.read(realtimeChannelFactoryProvider),
      accessToken: () => ref.read(tokenStoreProvider).accessToken,
      onStatus: _onStatus,
      onMessage: _onMessage,
    )..open();
  }

  void _onStatus(RealtimeStatus status, String? error) {
    state = state.copyWith(
      connection: switch (status) {
        RealtimeStatus.connecting => LeoConnection.connecting,
        RealtimeStatus.online => LeoConnection.online,
        RealtimeStatus.lost => LeoConnection.lost,
      },
      thinking: status == RealtimeStatus.online ? state.thinking : false,
      error: error,
      clearError: status == RealtimeStatus.online && error == null,
    );
  }

  /// Envoie un message. Retourne false si rien n'est parti.
  ///
  /// Le booléen existe pour que l'écran garde le texte saisi : l'effacer
  /// après un envoi qui n'a pas eu lieu perd la question sans le dire.
  bool send(String text, {String? page}) {
    final trimmed = text.trim();
    if (trimmed.isEmpty) return false;

    final sent = _push(
      {
        'type': 'chat',
        'message': trimmed,
        // L'écran courant permet à Leo de commenter ce que l'utilisateur
        // a sous les yeux plutôt que de demander de quoi on parle.
        if (page != null) 'context': {'page': page},
      },
      offline: 'Leo est hors ligne. Ton message n\'a pas été envoyé.',
    );
    if (!sent) return false;

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

  void _onMessage(Map<String, dynamic> event) {
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

  bool _emit(String type, Map<String, dynamic> payload) => _push(
        {'type': type, ...payload},
        offline: 'Leo est hors ligne : la décision n\'a pas été transmise.',
      );

  /// Envoie, ou dit pourquoi il n'a pas envoyé.
  ///
  /// Écrire dans un sink fermé ne lève pas toujours : sans ce verrou, le
  /// message s'afficherait comme parti et n'arriverait jamais.
  bool _push(Map<String, dynamic> message, {required String offline}) {
    if (_link?.isOpen != true ||
        state.connection != LeoConnection.online ||
        !_link!.send(message)) {
      state = state.copyWith(error: offline);
      return false;
    }
    return true;
  }
}

final leoControllerProvider =
    AutoDisposeNotifierProvider<LeoController, LeoState>(LeoController.new);
