import 'package:intl/intl.dart';

/// Formatage des montants.
///
/// Les valeurs arrivent en `String` depuis l'API, car le backend calcule en
/// `Decimal` et Dart n'a pas d'équivalent natif. On ne parse en `double` qu'au
/// tout dernier moment, pour l'affichage — jamais pour un calcul.
String formatMoney(String? raw, String currency) {
  if (raw == null || raw.isEmpty) return '—';
  final value = double.tryParse(raw);
  if (value == null) return '—';
  return NumberFormat.currency(locale: 'fr_FR', name: currency, decimalDigits: 2)
      .format(value);
}

String formatPercent(String? raw, {int digits = 2}) {
  if (raw == null || raw.isEmpty) return '—';
  final value = double.tryParse(raw);
  if (value == null) return '—';
  return '${NumberFormat.decimalPatternDigits(locale: 'fr_FR', decimalDigits: digits).format(value)} %';
}

/// Signe d'une variation, pour choisir la couleur sémantique.
enum MoveSign { gain, loss, flat }

MoveSign signOf(String? raw) {
  final value = double.tryParse(raw ?? '');
  if (value == null || value == 0) return MoveSign.flat;
  return value > 0 ? MoveSign.gain : MoveSign.loss;
}
