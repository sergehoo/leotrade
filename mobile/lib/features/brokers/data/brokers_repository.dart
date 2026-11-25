import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../../auth/presentation/auth_controller.dart';
import '../domain/models.dart';

/// Charge utile d'écriture d'un compte broker.
///
/// Les secrets sont optionnels et ne sont transmis que s'ils portent une
/// valeur : le serveur interprète l'absence comme « conserver l'existant »,
/// ce qui permet de modifier un compte sans ressaisir ses clés.
class BrokerAccountDraft {
  const BrokerAccountDraft({
    required this.name,
    required this.broker,
    required this.mode,
    this.login,
    this.server,
    this.terminalPath,
    this.derivAppId,
    this.derivCurrency,
    this.derivAccountType,
    this.isActive = true,
    this.isDefault = false,
    this.notes,
    this.secrets = const {},
  });

  final String name;
  final BrokerKind broker;
  final TradingMode mode;
  final String? login;
  final String? server;
  final String? terminalPath;
  final String? derivAppId;
  final String? derivCurrency;
  final String? derivAccountType;
  final bool isActive;
  final bool isDefault;
  final String? notes;
  final Map<SecretField, String> secrets;

  Map<String, dynamic> toJson() {
    final payload = <String, dynamic>{
      'name': name,
      'broker': brokerKindWire(broker),
      'mode': tradingModeWire(mode),
      'is_active': isActive,
      'is_default': isDefault,
      'notes': notes ?? '',
    };

    void put(String key, String? value) {
      if (value != null) payload[key] = value;
    }

    switch (broker) {
      case BrokerKind.mt5:
        put('login', login);
        put('server', server);
        put('terminal_path', terminalPath);
      case BrokerKind.deriv:
        put('deriv_app_id', derivAppId);
        put('deriv_currency', derivCurrency);
        put('deriv_account_type', derivAccountType);
      case BrokerKind.binance:
      case BrokerKind.unknown:
        break;
    }

    for (final entry in secrets.entries) {
      if (entry.value.isEmpty) continue;
      payload[secretFieldWire(entry.key)] = entry.value;
    }
    return payload;
  }
}

class BrokersRepository {
  const BrokersRepository(this._client);

  final ApiClient _client;

  Future<List<BrokerAccount>> list() async {
    final body = await _client.get<Map<String, dynamic>>('/brokers/');
    final results = body['results'];
    if (results is! List) return const [];
    return results
        .whereType<Map<String, dynamic>>()
        .map(BrokerAccount.fromJson)
        .toList(growable: false);
  }

  Future<List<BrokerHealth>> health() async {
    final body = await _client.get<Map<String, dynamic>>('/brokers/health/');
    final results = body['results'];
    if (results is! List) return const [];
    return results
        .whereType<Map<String, dynamic>>()
        .map(BrokerHealth.fromJson)
        .toList(growable: false);
  }

  Future<BrokerAccount> create(BrokerAccountDraft draft) async {
    final body = await _client.post<Map<String, dynamic>>(
      '/brokers/',
      data: draft.toJson(),
    );
    return BrokerAccount.fromJson(body);
  }

  Future<BrokerAccount> update(int id, BrokerAccountDraft draft) async {
    final body = await _client.patch<Map<String, dynamic>>(
      '/brokers/$id/',
      data: draft.toJson(),
    );
    return BrokerAccount.fromJson(body);
  }

  Future<BrokerAccount> setDefault(int id) async {
    final body =
        await _client.post<Map<String, dynamic>>('/brokers/$id/set-default/');
    return BrokerAccount.fromJson(body);
  }

  /// Lance le test de connexion réel. Lève une [ApiError] portant le code
  /// `MISSING_SECRETS` ou `CONNECTION_FAILED` selon la cause de l'échec,
  /// pour que l'interface distingue « identifiants incomplets » de
  /// « broker qui refuse ».
  Future<void> testConnection(int id) async {
    await _client.post<Map<String, dynamic>>('/brokers/$id/test-connection/');
  }

  Future<void> remove(int id) => _client.delete('/brokers/$id/');
}

final brokersRepositoryProvider = Provider<BrokersRepository>(
  (ref) => BrokersRepository(ref.watch(apiClientProvider)),
);

/// Liste des comptes. Rattachée à l'authentification : une déconnexion
/// invalide la liste, qui ne doit jamais rester affichée avec les comptes
/// du compte précédent.
final brokerAccountsProvider =
    FutureProvider.autoDispose<List<BrokerAccount>>((ref) async {
  final authenticated = ref.watch(
    authControllerProvider.select((state) => state.isAuthenticated),
  );
  if (!authenticated) throw const ApiError('Session fermée.');
  return ref.watch(brokersRepositoryProvider).list();
});

/// Santé du parc, indexée par identifiant de compte.
final brokerHealthProvider =
    FutureProvider.autoDispose<Map<int, BrokerHealth>>((ref) async {
  final authenticated = ref.watch(
    authControllerProvider.select((state) => state.isAuthenticated),
  );
  if (!authenticated) return const {};
  final rows = await ref.watch(brokersRepositoryProvider).health();
  return {for (final row in rows) row.id: row};
});
