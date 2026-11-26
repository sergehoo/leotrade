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
      const state = LeoState(connected: true, thinking: true, error: 'x');
      final copy = state.copyWith();

      expect(copy.connected, isTrue);
      expect(copy.thinking, isTrue);
      expect(copy.error, 'x');
    });
  });
}
