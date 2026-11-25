import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../../../core/network/token_store.dart';
import '../data/auth_repository.dart';
import '../domain/models.dart';

final tokenStoreProvider = Provider<TokenStore>((ref) => TokenStore());

final apiClientProvider = Provider<ApiClient>((ref) {
  final client = ApiClient(tokenStore: ref.watch(tokenStoreProvider));
  client.onSessionExpired = () {
    ref.read(authControllerProvider.notifier).forceSignOut();
  };
  return client;
});

final authRepositoryProvider = Provider<AuthRepository>(
  (ref) => AuthRepository(
    client: ref.watch(apiClientProvider),
    tokens: ref.watch(tokenStoreProvider),
  ),
);

/// État d'authentification.
///
/// `restoring` est distinct de « déconnecté » : tant que la reprise de
/// session n'a pas tranché, rediriger vers l'écran de connexion
/// déconnecterait l'utilisateur à chaque lancement.
class AuthState {
  const AuthState({this.user, this.mfaToken, this.restoring = true});

  final CurrentUser? user;
  final String? mfaToken;
  final bool restoring;

  bool get isAuthenticated => user != null;
  bool get awaitingMfa => mfaToken != null;

  AuthState copyWith({
    CurrentUser? user,
    String? mfaToken,
    bool? restoring,
    bool clearUser = false,
    bool clearMfa = false,
  }) =>
      AuthState(
        user: clearUser ? null : (user ?? this.user),
        mfaToken: clearMfa ? null : (mfaToken ?? this.mfaToken),
        restoring: restoring ?? this.restoring,
      );
}

final authControllerProvider =
    NotifierProvider<AuthController, AuthState>(AuthController.new);

class AuthController extends Notifier<AuthState> {
  @override
  AuthState build() {
    Future.microtask(restore);
    return const AuthState();
  }

  AuthRepository get _repository => ref.read(authRepositoryProvider);

  Future<void> restore() async {
    final user = await _repository.restore();
    state = AuthState(user: user, restoring: false);
  }

  /// Retourne true si un second facteur est requis.
  Future<bool> signIn(String email, String password) async {
    final result = await _repository.login(email, password);
    switch (result) {
      case MfaRequired(:final mfaToken):
        state = state.copyWith(mfaToken: mfaToken, restoring: false);
        return true;
      case LoginSucceeded(:final user):
        state = AuthState(user: user, restoring: false);
        return false;
    }
  }

  Future<void> submitMfa(String code) async {
    final token = state.mfaToken;
    if (token == null) throw const ApiError('Aucun défi en cours.');
    final user = await _repository.submitMfa(token, code);
    state = AuthState(user: user, restoring: false);
  }

  void cancelMfa() => state = state.copyWith(clearMfa: true);

  Future<void> signOut() async {
    await _repository.logout();
    state = const AuthState(restoring: false);
  }

  /// Session perdue côté serveur : on ne tente pas de révoquer, c'est déjà fait.
  void forceSignOut() => state = const AuthState(restoring: false);
}
