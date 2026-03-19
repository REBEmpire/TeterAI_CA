import 'package:flutter/material.dart';

/// Teter brand design tokens for the Flutter mobile app.
/// Colors sourced from teterae.com inspection.
class TeterColors {
  TeterColors._();

  static const Color orange = Color(0xFFD06F1A);       // Primary brand orange
  static const Color orangeDark = Color(0xFFB35E14);   // Hover/pressed
  static const Color orangeLight = Color(0xFFE8892A);  // Light variant
  static const Color dark = Color(0xFF313131);          // Nav/header bg
  static const Color darkSoft = Color(0xFF3D3D3D);
  static const Color white = Color(0xFFFFFFFF);
  static const Color lightGray = Color(0xFFEEEEEE);
  static const Color grayMid = Color(0xFFD4D4D4);
  static const Color grayText = Color(0xFF6B6B6B);

  // Confidence score
  static const Color confidenceHigh = Color(0xFF2E7D32);  // ≥ 0.80
  static const Color confidenceMid = Color(0xFFF9A825);   // 0.50–0.79
  static const Color confidenceLow = Color(0xFFC62828);   // < 0.50

  // Urgency badges
  static const Color urgencyHigh = Color(0xFFC62828);
  static const Color urgencyMedium = Color(0xFFE65100);
  static const Color urgencyLow = Color(0xFF757575);
  static const Color urgencyHighBg = Color(0xFFFFEBEE);
  static const Color urgencyMediumBg = Color(0xFFFFF3E0);
  static const Color urgencyLowBg = Color(0xFFF5F5F5);

  /// Returns the appropriate confidence color for a 0.0–1.0 score.
  static Color forConfidence(double score) {
    if (score >= 0.8) return confidenceHigh;
    if (score >= 0.5) return confidenceMid;
    return confidenceLow;
  }
}

/// The root ThemeData for TeterAI mobile, using the Teter brand palette.
final ThemeData teterTheme = ThemeData(
  useMaterial3: true,
  colorScheme: ColorScheme.fromSeed(
    seedColor: TeterColors.orange,
    primary: TeterColors.orange,
    onPrimary: Colors.white,
    secondary: TeterColors.dark,
    onSecondary: Colors.white,
    surface: Colors.white,
    onSurface: TeterColors.dark,
    surfaceContainerHighest: TeterColors.lightGray,
    error: TeterColors.confidenceLow,
  ),
  scaffoldBackgroundColor: const Color(0xFFF7F7F7),
  appBarTheme: const AppBarTheme(
    backgroundColor: TeterColors.dark,
    foregroundColor: Colors.white,
    elevation: 2,
    titleTextStyle: TextStyle(
      fontFamily: 'Arial',
      fontSize: 16,
      fontWeight: FontWeight.w600,
      color: Colors.white,
    ),
  ),
  textTheme: const TextTheme(
    headlineSmall: TextStyle(
      fontFamily: 'Arial',
      fontWeight: FontWeight.w600,
      color: TeterColors.dark,
    ),
    titleMedium: TextStyle(
      fontFamily: 'Arial',
      fontWeight: FontWeight.w600,
      color: TeterColors.dark,
    ),
    bodyMedium: TextStyle(
      fontFamily: 'Arial',
      color: TeterColors.dark,
    ),
    bodySmall: TextStyle(
      fontFamily: 'Arial',
      color: TeterColors.grayText,
    ),
  ),
  elevatedButtonTheme: ElevatedButtonThemeData(
    style: ElevatedButton.styleFrom(
      backgroundColor: TeterColors.orange,
      foregroundColor: Colors.white,
      textStyle: const TextStyle(
        fontFamily: 'Arial',
        fontWeight: FontWeight.w600,
      ),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
    ),
  ),
  outlinedButtonTheme: OutlinedButtonThemeData(
    style: OutlinedButton.styleFrom(
      foregroundColor: TeterColors.dark,
      side: const BorderSide(color: TeterColors.grayMid),
      textStyle: const TextStyle(
        fontFamily: 'Arial',
        fontWeight: FontWeight.w600,
      ),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
    ),
  ),
  inputDecorationTheme: InputDecorationTheme(
    border: OutlineInputBorder(
      borderRadius: BorderRadius.circular(6),
      borderSide: const BorderSide(color: TeterColors.grayMid),
    ),
    focusedBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(6),
      borderSide: const BorderSide(color: TeterColors.orange, width: 2),
    ),
    contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
  ),
  cardTheme: CardTheme(
    elevation: 1,
    color: Colors.white,
    shape: RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(8),
      side: const BorderSide(color: TeterColors.grayMid),
    ),
    margin: const EdgeInsets.symmetric(vertical: 4),
  ),
  tabBarTheme: const TabBarTheme(
    labelColor: TeterColors.orange,
    unselectedLabelColor: TeterColors.grayText,
    indicatorColor: TeterColors.orange,
    indicatorSize: TabBarIndicatorSize.tab,
    labelStyle: TextStyle(fontFamily: 'Arial', fontWeight: FontWeight.w600),
  ),
  dividerColor: TeterColors.grayMid,
);
