/// Configuration d'environnement, injectée à la compilation.
///
///   flutter run --dart-define=API_BASE_URL=https://staging.leotrade.com
///
/// Aucune valeur de production n'est codée en dur : une URL oubliée dans le
/// binaire est une fuite, et un build de test pointant sur la production est
/// un risque d'ordre réel.
class Env {
  const Env._();

  /// Par défaut l'émulateur Android : 10.0.2.2 est l'hôte vu depuis la VM.
  static const String apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://10.0.2.2:8000',
  );

  static String get apiV1 => '$apiBaseUrl/api/v1';

  static String get wsBaseUrl =>
      apiBaseUrl.replaceFirst(RegExp(r'^http'), 'ws');

  static const bool isProduction = bool.fromEnvironment('dart.vm.product');
}
