// Modèles de Leo, alignés sur ai_assistant/serializers_api.py et sur le
// protocole WebSocket décrit en tête de ai_assistant/consumers.py.

enum LeoRole { user, assistant, system }

LeoRole leoRoleFrom(String? raw) => switch (raw) {
      'USER' => LeoRole.user,
      'SYSTEM' => LeoRole.system,
      _ => LeoRole.assistant,
    };

/// Action proposée par Leo. Rien n'est exécuté sans confirmation : la
/// présence de cet objet signifie « l'assistant propose », jamais
/// « l'assistant a fait ».
class LeoAction {
  const LeoAction({
    required this.id,
    required this.type,
    required this.status,
    required this.rationale,
  });

  factory LeoAction.fromJson(Map<String, dynamic> json) => LeoAction(
        id: json['id'] as int,
        type: json['type'] as String? ?? json['action_type'] as String? ?? '',
        status: json['status'] as String? ?? 'PENDING',
        rationale: json['rationale'] as String? ?? '',
      );

  final int id;
  final String type;
  final String status;
  final String rationale;

  /// Une action non tranchée attend une décision de l'utilisateur.
  bool get isPending => status == 'PENDING' || status == 'PROPOSED';
}

class LeoTurn {
  const LeoTurn({
    required this.id,
    required this.role,
    required this.content,
    this.actions = const [],
    this.streaming = false,
  });

  factory LeoTurn.fromJson(Map<String, dynamic> json) {
    final rawActions = json['actions'];
    return LeoTurn(
      id: '${json['id']}',
      role: leoRoleFrom(json['role'] as String?),
      content: json['content'] as String? ?? '',
      actions: rawActions is List
          ? rawActions
              .whereType<Map<String, dynamic>>()
              .map(LeoAction.fromJson)
              .toList(growable: false)
          : const [],
    );
  }

  final String id;
  final LeoRole role;
  final String content;
  final List<LeoAction> actions;
  final bool streaming;

  bool get isUser => role == LeoRole.user;

  LeoTurn copyWith({
    String? content,
    List<LeoAction>? actions,
    bool? streaming,
  }) =>
      LeoTurn(
        id: id,
        role: role,
        content: content ?? this.content,
        actions: actions ?? this.actions,
        streaming: streaming ?? this.streaming,
      );
}

/// État de la liaison temps réel avec Leo.
///
/// Trois états et non deux : « en cours de connexion » et « connexion
/// perdue » se ressemblaient à l'écran sous un seul libellé « Connexion… ».
/// Après une coupure, l'en-tête annonçait donc indéfiniment une connexion
/// en cours pendant que rien ne se reconnectait, et le bouton d'envoi
/// restait grisé sans explication.
enum LeoConnection { connecting, online, lost }

/// Demande de confirmation TRANSACTIONNELLE, passée par le Risk Engine.
///
/// À ne pas confondre avec [LeoAction], qui est une simple proposition
/// attachée à un message. Ce sont deux modèles côté serveur,
/// `AssistantActionRequest` et `AssistantAction`, avec deux séquences
/// d'identifiants distinctes — les confondre fait confirmer une opération
/// que l'utilisateur n'a pas regardée.
class LeoActionRequest {
  const LeoActionRequest({
    required this.id,
    required this.actionType,
    required this.status,
    required this.mode,
    required this.summary,
    required this.riskSummary,
    required this.requiresDoubleConfirmation,
    required this.confirmationsReceived,
    required this.errorMessage,
  });

  factory LeoActionRequest.fromJson(Map<String, dynamic> json) =>
      LeoActionRequest(
        id: json['id'] as int,
        actionType: json['action_type'] as String? ?? '',
        status: json['status'] as String? ?? 'WAITING',
        mode: json['mode'] as String? ?? '',
        summary: json['summary'] as String? ?? '',
        riskSummary: json['risk_summary'] as String? ?? '',
        requiresDoubleConfirmation:
            json['requires_double_confirmation'] == true,
        confirmationsReceived: json['confirmations_received'] as int? ?? 0,
        errorMessage: json['error_message'] as String? ?? '',
      );

  final int id;
  final String actionType;
  final String status;

  /// PAPER ou LIVE. En LIVE, c'est de l'argent réel qui part.
  final String mode;
  final String summary;
  final String riskSummary;
  final bool requiresDoubleConfirmation;
  final int confirmationsReceived;
  final String errorMessage;

  bool get isLive => mode == 'LIVE';

  /// Une demande tranchée ne propose plus rien.
  bool get isActionable => status == 'WAITING' || status == 'PENDING';

  /// Seconde confirmation attendue : le serveur en exige deux en LIVE.
  bool get awaitsSecondConfirmation =>
      requiresDoubleConfirmation && confirmationsReceived < 2;
}

/// État de la conversation en cours.
class LeoState {
  const LeoState({
    this.turns = const [],
    this.connection = LeoConnection.connecting,
    this.thinking = false,
    this.error,
    this.actionRequest,
  });

  final List<LeoTurn> turns;
  final LeoConnection connection;
  final bool thinking;
  final String? error;

  /// Dernière demande de confirmation transactionnelle reçue du serveur.
  final LeoActionRequest? actionRequest;

  bool get connected => connection == LeoConnection.online;

  LeoState copyWith({
    List<LeoTurn>? turns,
    LeoConnection? connection,
    bool? thinking,
    String? error,
    LeoActionRequest? actionRequest,
    bool clearError = false,
    bool clearActionRequest = false,
  }) =>
      LeoState(
        turns: turns ?? this.turns,
        connection: connection ?? this.connection,
        thinking: thinking ?? this.thinking,
        error: clearError ? null : (error ?? this.error),
        actionRequest: clearActionRequest
            ? null
            : (actionRequest ?? this.actionRequest),
      );
}
