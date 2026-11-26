import 'dart:async';
import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:leotrade/core/network/token_store.dart';
import 'package:leotrade/features/auth/domain/models.dart';
import 'package:leotrade/features/auth/presentation/auth_controller.dart';
import 'package:leotrade/features/leo/data/leo_controller.dart';
import 'package:leotrade/features/leo/domain/models.dart';
import 'package:stream_channel/stream_channel.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

/// Socket pilotée par le test : on pousse les messages du serveur, et on
/// lit ce que le client envoie.
class _FakeChannel extends StreamChannelMixin<dynamic>
    implements WebSocketChannel {
  _FakeChannel() : _incoming = StreamController<dynamic>();

  final StreamController<dynamic> _incoming;
  final List<Map<String, dynamic>> sent = [];
  bool closed = false;

  void push(Map<String, dynamic> event) => _incoming.add(jsonEncode(event));

  void drop() {
    if (!_incoming.isClosed) _incoming.close();
  }

  @override
  Stream<dynamic> get stream => _incoming.stream;

  @override
  WebSocketSink get sink => _FakeSink(this);

  @override
  Future<void> get ready => Future<void>.value();

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class _FakeSink implements WebSocketSink {
  _FakeSink(this._channel);
  final _FakeChannel _channel;

  @override
  void add(dynamic data) {
    if (_channel.closed) throw StateError('socket fermée');
    _channel.sent.add(jsonDecode(data as String) as Map<String, dynamic>);
  }

  @override
  Future<void> close([int? closeCode, String? closeReason]) async {
    _channel.closed = true;
    _channel.drop();
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

/// Session ouverte, sans toucher au réseau ni au Keychain.
class _SignedIn extends AuthController {
  @override
  AuthState build() => AuthState(
        user: CurrentUser.fromJson(const {
          'id': 1,
          'email': 'trader@leotrade.test',
          'kyc_status': 'APPROVED',
        }),
        restoring: false,
      );
}

ProviderContainer _containerWith(_FakeChannel channel) {
  final container = ProviderContainer(
    overrides: [
      authControllerProvider.overrideWith(_SignedIn.new),
      tokenStoreProvider.overrideWithValue(TokenStore()..accessToken = 'jeton'),
      leoChannelFactoryProvider.overrideWithValue((_, __) => channel),
    ],
  );
  addTearDown(container.dispose);
  return container;
}

Future<LeoController> _connected(_FakeChannel channel) async {
  final container = _containerWith(channel);
  // Un abonnement d'abord : le provider est `autoDispose`, une simple
  // lecture le démonterait aussitôt.
  container.listen(leoControllerProvider, (_, __) {}, fireImmediately: true);
  final controller = container.read(leoControllerProvider.notifier);
  // `build()` lance `connect()` dans un microtask : on le laisse partir
  // plutôt que d'en déclencher un second, qui se réabonnerait à une
  // socket déjà écoutée.
  await Future<void>.delayed(Duration.zero);
  return controller;
}

void main() {
  group('Protocole de Leo', () {
    test(
      "un `done` sans `chunk` préalable ne perd pas la réponse",
      () async {
        // C'est la forme que prend le résultat d'un OUTIL côté serveur
        // (`_send_tool_result`) : un `start`, puis directement un `done`
        // portant `clean_content`. Le client ne traitant que les `chunk`,
        // la confirmation d'une opération disparaissait sans un mot.
        final channel = _FakeChannel();
        final controller = await _connected(channel);

        channel.push({
          'type': 'done',
          'id': 42,
          'clean_content': '✅ Position ouverte.',
          'actions': <dynamic>[],
        });
        await Future<void>.delayed(Duration.zero);

        expect(controller.state.turns, hasLength(1));
        expect(controller.state.turns.single.content, '✅ Position ouverte.');
        expect(controller.state.turns.single.isUser, isFalse);
      },
    );

    test('la demande transactionnelle du `done` est lue', () async {
      final channel = _FakeChannel();
      final controller = await _connected(channel);

      channel.push({
        'type': 'done',
        'id': 7,
        'clean_content': 'Confirme-tu ?',
        'actions': <dynamic>[],
        'action_request': {
          'id': 31,
          'action_type': 'OPEN_POSITION',
          'status': 'WAITING',
          'mode': 'LIVE',
          'summary': 'Acheter 0,1 BTC',
          'risk_summary': 'Exposition 4 %',
          'requires_double_confirmation': true,
          'confirmations_received': 0,
        },
      });
      await Future<void>.delayed(Duration.zero);

      final request = controller.state.actionRequest;
      expect(request, isNotNull);
      expect(request!.id, 31);
      expect(request.isLive, isTrue);
      expect(request.summary, 'Acheter 0,1 BTC');
    });

    test(
      'une PROPOSITION est tranchée par la socket, pas par HTTP',
      () async {
        // L'ancienne version postait l'identifiant d'un `AssistantAction`
        // sur `/assistant/action-requests/<id>/confirm/`, l'endpoint d'un
        // AUTRE modèle. Deux séquences de clés primaires : soit le bouton
        // était mort, soit une demande portant le même numéro était
        // confirmée — et exécutée.
        final channel = _FakeChannel();
        final controller = await _connected(channel);

        expect(controller.decideAction(12, confirm: true), isTrue);

        expect(channel.sent.last, {'type': 'action_confirm', 'action_id': 12});
      },
    );

    test('une DEMANDE transactionnelle emprunte son propre type', () async {
      final channel = _FakeChannel();
      final controller = await _connected(channel);

      controller.decideActionRequest(31, confirm: false);

      expect(channel.sent.last, {
        'type': 'action_request_cancel',
        'request_id': 31,
      });
    });

    test(
      "le statut d'une action n'est jamais fabriqué par le client",
      () async {
        final channel = _FakeChannel();
        final controller = await _connected(channel);

        channel.push({
          'type': 'done',
          'id': 5,
          'clean_content': 'Proposition.',
          'actions': [
            {'id': 12, 'type': 'SUGGEST_SIZE', 'status': 'PENDING'},
          ],
        });
        await Future<void>.delayed(Duration.zero);

        controller.decideAction(12, confirm: true);
        await Future<void>.delayed(Duration.zero);

        // Tant que le serveur n'a rien dit, l'action reste en attente.
        expect(controller.state.turns.single.actions.single.status, 'PENDING');

        channel.push({
          'type': 'action_update',
          'action_id': 12,
          'status': 'CONFIRMED',
        });
        await Future<void>.delayed(Duration.zero);

        expect(controller.state.turns.single.actions.single.status, 'CONFIRMED');
      },
    );

    test('un envoi sur une socket morte est refusé et annoncé', () async {
      final channel = _FakeChannel();
      final controller = await _connected(channel);

      channel.drop();
      await Future<void>.delayed(Duration.zero);

      expect(controller.state.connection, LeoConnection.lost);

      final sent = controller.send('Quel est mon risque ?');

      expect(sent, isFalse, reason: 'rien ne doit partir sur une socket morte');
      expect(controller.state.turns, isEmpty,
          reason: 'le message ne doit pas s\'afficher comme envoyé');
      expect(controller.state.error, isNotNull);
    });

    test('une coupure est annoncée comme telle, pas comme une connexion',
        () async {
      final channel = _FakeChannel();
      final controller = await _connected(channel);

      expect(controller.state.connection, LeoConnection.online);

      channel.drop();
      await Future<void>.delayed(Duration.zero);

      // `connecting` et `lost` partageaient le libellé « Connexion… » :
      // l'écran annonçait indéfiniment une reconnexion en cours.
      expect(controller.state.connection, LeoConnection.lost);
    });
  });
}
