// Modèles du domaine brokers, alignés sur api/serializers/brokers.py.
//
// Invariant central : aucune valeur de secret ne traverse ce fichier. Le
// serveur n'expose que l'existence d'un secret et sa date de rotation ;
// `SecretState` reflète exactement cela, sans champ de valeur, pour que
// l'erreur soit impossible à commettre plus haut dans l'application.

enum BrokerKind { binance, mt5, deriv, unknown }

BrokerKind brokerKindFrom(String? raw) => switch (raw) {
      'BINANCE' => BrokerKind.binance,
      'MT5' => BrokerKind.mt5,
      'DERIV' => BrokerKind.deriv,
      // Un broker ajouté côté serveur ne doit pas faire planter un client
      // déjà déployé : on dégrade au lieu de lever.
      _ => BrokerKind.unknown,
    };

String brokerKindLabel(BrokerKind kind) => switch (kind) {
      BrokerKind.binance => 'Binance',
      BrokerKind.mt5 => 'MetaTrader 5',
      BrokerKind.deriv => 'Deriv',
      BrokerKind.unknown => 'Broker inconnu',
    };

String brokerKindWire(BrokerKind kind) => switch (kind) {
      BrokerKind.binance => 'BINANCE',
      BrokerKind.mt5 => 'MT5',
      BrokerKind.deriv => 'DERIV',
      BrokerKind.unknown => '',
    };

enum TradingMode { paper, live }

TradingMode tradingModeFrom(String? raw) =>
    raw == 'LIVE' ? TradingMode.live : TradingMode.paper;

String tradingModeWire(TradingMode mode) =>
    mode == TradingMode.live ? 'LIVE' : 'PAPER';

enum BrokerStatus { draft, active, inactive, error, unknown }

BrokerStatus brokerStatusFrom(String? raw) => switch (raw) {
      'DRAFT' => BrokerStatus.draft,
      'ACTIVE' => BrokerStatus.active,
      'INACTIVE' => BrokerStatus.inactive,
      'ERROR' => BrokerStatus.error,
      _ => BrokerStatus.unknown,
    };

enum CircuitState { closed, halfOpen, open, unavailable }

CircuitState circuitStateFrom(String? raw) => switch (raw) {
      'CLOSED' => CircuitState.closed,
      'HALF_OPEN' => CircuitState.halfOpen,
      'OPEN' => CircuitState.open,
      // « Indisponible » est l'état sûr : on ne prétend pas que le circuit
      // est fermé quand on n'a pas pu lire son état.
      _ => CircuitState.unavailable,
    };

String circuitStateLabel(CircuitState state) => switch (state) {
      CircuitState.closed => 'Fermé',
      CircuitState.halfOpen => 'Semi-ouvert',
      CircuitState.open => 'Ouvert',
      CircuitState.unavailable => 'Indisponible',
    };

/// Champ de secret. Porte un identifiant, jamais une valeur.
enum SecretField { apiKey, apiSecret, password, derivToken }

SecretField? secretFieldFrom(String? raw) => switch (raw) {
      'api_key' => SecretField.apiKey,
      'api_secret' => SecretField.apiSecret,
      'password' => SecretField.password,
      'deriv_token' => SecretField.derivToken,
      _ => null,
    };

String secretFieldWire(SecretField field) => switch (field) {
      SecretField.apiKey => 'api_key',
      SecretField.apiSecret => 'api_secret',
      SecretField.password => 'password',
      SecretField.derivToken => 'deriv_token',
    };

String secretFieldLabel(SecretField field) => switch (field) {
      SecretField.apiKey => 'Clé API',
      SecretField.apiSecret => 'Secret API',
      SecretField.password => 'Mot de passe',
      SecretField.derivToken => 'Jeton Deriv',
    };

/// Présence d'un secret — jamais sa valeur.
class SecretState {
  const SecretState({required this.configured, this.updatedAt});

  factory SecretState.fromJson(Map<String, dynamic>? json) => SecretState(
        configured: json?['configured'] as bool? ?? false,
        updatedAt: DateTime.tryParse('${json?['updated_at'] ?? ''}'),
      );

