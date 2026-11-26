import 'package:flutter_test/flutter_test.dart';
import 'package:leotrade/features/leo/domain/models.dart';

void main() {
  group('LeoAction', () {
    test('une action non tranchée attend une décision', () {
      // Tant qu'elle est en attente, rien n'a été exécuté : l'assistant
      // propose, il ne dispose pas.
      for (final status in ['PENDING', 'PROPOSED']) {
        final action = LeoAction.fromJson({
          'id': 1, 'type': 'OPEN_POSITION', 'status': status, 'rationale': '',
        });
        expect(action.isPending, isTrue, reason: 'statut $status');
      }
    });

    test('une action tranchée ne propose plus de décision', () {
      for (final status in ['CONFIRMED', 'REJECTED', 'EXPIRED']) {
        final action = LeoAction.fromJson({
          'id': 1, 'type': 'OPEN_POSITION', 'status': status, 'rationale': '',
        });
        expect(action.isPending, isFalse, reason: 'statut $status');
      }
    });

    test('un statut absent est traité comme en attente, jamais comme exécuté', () {
      final action = LeoAction.fromJson({'id': 1, 'type': 'X'});

      expect(action.isPending, isTrue);
    });

    test('lit le type sous ses deux noms de champ', () {
      expect(
        LeoAction.fromJson({'id': 1, 'action_type': 'CLOSE_POSITION'}).type,
        'CLOSE_POSITION',
      );
      expect(
        LeoAction.fromJson({'id': 1, 'type': 'CLOSE_POSITION'}).type,
        'CLOSE_POSITION',
      );
    });
  });

  group('LeoTurn', () {
    test('distingue l\'utilisateur de l\'assistant', () {
      final user = LeoTurn.fromJson({'id': 1, 'role': 'USER', 'content': 'bonjour'});
      final leo = LeoTurn.fromJson({'id': 2, 'role': 'ASSISTANT', 'content': 'salut'});

      expect(user.isUser, isTrue);
      expect(leo.isUser, isFalse);
    });

    test('un rôle inconnu est attribué à l\'assistant, pas à l\'utilisateur', () {
      // Attribuer à tort un message à l'utilisateur laisserait croire
      // qu'il a dit quelque chose qu'il n'a pas dit.
      final turn = LeoTurn.fromJson({'id': 1, 'role': 'ROBOT', 'content': 'x'});

      expect(turn.isUser, isFalse);
    });

    test('un tour sans action n\'en invente pas', () {
      final turn = LeoTurn.fromJson({'id': 1, 'role': 'ASSISTANT', 'content': 'x'});

      expect(turn.actions, isEmpty);
    });

    test('copyWith préserve l\'identité et le rôle', () {
      final turn = LeoTurn.fromJson({'id': 7, 'role': 'ASSISTANT', 'content': 'a'});
      final updated = turn.copyWith(content: 'ab', streaming: false);

      expect(updated.id, '7');
      expect(updated.isUser, isFalse);
      expect(updated.content, 'ab');
    });
  });

  group('LeoState', () {
    test('clearError efface réellement l\'erreur', () {
      const state = LeoState(error: 'panne');

      expect(state.copyWith(clearError: true).error, isNull);
    });

    test('copyWith sans argument ne perd rien', () {
      const state = LeoState(
        connection: LeoConnection.online,
        thinking: true,
        error: 'x',
      );
      final copy = state.copyWith();

      expect(copy.connected, isTrue);
      expect(copy.thinking, isTrue);
      expect(copy.error, 'x');
    });

    test('une connexion perdue ne se confond pas avec une connexion en cours', () {
      // Les deux états partageaient le libellé « Connexion… » : après une
      // coupure, l'écran annonçait indéfiniment une reconnexion que
      // personne ne tentait.
      const lost = LeoState(connection: LeoConnection.lost);
      const connecting = LeoState(connection: LeoConnection.connecting);

      expect(lost.connected, isFalse);
      expect(connecting.connected, isFalse);
      expect(lost.connection, isNot(connecting.connection));
    });

    test('une demande tranchée se retire de l\'écran', () {
      const request = LeoActionRequest(
        id: 4,
        actionType: 'OPEN_POSITION',
        status: 'WAITING',
        mode: 'LIVE',
        summary: 'Acheter 0,1 BTC',
        riskSummary: '',
        requiresDoubleConfirmation: true,
        confirmationsReceived: 0,
        errorMessage: '',
      );
      const state = LeoState(actionRequest: request);

      expect(state.actionRequest, isNotNull);
      expect(state.copyWith(clearActionRequest: true).actionRequest, isNull);
    });
  });

  group('LeoActionRequest', () {
    LeoActionRequest parse(Map<String, dynamic> overrides) =>
        LeoActionRequest.fromJson({
          'id': 9,
          'action_type': 'OPEN_POSITION',
          'status': 'WAITING',
          'mode': 'PAPER',
          'summary': 'Acheter 0,1 BTC',
          'risk_summary': 'Exposition 4 %',
          'requires_double_confirmation': false,
          'confirmations_received': 0,
          'error_message': '',
          ...overrides,
        });

    test('le mode réel est reconnu comme tel', () {
      expect(parse({'mode': 'LIVE'}).isLive, isTrue);
      expect(parse({'mode': 'PAPER'}).isLive, isFalse);
    });

    test('une demande tranchée ne propose plus rien', () {
      expect(parse({'status': 'WAITING'}).isActionable, isTrue);
      expect(parse({'status': 'EXECUTED'}).isActionable, isFalse);
      expect(parse({'status': 'CANCELLED'}).isActionable, isFalse);
    });

    test('la seconde confirmation du mode réel est suivie', () {
      // Le serveur exige deux confirmations distinctes en LIVE. Les
      // compter côté client permet d'annoncer laquelle on demande, sans
      // jamais décider à la place du serveur.
      expect(
        parse({'requires_double_confirmation': true, 'confirmations_received': 1})
            .awaitsSecondConfirmation,
        isTrue,
      );
      expect(
        parse({'requires_double_confirmation': true, 'confirmations_received': 2})
            .awaitsSecondConfirmation,
        isFalse,
      );
      expect(parse({}).awaitsSecondConfirmation, isFalse);
    });

    test('un champ absent ne fait pas échouer la lecture', () {
      final request = LeoActionRequest.fromJson({'id': 3});

      expect(request.id, 3);
      expect(request.status, 'WAITING');
      expect(request.summary, '');
    });
  });
}
