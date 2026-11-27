import 'dart:async';
import 'dart:convert';

import 'package:stream_channel/stream_channel.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

/// Socket pilotée par le test : on pousse les messages du serveur, et on
/// lit ce que le client envoie.
///
/// Partagée par les tests de Leo et ceux du portefeuille : les deux
/// canaux passent par la même `RealtimeConnection`, autant éprouver la
/// même fausse socket.
class FakeChannel extends StreamChannelMixin<dynamic>
    implements WebSocketChannel {
  FakeChannel() : _incoming = StreamController<dynamic>();

  final StreamController<dynamic> _incoming;

  /// Ce que le client a envoyé, décodé.
  final List<Map<String, dynamic>> sent = [];

  bool closed = false;

  void push(Map<String, dynamic> event) => _incoming.add(jsonEncode(event));

  /// Pousse une charge illisible, pour vérifier qu'elle ne fait pas
  /// tomber la liaison.
  void pushRaw(String raw) => _incoming.add(raw);

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
  final FakeChannel _channel;

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
