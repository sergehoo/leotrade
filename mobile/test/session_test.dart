import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:leotrade/core/network/api_client.dart';
import 'package:leotrade/core/network/token_store.dart';
import 'package:leotrade/features/auth/data/auth_repository.dart';
import 'package:leotrade/features/auth/domain/models.dart';

/// Adaptateur piloté par le test : chaque requête est servie par la
/// fonction fournie, sans réseau.
class _ScriptedAdapter implements HttpClientAdapter {
  _ScriptedAdapter(this.serve);

  final Future<ResponseBody> Function(RequestOptions options) serve;
  final List<String> seen = [];

  @override
  void close({bool force = false}) {}

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) {
    seen.add(options.path);
    return serve(options);
  }
}

ResponseBody _json(Map<String, dynamic> body, int status) => ResponseBody.fromString(
      jsonEncode(body),
      status,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );

/// Keychain en mémoire : le vrai `TokenStore` est exercé, seul le canal
/// natif est simulé. Un faux `TokenStore` aurait laissé non testé ce qui
/// compte ici — qu'un jeton soit effacé, ou qu'il ne le soit pas.
Map<String, String> _installFakeKeychain() {
  final storage = <String, String>{};
  const channel = MethodChannel('plugins.it_nomads.com/flutter_secure_storage');

  TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
      .setMockMethodCallHandler(channel, (call) async {
    final args = Map<String, dynamic>.from(call.arguments as Map);
    final key = args['key'] as String?;
    switch (call.method) {
      case 'read':
        return storage[key];
      case 'write':
        storage[key!] = args['value'] as String;
        return null;
      case 'delete':
        storage.remove(key);
        return null;
      case 'readAll':
        return storage;
      case 'deleteAll':
        storage.clear();
        return null;
      case 'containsKey':
        return storage.containsKey(key);
    }
    return null;
  });
  return storage;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('Rejeu après rafraîchissement', () {
    late Map<String, String> keychain;
    late TokenStore tokens;

    setUp(() async {
      keychain = _installFakeKeychain();
      tokens = TokenStore();
      await tokens.writeRefreshToken('refresh-valide');
    });

    test(
      "une panne sur la requête REJOUÉE ne détruit pas la session",
      () async {
        // Le scénario : le jeton d'accès a expiré, le rafraîchissement
        // réussit, puis la requête rejouée tombe sur un 500. Avant
        // correction, le `catch` englobait le rejeu : l'utilisateur était
        // déconnecté par un incident serveur sans rapport avec son jeton.
        var expired = false;
        final business = Dio();
        business.httpClientAdapter = _ScriptedAdapter((options) async {
          if (options.extra['retried'] == true) {
            return _json({'detail': 'Panne interne.'}, 500);
          }
          return _json({'detail': 'Jeton expiré.'}, 401);
        });

        final refresher = Dio();
        refresher.httpClientAdapter = _ScriptedAdapter(
          (_) async => _json({'access': 'acces-frais'}, 200),
        );

        final client = ApiClient(
          tokenStore: tokens,
          dio: business,
          refreshDio: refresher,
        )..onSessionExpired = () => expired = true;

        await expectLater(
          client.get<Map<String, dynamic>>('/portfolios/'),
          throwsA(isA<ApiError>().having((e) => e.statusCode, 'statut', 500)),
        );

        expect(await tokens.readRefreshToken(), 'refresh-valide',
            reason: 'le refresh token devait survivre à un 500 sur le rejeu');
        expect(keychain.containsKey('lyneci.refresh'), isTrue);
        expect(expired, isFalse,
            reason: 'aucune session perdue : seul le rejeu a échoué');
      },
    );

    test("un rafraîchissement REFUSÉ ferme bien la session", () async {
      var expired = false;
      final business = Dio();
      business.httpClientAdapter = _ScriptedAdapter(
        (_) async => _json({'detail': 'Jeton expiré.'}, 401),
      );

      final refresher = Dio();
      refresher.httpClientAdapter = _ScriptedAdapter(
        (_) async => _json({'detail': 'Jeton révoqué.'}, 401),
      );

      final client = ApiClient(
        tokenStore: tokens,
        dio: business,
        refreshDio: refresher,
      )..onSessionExpired = () => expired = true;

      await expectLater(
        client.get<Map<String, dynamic>>('/portfolios/'),
        throwsA(isA<ApiError>()),
      );

      expect(await tokens.readRefreshToken(), isNull);
      expect(expired, isTrue);
    });

    test('la rotation du refresh est enregistrée', () async {
      final business = Dio();
      var replayed = false;
      business.httpClientAdapter = _ScriptedAdapter((options) async {
        if (options.extra['retried'] == true) {
          replayed = true;
          return _json({'results': <dynamic>[]}, 200);
        }
        return _json({'detail': 'Jeton expiré.'}, 401);
      });

      final refresher = Dio();
      refresher.httpClientAdapter = _ScriptedAdapter(
        (_) async => _json(
          {'access': 'acces-frais', 'refresh': 'refresh-pivote'},
          200,
        ),
      );

      final client = ApiClient(
        tokenStore: tokens,
        dio: business,
        refreshDio: refresher,
      );

      await client.get<Map<String, dynamic>>('/portfolios/');

      expect(replayed, isTrue);
      expect(await tokens.readRefreshToken(), 'refresh-pivote',
          reason: 'sans cela, la session suivante présente un jeton révoqué');
    });

    test('un seul rafraîchissement pour deux requêtes concurrentes', () async {
      final business = Dio();
      business.httpClientAdapter = _ScriptedAdapter((options) async {
        if (options.extra['retried'] == true) {
          return _json({'ok': true}, 200);
        }
        return _json({'detail': 'Jeton expiré.'}, 401);
      });

      var refreshes = 0;
      final refresher = Dio();
      refresher.httpClientAdapter = _ScriptedAdapter((_) async {
        refreshes++;
        await Future<void>.delayed(const Duration(milliseconds: 20));
        return _json({'access': 'acces-frais'}, 200);
      });

      final client = ApiClient(
        tokenStore: tokens,
        dio: business,
        refreshDio: refresher,
      );

      await Future.wait([
        client.get<Map<String, dynamic>>('/portfolios/'),
        client.get<Map<String, dynamic>>('/positions/'),
      ]);

      // La rotation est active côté serveur : deux rafraîchissements
      // concurrents présenteraient le même jeton, déjà consommé pour tous
      // sauf un, et feraient tomber la session.
      expect(refreshes, 1);
    });
  });

  group('Reprise de session au lancement', () {
    late Map<String, String> keychain;
    late TokenStore tokens;

    setUp(() async {
      keychain = _installFakeKeychain();
      tokens = TokenStore();
    });

    AuthRepository buildRepository(
      Future<ResponseBody> Function(RequestOptions) serve, {
      Future<ResponseBody> Function(RequestOptions)? refresh,
    }) {
      final business = Dio()..httpClientAdapter = _ScriptedAdapter(serve);
      final refresher = Dio()
        ..httpClientAdapter = _ScriptedAdapter(
          refresh ?? (_) async => _json({'detail': 'Jeton révoqué.'}, 401),
        );
      return AuthRepository(
        client: ApiClient(
          tokenStore: tokens,
          dio: business,
          refreshDio: refresher,
        ),
        tokens: tokens,
      );
    }

    test('sans jeton, aucune session — et rien à effacer', () async {
      final result = await buildRepository((_) async => _json({}, 200)).restore();
      expect(result, isA<NoSession>());
    });

    test(
      'serveur injoignable : le jeton est CONSERVÉ',
      () async {
        // C'était le défaut : `on ApiError` attrapait aussi la panne
        // réseau. Démarrer l'application dans le métro effaçait un jeton
        // parfaitement valide, et imposait de ressaisir son mot de passe —
        // y compris avec une position ouverte à surveiller.
        await tokens.writeRefreshToken('refresh-valide');

        final result = await buildRepository(
          (options) async => throw DioException.connectionError(
            requestOptions: options,
            reason: 'réseau coupé',
          ),
        ).restore();

        expect(result, isA<RestoreUnavailable>());
        expect(await tokens.readRefreshToken(), 'refresh-valide');
        expect(keychain.containsKey('lyneci.refresh'), isTrue);
      },
    );

    test('une panne serveur 5xx ne vaut pas non plus déconnexion', () async {
      await tokens.writeRefreshToken('refresh-valide');

      final result = await buildRepository(
        (_) async => _json({'detail': 'Indisponible.'}, 503),
      ).restore();

      expect(result, isA<RestoreUnavailable>());
      expect(await tokens.readRefreshToken(), 'refresh-valide');
    });

    test('un jeton RÉVOQUÉ par le serveur est effacé', () async {
      await tokens.writeRefreshToken('refresh-revoque');

      final result = await buildRepository(
        (_) async => _json({'detail': 'Jeton expiré.'}, 401),
      ).restore();

      expect(result, isA<NoSession>());
      expect(await tokens.readRefreshToken(), isNull);
    });

    test('une session valide est reprise', () async {
      await tokens.writeRefreshToken('refresh-valide');

      final result = await buildRepository(
        (options) async {
          if (options.extra['retried'] == true || options.headers.containsKey('Authorization')) {
            return _json({
              'id': 7,
              'email': 'trader@leotrade.test',
              'kyc_status': 'APPROVED',
            }, 200);
          }
          return _json({'detail': 'Jeton expiré.'}, 401);
        },
        refresh: (_) async => _json({'access': 'acces-frais'}, 200),
      ).restore();

      expect(result, isA<SessionRestored>());
      expect((result as SessionRestored).user.email, 'trader@leotrade.test');
    });
  });
}
