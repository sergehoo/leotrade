import 'package:flutter_test/flutter_test.dart';
import 'package:lyneci/features/brokers/data/brokers_repository.dart';
import 'package:lyneci/features/brokers/domain/models.dart';

/// Réponse telle que la sert `api/serializers/brokers.py` : les secrets
/// n'y figurent que sous forme de métadonnées.
Map<String, dynamic> _accountJson({
  String mode = 'PAPER',
  bool derivTokenConfigured = true,
  List<String> missing = const [],
}) =>
    {
      'id': 7,
      'name': 'Deriv principal',
      'broker': 'DERIV',
      'mode': mode,
      'login': null,
      'server': null,
      'deriv_app_id': '1089',
      'deriv_currency': 'USD',
      'is_active': true,
      'is_default': true,
      'status': 'ACTIVE',
      'last_connection_status': true,
      'last_connection_error': null,
      'last_connected_at': '2026-11-25T17:53:04.328995Z',
      'secrets': {
        'api_key': {'configured': false, 'updated_at': null, 'rotated_at': null},
        'api_secret': {'configured': false, 'updated_at': null, 'rotated_at': null},
        'password': {'configured': false, 'updated_at': null, 'rotated_at': null},
        'deriv_token': {
          'configured': derivTokenConfigured,
          'updated_at': '2026-11-25T17:52:42.121816Z',
          'rotated_at': null,
        },
      },
      'missing_secrets': missing,
      'required_secrets': ['deriv_token'],
      'is_ready_to_connect': missing.isEmpty,
    };

void main() {
  group('BrokerAccount — lecture du contrat', () {
    test('ne porte que la présence d\'un secret, jamais sa valeur', () {
      final account = BrokerAccount.fromJson(_accountJson());

      expect(account.secretState(SecretField.derivToken).configured, isTrue);
      expect(account.secretState(SecretField.apiKey).configured, isFalse);
      // SecretState n'expose aucun champ de valeur : l'invariant est
      // porté par le type, pas par une convention d'appel.
      expect(
        account.secretState(SecretField.derivToken).updatedAt,
        isA<DateTime>(),
      );
    });

    test('rapporte les secrets manquants pour guider la saisie', () {
      final account = BrokerAccount.fromJson(
        _accountJson(derivTokenConfigured: false, missing: ['deriv_token']),
      );

      expect(account.missingSecrets, [SecretField.derivToken]);
      expect(account.isReadyToConnect, isFalse);
    });

    test('distingue le mode Live du mode Paper', () {
      expect(BrokerAccount.fromJson(_accountJson()).isLive, isFalse);
      expect(BrokerAccount.fromJson(_accountJson(mode: 'LIVE')).isLive, isTrue);
    });

    test('dégrade un broker inconnu au lieu de lever', () {
      // Un broker ajouté côté serveur ne doit pas faire planter un client
      // déjà déployé sur un téléphone.
      final json = _accountJson()..['broker'] = 'KRAKEN';

      expect(BrokerAccount.fromJson(json).broker, BrokerKind.unknown);
    });

    test('un circuit illisible est rapporté indisponible, pas fermé', () {
      // Prétendre « fermé » quand l'état n'a pas pu être lu laisserait
      // croire que le broker est joignable.
      expect(circuitStateFrom(null), CircuitState.unavailable);
      expect(circuitStateFrom('???'), CircuitState.unavailable);
      expect(circuitStateFrom('CLOSED'), CircuitState.closed);
    });

    test('un champ secrets absent ne fait pas échouer la lecture', () {
      final json = _accountJson()..remove('secrets');

      final account = BrokerAccount.fromJson(json);

      expect(account.secretState(SecretField.derivToken).configured, isFalse);
    });
  });

  group('BrokerAccountDraft — écriture', () {
    test('un secret vide n\'est pas transmis', () {
      // Le serveur lit l'absence comme « conserver l'existant » : envoyer
      // une chaîne vide effacerait l'identifiant enregistré.
      final payload = const BrokerAccountDraft(
        name: 'Deriv',
        broker: BrokerKind.deriv,
        mode: TradingMode.paper,
        derivAppId: '1089',
        secrets: {SecretField.derivToken: ''},
      ).toJson();

      expect(payload.containsKey('deriv_token'), isFalse);
    });

    test('un secret renseigné est transmis sous sa clé d\'API', () {
      final payload = const BrokerAccountDraft(
        name: 'Deriv',
        broker: BrokerKind.deriv,
        mode: TradingMode.paper,
        derivAppId: '1089',
        secrets: {SecretField.derivToken: 'a1-TOKEN'},
      ).toJson();

      expect(payload['deriv_token'], 'a1-TOKEN');
    });

    test('n\'envoie que les champs propres au broker choisi', () {
      final payload = const BrokerAccountDraft(
        name: 'MT5',
        broker: BrokerKind.mt5,
        mode: TradingMode.paper,
        login: '12345',
        server: 'ICMarkets-Demo',
        // Renseigné par erreur : ne concerne pas MT5.
        derivAppId: '1089',
      ).toJson();

      expect(payload['login'], '12345');
      expect(payload['server'], 'ICMarkets-Demo');
      expect(payload.containsKey('deriv_app_id'), isFalse);
    });

    test('le mode est transmis dans la forme attendue par le serveur', () {
      expect(
        const BrokerAccountDraft(
          name: 'X',
          broker: BrokerKind.binance,
          mode: TradingMode.live,
        ).toJson()['mode'],
        'LIVE',
      );
    });
  });
}