  final bool configured;
  final DateTime? updatedAt;
}

class BrokerAccount {
  const BrokerAccount({
    required this.id,
    required this.name,
    required this.broker,
    required this.mode,
    required this.isActive,
    required this.isDefault,
    required this.status,
    required this.connected,
    required this.secrets,
    required this.missingSecrets,
    required this.requiredSecrets,
    required this.isReadyToConnect,
    this.login,
    this.server,
    this.terminalPath,
    this.derivAppId,
    this.derivCurrency = 'USD',
    this.derivAccountType,
    this.lastConnectionError,
    this.lastConnectedAt,
    this.notes,
  });

  factory BrokerAccount.fromJson(Map<String, dynamic> json) {
    final rawSecrets = json['secrets'];
    final secrets = <SecretField, SecretState>{};
    if (rawSecrets is Map) {
      for (final entry in rawSecrets.entries) {
        final field = secretFieldFrom('${entry.key}');
        if (field == null) continue;
        secrets[field] = SecretState.fromJson(
          entry.value is Map<String, dynamic>
              ? entry.value as Map<String, dynamic>
              : null,
        );
      }
    }

    return BrokerAccount(
      id: json['id'] as int,
      name: json['name'] as String? ?? '',
      broker: brokerKindFrom(json['broker'] as String?),
      mode: tradingModeFrom(json['mode'] as String?),
      isActive: json['is_active'] as bool? ?? false,
      isDefault: json['is_default'] as bool? ?? false,
      status: brokerStatusFrom(json['status'] as String?),
      connected: json['last_connection_status'] as bool? ?? false,
      secrets: secrets,
      missingSecrets: _secretList(json['missing_secrets']),
      requiredSecrets: _secretList(json['required_secrets']),
      isReadyToConnect: json['is_ready_to_connect'] as bool? ?? false,
      login: json['login'] as String?,
      server: json['server'] as String?,
      terminalPath: json['terminal_path'] as String?,
      derivAppId: json['deriv_app_id'] as String?,
      derivCurrency: json['deriv_currency'] as String? ?? 'USD',
      derivAccountType: json['deriv_account_type'] as String?,
      lastConnectionError: json['last_connection_error'] as String?,
      lastConnectedAt: DateTime.tryParse('${json['last_connected_at'] ?? ''}'),
      notes: json['notes'] as String?,
    );
  }

  final int id;
  final String name;
  final BrokerKind broker;
  final TradingMode mode;
  final bool isActive;
  final bool isDefault;
  final BrokerStatus status;
  final bool connected;
  final Map<SecretField, SecretState> secrets;
  final List<SecretField> missingSecrets;
  final List<SecretField> requiredSecrets;
  final bool isReadyToConnect;
  final String? login;
  final String? server;
  final String? terminalPath;
  final String? derivAppId;
  final String derivCurrency;
  final String? derivAccountType;
  final String? lastConnectionError;
  final DateTime? lastConnectedAt;
  final String? notes;

  bool get isLive => mode == TradingMode.live;
  bool get hasError => status == BrokerStatus.error;

  SecretState secretState(SecretField field) =>
      secrets[field] ?? const SecretState(configured: false);

  static List<SecretField> _secretList(Object? raw) {
    if (raw is! List) return const [];
    return raw
        .map((item) => secretFieldFrom('$item'))
        .whereType<SecretField>()
        .toList(growable: false);
  }
}

/// Santé opérationnelle — état persisté, aucune I/O broker déclenchée.
class BrokerHealth {
  const BrokerHealth({
    required this.id,
    required this.circuitState,
    this.lastSyncAt,
  });

  factory BrokerHealth.fromJson(Map<String, dynamic> json) => BrokerHealth(
        id: json['id'] as int,
        circuitState: circuitStateFrom(json['circuit_state'] as String?),
        lastSyncAt: DateTime.tryParse('${json['last_sync_at'] ?? ''}'),
      );

  final int id;
  final CircuitState circuitState;
  final DateTime? lastSyncAt;
}
