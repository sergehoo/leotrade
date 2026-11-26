import 'dart:async';

import 'package:dio/dio.dart';

import '../config/env.dart';
import 'token_store.dart';

/// Erreur d'API normalisée, prête à l'affichage. Jamais de message inventé :
/// quand le serveur en fournit un, c'est le sien qui est montré.
class ApiError implements Exception {
  const ApiError(this.message, {this.code, this.statusCode, this.fields});

  final String message;
  final String? code;
  final int? statusCode;
  final Map<String, List<String>>? fields;

  @override
  String toString() => message;
}

class ApiClient {
  ApiClient({required TokenStore tokenStore, Dio? dio, Dio? refreshDio})
      : _tokens = tokenStore,
        _dio = dio ?? Dio(),
        // Client distinct pour le rafraîchissement : il ne doit PAS passer
        // par l'intercepteur, sinon un refresh refusé en 401 relancerait un
        // refresh, en boucle. Injectable pour que le test puisse distinguer
        // « le refresh a échoué » de « le rejeu a échoué ».
        _refreshClient = refreshDio ?? Dio() {
    _dio.options
      ..baseUrl = Env.apiV1
      ..connectTimeout = const Duration(seconds: 15)
      ..receiveTimeout = const Duration(seconds: 30)
      ..headers['Content-Type'] = 'application/json';

    _dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          final token = _tokens.accessToken;
          if (token != null) {
            options.headers['Authorization'] = 'Bearer $token';
          }
          handler.next(options);
        },
        onError: _onError,
      ),
    );
  }

  final Dio _dio;
  final Dio _refreshClient;
  final TokenStore _tokens;

  /// Appelé quand la session est définitivement perdue.
  void Function()? onSessionExpired;

  /// Routes où un 401 signifie « identifiants refusés », pas « jeton expiré ».
  /// `/auth/me/` n'en fait volontairement PAS partie : c'est l'appel qui
  /// restaure la session au démarrage, et il doit pouvoir déclencher un
  /// rafraîchissement.
  static const _noRefresh = {'/auth/login/', '/auth/login/mfa/', '/auth/refresh/'};

  /// Un seul rafraîchissement en vol. La rotation étant active côté serveur,
  /// plusieurs refresh concurrents présenteraient le même jeton, déjà
  /// consommé pour tous sauf un — et feraient tomber la session.
  Future<String>? _refreshInFlight;

  Future<void> _onError(DioException error, ErrorInterceptorHandler handler) async {
    final request = error.requestOptions;
    final isCredentialRoute = _noRefresh.any(request.path.startsWith);
    final alreadyRetried = request.extra['retried'] == true;

    if (error.response?.statusCode != 401 || isCredentialRoute || alreadyRetried) {
      return handler.next(error);
    }

    // ── 1. Rafraîchir ──────────────────────────────────────────────────
    // Échouer ICI signifie que le refresh token ne vaut plus rien : la
    // session est perdue, il faut la fermer.
    final String token;
    final inFlight = _refreshInFlight ??= _refreshAccessToken();
    try {
      token = await inFlight;
    } catch (_) {
      await _tokens.clear();
      onSessionExpired?.call();
      return handler.next(error);
    } finally {
      // Ne remettre à null que SI c'est toujours le même rafraîchissement :
      // sinon on effacerait celui qu'un autre appel vient de démarrer.
      if (identical(_refreshInFlight, inFlight)) _refreshInFlight = null;
    }

    // ── 2. Rejouer ─────────────────────────────────────────────────────
    // Échouer ici ne dit RIEN sur la session : un 500, une coupure réseau
    // ou un délai dépassé sur le rejeu sont des accidents de la requête,
    // pas du jeton. Les traiter comme une session perdue déconnecterait
    // l'utilisateur — et sur une plateforme de trading, se retrouver
    // devant un écran de connexion avec une position ouverte n'est pas un
    // désagrément, c'est une impossibilité d'agir.
    request.extra['retried'] = true;
    request.headers['Authorization'] = 'Bearer $token';
    try {
      return handler.resolve(await _dio.fetch(request));
    } on DioException catch (replayFailure) {
      return handler.next(replayFailure);
    }
  }

  Future<String> _refreshAccessToken() async {
    final refresh = await _tokens.readRefreshToken();
    if (refresh == null) throw const ApiError('Session expirée.');

    final response = await _refreshClient.post<Map<String, dynamic>>(
      '${Env.apiV1}/auth/refresh/',
      data: {'refresh': refresh},
      options: Options(headers: {'Content-Type': 'application/json'}),
    );

    final access = response.data?['access'] as String?;
    if (access == null) throw const ApiError('Réponse de rafraîchissement invalide.');
    _tokens.accessToken = access;

    // Rotation active : stocker le nouveau refresh, sinon la session suivante
    // présentera un jeton révoqué.
    final rotated = response.data?['refresh'] as String?;
    if (rotated != null) await _tokens.writeRefreshToken(rotated);
    return access;
  }

  Future<T> get<T>(String path, {Map<String, dynamic>? query}) async {
    return _unwrap(() => _dio.get<T>(path, queryParameters: query));
  }

  Future<T> post<T>(String path, {Object? data}) async {
    return _unwrap(() => _dio.post<T>(path, data: data));
  }

  Future<T> patch<T>(String path, {Object? data}) async {
    return _unwrap(() => _dio.patch<T>(path, data: data));
  }

  /// DELETE renvoie 204 sans corps : le type de retour est volontairement
  /// `void`, un `_unwrap<T>` castant `null` en `T` échouerait.
  Future<void> delete(String path) async {
    try {
      await _dio.delete<void>(path);
    } on DioException catch (error) {
      throw toApiError(error);
    }
  }

  Future<T> _unwrap<T>(Future<Response<T>> Function() call) async {
    try {
      final response = await call();
      return response.data as T;
    } on DioException catch (error) {
      throw toApiError(error);
    }
  }

  static ApiError toApiError(DioException error) {
    switch (error.type) {
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.receiveTimeout:
      case DioExceptionType.sendTimeout:
        return const ApiError('Le serveur met trop de temps à répondre.');
      case DioExceptionType.connectionError:
        return const ApiError('Serveur injoignable. Vérifiez votre connexion.');
      default:
        break;
    }

    final status = error.response?.statusCode;
    if (status == 429) {
      return const ApiError(
        'Trop de tentatives. Réessayez dans un instant.',
        code: 'THROTTLED',
        statusCode: 429,
      );
    }

    final data = error.response?.data;
    if (data is Map) {
      final detail = data['detail'];
      if (detail is String) {
        return ApiError(detail, code: data['code'] as String?, statusCode: status);
      }

      // Erreurs de validation DRF : {champ: ["message", …]}
      final fields = <String, List<String>>{};
      data.forEach((key, value) {
        if (value is List) {
          fields['$key'] = value.map((item) => '$item').toList();
        } else if (value is String) {
          fields['$key'] = [value];
        }
      });
      if (fields.isNotEmpty) {
        return ApiError(
          fields.values.first.first,
          statusCode: status,
          fields: fields,
        );
      }
    }

    return ApiError('Erreur ${status ?? ''}'.trim(), statusCode: status);
  }
}
