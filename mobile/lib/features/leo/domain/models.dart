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

/// État de la conversation en cours.
class LeoState {
  const LeoState({
    this.turns = const [],
    this.connected = false,
    this.thinking = false,
    this.error,
  });

  final List<LeoTurn> turns;
  final bool connected;
  final bool thinking;
  final String? error;

  LeoState copyWith({
    List<LeoTurn>? turns,
    bool? connected,
    bool? thinking,
    String? error,
    bool clearError = false,
  }) =>
      LeoState(
        turns: turns ?? this.turns,
        connected: connected ?? this.connected,
        thinking: thinking ?? this.thinking,
        error: clearError ? null : (error ?? this.error),
      );
}
