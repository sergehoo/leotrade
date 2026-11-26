import '../../../core/network/api_client.dart';
import '../../../core/network/token_store.dart';
import '../domain/models.dart';

class AuthRepository {
  AuthRepository({required ApiClient client, required TokenStore tokens})
      : _client = client,
        _tokens = tokens;

  final ApiClient _client;
  final TokenStore _tokens;

  Future<LoginResult> login(String email, String password) async {
    final data = await _client.post<Map<String, dynamic>>(
      '/auth/login/',
      data: {'email': email.trim(), 'password': password},
    );

    // Le serveur impose un second facteur : aucun jeton n'est délivré ici.
    if (data['mfa_required'] == true) {
      return MfaRequired(data['mfa_token'] as String);
    }
    return LoginSucceeded(await _persist(data));
  }

  Future<CurrentUser> submitMfa(String mfaToken, String code) async {
    final data = await _client.post<Map<String, dynamic>>(
      '/auth/login/mfa/',
      data: {'mfa_token': mfaToken, 'code': code.trim()},
    );
    return _persist(data);
  }

  Future<CurrentUser> me() async {
    final data = await _client.get<Map<String, dynamic>>('/auth/me/');
    return CurrentUser.fromJson(data);
  }

  Future<void> logout() async {
    final refresh = await _tokens.readRefreshToken();
    if (refresh != null) {
      try {
        // Révocation serveur : sans cet appel, supprimer le jeton localement
        // le laisserait valide quatorze jours pour qui l'aurait intercepté.
        await _client.post<dynamic>('/auth/logout/', data: {'refresh': refresh});
      } on ApiError {
        /* déjà révoqué ou expiré : la déconnexion locale reste légitime */
      }
    }
    await _tokens.clear();
  }

  /// Tente de reprendre la session au lancement.
  ///
  /// Le jeton n'est effacé que si le SERVEUR l'a refusé. Une panne réseau,
  /// un délai dépassé ou un 5xx ne disent rien sur sa validité : les
  /// traiter comme une session perdue obligeait à ressaisir son mot de
  /// passe pour une coupure de réseau — y compris avec une position
  /// ouverte à surveiller.
  Future<RestoreResult> restore() async {
    if (await _tokens.readRefreshToken() == null) return const NoSession();
    try {
      // L'access n'est pas persisté : le premier appel part sans en-tête,
      // reçoit un 401, et l'intercepteur rafraîchit.
      return SessionRestored(await me());
    } on ApiError catch (error) {
      final status = error.statusCode;

      // Pas de code HTTP : la requête n'a pas abouti (réseau, délai).
      // Un 5xx n'est pas davantage un verdict sur le jeton.
      if (status == null || status >= 500) {
        return RestoreUnavailable(error.message);
      }

      await _tokens.clear();
      return const NoSession();
    }
  }

  Future<CurrentUser> _persist(Map<String, dynamic> data) async {
    _tokens.accessToken = data['access'] as String;
    await _tokens.writeRefreshToken(data['refresh'] as String);
    return CurrentUser.fromJson(data['user'] as Map<String, dynamic>);
  }
}
