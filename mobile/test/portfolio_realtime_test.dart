import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:leotrade/core/network/realtime.dart';
import 'package:leotrade/core/network/token_store.dart';
import 'package:leotrade/features/auth/domain/models.dart';
import 'package:leotrade/features/auth/presentation/auth_controller.dart';
import 'package:leotrade/features/portfolio/data/portfolio_realtime.dart';

import 'support/fake_channel.dart';

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

Future<PortfolioLive Function()> _connected(FakeChannel channel) async {
  final container = ProviderContainer(
    overrides: [
      authControllerProvider.overrideWith(_SignedIn.new),
      tokenStoreProvider.overrideWithValue(TokenStore()..accessToken = 'jeton'),
      realtimeChannelFactoryProvider.overrideWithValue((_, __) => channel),
    ],
  );
  addTearDown(container.dispose);

  // Un abonnement d'abord : le provider est `autoDispose`, une simple
  // lecture le démonterait aussitôt.
  container.listen(portfolioRealtimeProvider(7), (_, __) {},
      fireImmediately: true);
  await Future<void>.delayed(Duration.zero);
  return () => container.read(portfolioRealtimeProvider(7));
}

void main() {
  group('Flux du portefeuille', () {
    test('la liaison s\'ouvre sur le bon chemin', () async {
      // Le canal existait côté serveur depuis l'origine ; aucun des deux
      // clients ne s'y connectait.
      final channel = FakeChannel();
      final read = await _connected(channel);

      expect(read().status, RealtimeStatus.online);
    });

    test(
      'une poignée de main ne compte pas comme une mise à jour',
      () async {
        // « Connecté » et « à jour » sont deux choses différentes : une
        // liaison ouverte qui ne reçoit rien ressemble à une liaison qui
        // tient les prix à jour.
        final channel = FakeChannel();
        final read = await _connected(channel);

        channel.push({
          'event': 'connection.established',
          'payload': {'portfolio_id': 7, 'group': 'portfolio_7'},
        });
        await Future<void>.delayed(Duration.zero);

        expect(read().isOnline, isTrue);
        expect(read().isSilent, isTrue,
            reason: 'aucune mesure n\'est encore arrivée');
        expect(read().lastEventAt, isNull);
      },
    );

    test('un mark corrige la position visée', () async {
      final channel = FakeChannel();
      final read = await _connected(channel);

      channel.push({
        'event': 'position.update',
        'payload': {
          'position': {
            'id': 42,
            'symbol': 'BTCUSDT',
            'mark_price': '78776.62',
            'unrealized_pnl': '-124.50',
          },
        },
      });
      await Future<void>.delayed(Duration.zero);

      final patch = read().positions[42];
      expect(patch, isNotNull);
      expect(patch!.markPrice, '78776.62');
      expect(patch.unrealizedPnl, '-124.50');
      expect(read().isSilent, isFalse);
      expect(read().lastEventAt, isNotNull);
    });

    test(
      'un champ absent du message ne remplace rien',
      () async {
        // C'est la règle qui protège l'affichage : un correctif partiel
        // ne doit pas écraser une valeur REST par un zéro qui passerait
        // ensuite pour une mesure.
        final channel = FakeChannel();
        final read = await _connected(channel);

        channel.push({
          'event': 'position.update',
          'payload': {
            'position': {'id': 42, 'mark_price': '78776.62'},
          },
        });
        await Future<void>.delayed(Duration.zero);

        final patch = read().positions[42]!;
        expect(patch.markPrice, '78776.62');
        expect(patch.unrealizedPnl, isNull);
        expect(patch.quantity, isNull);
      },
    );

    test('les montants restent en chaîne', () async {
      final channel = FakeChannel();
      final read = await _connected(channel);

      channel.push({
        'event': 'position.update',
        'payload': {
          'position': {'id': 1, 'mark_price': '0.000450009999'},
        },
      });
      await Future<void>.delayed(Duration.zero);

      final value = read().positions[1]!.markPrice;
      expect(value, isA<String>());
      expect(value, '0.000450009999');
    });

    test('un recalcul met à jour la synthèse', () async {
      final channel = FakeChannel();
      final read = await _connected(channel);

      channel.push({
        'event': 'portfolio.update',
        'payload': {
          'kind': 'metrics_refresh',
          'portfolio_id': 7,
          'equity': '10250.00',
          'available_cash': '9100.00',
          'locked_cash': '150.00',
          'unrealized_pnl': '250.00',
          'realized_pnl': '0.00',
        },
      });
      await Future<void>.delayed(Duration.zero);

      final metrics = read().metrics!;
      expect(metrics.equity, '10250.00');
      expect(metrics.lockedCash, '150.00');
      expect(read().lastEventAt, isNotNull);
    });

    test('un instantané remplace la table des positions', () async {
      final channel = FakeChannel();
      final read = await _connected(channel);

      channel.push({
        'event': 'position.update',
        'payload': {
          'position': {'id': 1, 'mark_price': '1.00'},
        },
      });
      await Future<void>.delayed(Duration.zero);

      channel.push({
        'event': 'portfolio.update',
        'payload': {
          'kind': 'positions_snapshot',
          'positions': [
            {'id': 2, 'mark_price': '2.00'},
          ],
        },
      });
      await Future<void>.delayed(Duration.zero);

      expect(read().positions.keys, [2],
          reason: 'un instantané fait foi : il remplace, il ne complète pas');
    });

    test(
      'un événement d\'une autre forme vaut signe de vie, sans rien corriger',
      () async {
        // Un ordre passé, un instantané créé : la forme change, mais la
        // liaison prouve qu'elle vit.
        final channel = FakeChannel();
        final read = await _connected(channel);

        channel.push({
          'event': 'portfolio.update',
          'payload': {'kind': 'snapshot_created', 'snapshot_id': 12},
        });
        await Future<void>.delayed(Duration.zero);

        expect(read().lastEventAt, isNotNull);
        expect(read().metrics, isNull);
        expect(read().positions, isEmpty);
      },
    );

    test('un message illisible ne fait pas tomber la liaison', () async {
      final channel = FakeChannel();
      final read = await _connected(channel);

      channel.pushRaw('{ ceci n\'est pas du JSON');
      await Future<void>.delayed(Duration.zero);

      expect(read().status, RealtimeStatus.online);
    });

    test('une coupure est annoncée comme telle', () async {
      final channel = FakeChannel();
      final read = await _connected(channel);

      channel.drop();
      await Future<void>.delayed(Duration.zero);

      expect(read().status, RealtimeStatus.lost);
      expect(read().isOnline, isFalse);
    });
  });
}
