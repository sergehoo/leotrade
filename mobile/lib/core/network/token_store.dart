import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Stockage des jetons.
///
/// Le refresh va dans le Keychain (iOS) / Keystore (Android), jamais dans
/// SharedPreferences : sur un appareil rooté ou jailbreaké, SharedPreferences
/// se lit en clair, et un refresh token vaut un accès complet au compte
/// pendant quatorze jours.
///
/// L'access token reste en mémoire : sa durée de vie est de quinze minutes,
/// le persister ajouterait une surface d'exposition pour un gain nul.
class TokenStore {
  TokenStore({FlutterSecureStorage? storage})
      : _storage = storage ??
            const FlutterSecureStorage(
              aOptions: AndroidOptions(encryptedSharedPreferences: true),
              iOptions: IOSOptions(
                accessibility: KeychainAccessibility.first_unlock_this_device,
              ),
            );

  // Nom historique conservé volontairement malgré le renommage en
  // LeoTrade : cette clé vit dans le Keychain / Keystore de l'appareil.
  // La renommer rendrait le jeton existant introuvable et déconnecterait
  // tout le monde à la première mise à jour.
  static const _refreshKey = 'lyneci.refresh';

  final FlutterSecureStorage _storage;

  /// Jeton d'accès, volontairement non persisté (15 minutes de durée de vie).
  String? accessToken;

  Future<String?> readRefreshToken() async {
    try {
      return await _storage.read(key: _refreshKey);
    } catch (_) {
      // Keystore indisponible (appareil verrouillé, migration) : on dégrade
      // vers une session non persistante plutôt que de planter au démarrage.
      return null;
    }
  }

  Future<void> writeRefreshToken(String? token) async {
    try {
      if (token == null) {
        await _storage.delete(key: _refreshKey);
      } else {
        await _storage.write(key: _refreshKey, value: token);
      }
    } catch (_) {
      /* la session ne survivra pas au redémarrage */
    }
  }

  Future<void> clear() async {
    accessToken = null;
    await writeRefreshToken(null);
  }
}
