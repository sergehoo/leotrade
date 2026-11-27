import 'dart:async';
import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../config/env.dart';

/// Marqueur du sous-protocole JWT — doit correspondre à core/ws_auth.py.
const String kJwtSubprotocol = 'leotrade.jwt';

/// Délais de reconnexion, en secondes. La dernière valeur est répétée.
const List<int> kReconnectDelays = [1, 2, 5, 10, 30];

/// État de la liaison temps réel.
///
/// Trois états et non deux : « en cours de connexion » et « connexion
/// perdue » se ressemblent à l'écran sous un seul libellé, et après une
/// coupure l'interface annonce alors indéfiniment une reconnexion que
/// personne ne tente.
enum RealtimeStatus { connecting, online, lost }

/// Ouverture d'une liaison, isolée derrière un provider.
///
/// Seule couture de test du temps réel : c'est par ces sockets que
/// transitent les confirmations d'opérations et les marks de position,
/// donc les chemins qu'il faut pouvoir éprouver sans serveur.
typedef RealtimeChannelFactory = WebSocketChannel Function(
  Uri uri,
  List<String> protocols,
);

final realtimeChannelFactoryProvider = Provider<RealtimeChannelFactory>(
  (_) => (uri, protocols) =>
      WebSocketChannel.connect(uri, protocols: protocols),
);

/// Liaison temps réel : connexion, reconnexion, décodage.
///
/// Transport uniquement. Chaque canal a son propre protocole applicatif
/// — Leo parle en `{type: …}`, le portefeuille en `{event, payload}` —
/// et c'est à l'appelant de l'interpréter. Ce qui se mutualise, c'est ce
/// qui se répétait mot pour mot : le sous-protocole JWT, le refus
/// d'ouvrir sans jeton, les délais croissants, le démontage propre.
class RealtimeConnection {
  RealtimeConnection({
    required this.path,
    required RealtimeChannelFactory connect,
    required String? Function() accessToken,
    required void Function(RealtimeStatus status, String? error) onStatus,
    required void Function(Map<String, dynamic> message) onMessage,
  })  : _connect = connect,
        _accessToken = accessToken,
        _onStatus = onStatus,
        _onMessage = onMessage;

  /// Chemin absolu, par exemple `/ws/portfolio/3/`.
  final String path;

  final RealtimeChannelFactory _connect;
  final String? Function() _accessToken;
  final void Function(RealtimeStatus, String?) _onStatus;
  final void Function(Map<String, dynamic>) _onMessage;

  WebSocketChannel? _channel;
  StreamSubscription<dynamic>? _subscription;
  Timer? _reconnect;
  int _attempts = 0;
  bool _disposed = false;

  bool get isOpen => _channel != null;

  void open() {
    if (_disposed) return;
    _reconnect?.cancel();

    final token = _accessToken();
    if (token == null || token.isEmpty) {
      // Ouvrir une connexion vouée au refus produirait une boucle de
      // reconnexion silencieuse.
      _onStatus(RealtimeStatus.lost, 'Session expirée. Reconnecte-toi.');
      return;
    }

    _onStatus(RealtimeStatus.connecting, null);

    try {
      // Le jeton voyage dans le sous-protocole, pas dans l'URL : une
      // chaîne de requête se retrouve dans les journaux d'accès du
      // serveur, des proxies et des CDN, bien au-delà de sa validité.
      final channel = _connect(
        Uri.parse('${Env.wsBaseUrl}$path'),
        [kJwtSubprotocol, token],
      );
      _channel = channel;
      _subscription = channel.stream.listen(
        _decode,
        onError: (_) => _dropped('Connexion interrompue.'),
        onDone: () => _dropped(null),
        cancelOnError: true,
      );
      _attempts = 0;
      _onStatus(RealtimeStatus.online, null);
    } catch (_) {
      _dropped('Liaison impossible.');
    }
  }

  /// Envoie un message. Retourne false si rien n'est parti.
  bool send(Map<String, dynamic> message) {
    final channel = _channel;
    if (channel == null) return false;
    try {
      channel.sink.add(jsonEncode(message));
      return true;
    } catch (_) {
      // Écrire dans un sink fermé ne lève pas toujours : sans ce filet,
      // le message passerait pour envoyé.
      _dropped('Message non transmis.');
      return false;
    }
  }

  void _decode(dynamic raw) {
    try {
      final decoded = jsonDecode(raw as String);
      if (decoded is Map<String, dynamic>) _onMessage(decoded);
    } catch (_) {
      // Un message illisible ne doit pas faire tomber la liaison.
    }
  }

  void _dropped(String? error) {
    _subscription?.cancel();
    _subscription = null;
    _channel = null;
    if (_disposed) return;
    _onStatus(RealtimeStatus.lost, error);
    _schedule();
  }

  void _schedule() {
    _reconnect?.cancel();
    final index = _attempts < kReconnectDelays.length
        ? _attempts
        : kReconnectDelays.length - 1;
    _attempts++;
    _reconnect = Timer(Duration(seconds: kReconnectDelays[index]), open);
  }

  void dispose() {
    _disposed = true;
    _reconnect?.cancel();
    _reconnect = null;
    _subscription?.cancel();
    _channel?.sink.close();
    _subscription = null;
    _channel = null;
  }
}
