import 'package:flutter/material.dart';

/// Thème LeoTrade — miroir de web/src/index.css.
///
/// Même règle que sur le web : le vert et le rouge sont réservés au P&L et
/// aux états de risque. Un vert décoratif rendrait illisible la seule
/// information qui compte dans un écran de trading — gagne-t-on ou perd-on.
class AppColors {
  const AppColors._();

  static const background = Color(0xFF080D16);
  static const surface = Color(0xFF0E1522);
  static const surfaceHigh = Color(0xFF161F30);
  static const border = Color(0xFF1E293B);

  static const primary = Color(0xFF26BFA6);
  static const onPrimary = Color(0xFF07121A);

  static const foreground = Color(0xFFEFF4F9);
  static const muted = Color(0xFF8C9BB0);

  /// Sémantique financière.
  static const gain = Color(0xFF2BBF84);
  static const loss = Color(0xFFE2504F);
  static const flat = Color(0xFF8C9BB0);
  static const warning = Color(0xFFF59E0B);
  static const info = Color(0xFF4A90E8);

  /// Paliers d'instrument — cf. backend/risk/instruments.py
  static const tierCore = primary;
  static const tierVolatile = warning;
  static const tierSpeculative = loss;
}

ThemeData buildAppTheme() {
  const scheme = ColorScheme.dark(
    primary: AppColors.primary,
    onPrimary: AppColors.onPrimary,
    surface: AppColors.surface,
    onSurface: AppColors.foreground,
    error: AppColors.loss,
    outline: AppColors.border,
  );

  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: AppColors.background,
    textTheme: const TextTheme(
      // Les chiffres financiers s'alignent en colonne : chasse tabulaire.
      bodyLarge: TextStyle(fontFeatures: [FontFeature.tabularFigures()]),
      bodyMedium: TextStyle(fontFeatures: [FontFeature.tabularFigures()]),
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: AppColors.background,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      centerTitle: false,
    ),
    cardTheme: CardThemeData(
      color: AppColors.surface,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: const BorderSide(color: AppColors.border),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: AppColors.surfaceHigh,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: AppColors.border),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: AppColors.border),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: AppColors.primary, width: 2),
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size.fromHeight(48),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      ),
    ),
    dividerTheme: const DividerThemeData(color: AppColors.border, space: 1),
  );
}
