// СГЕНЕРИРОВАНО scripts/design_tokens.mts из design/tokens.json — не редактировать.
// Обновление: npm run tokens. Глава 6, ADR 0010.
import 'package:flutter/material.dart';

/// Семантические цвета темы (design/tokens.json → theme.*).
@immutable
class EvColors extends ThemeExtension<EvColors> {
  const EvColors({
    required this.canvas,
    required this.surface,
    required this.surfaceSubtle,
    required this.fg,
    required this.fgMuted,
    required this.fgDisabled,
    required this.border,
    required this.borderStrong,
    required this.primary,
    required this.primaryHover,
    required this.onPrimary,
    required this.primaryText,
    required this.focusRing,
    required this.danger,
    required this.dangerHover,
    required this.onDanger,
    required this.dangerText,
    required this.infoText,
    required this.statusGreenBg,
    required this.statusGreenFg,
    required this.statusGreenSolid,
    required this.statusYellowBg,
    required this.statusYellowFg,
    required this.statusYellowSolid,
    required this.statusRedBg,
    required this.statusRedFg,
    required this.statusRedSolid,
    required this.statusUnknownBg,
    required this.statusUnknownFg,
    required this.statusUnknownSolid,
  });

  final Color canvas;
  final Color surface;
  final Color surfaceSubtle;
  final Color fg;
  final Color fgMuted;
  final Color fgDisabled;
  final Color border;
  final Color borderStrong;
  final Color primary;
  final Color primaryHover;
  final Color onPrimary;
  final Color primaryText;
  final Color focusRing;
  final Color danger;
  final Color dangerHover;
  final Color onDanger;
  final Color dangerText;
  final Color infoText;
  final Color statusGreenBg;
  final Color statusGreenFg;
  final Color statusGreenSolid;
  final Color statusYellowBg;
  final Color statusYellowFg;
  final Color statusYellowSolid;
  final Color statusRedBg;
  final Color statusRedFg;
  final Color statusRedSolid;
  final Color statusUnknownBg;
  final Color statusUnknownFg;
  final Color statusUnknownSolid;

  @override
  EvColors copyWith({
    Color? canvas,
    Color? surface,
    Color? surfaceSubtle,
    Color? fg,
    Color? fgMuted,
    Color? fgDisabled,
    Color? border,
    Color? borderStrong,
    Color? primary,
    Color? primaryHover,
    Color? onPrimary,
    Color? primaryText,
    Color? focusRing,
    Color? danger,
    Color? dangerHover,
    Color? onDanger,
    Color? dangerText,
    Color? infoText,
    Color? statusGreenBg,
    Color? statusGreenFg,
    Color? statusGreenSolid,
    Color? statusYellowBg,
    Color? statusYellowFg,
    Color? statusYellowSolid,
    Color? statusRedBg,
    Color? statusRedFg,
    Color? statusRedSolid,
    Color? statusUnknownBg,
    Color? statusUnknownFg,
    Color? statusUnknownSolid,
  }) {
    return EvColors(
      canvas: canvas ?? this.canvas,
      surface: surface ?? this.surface,
      surfaceSubtle: surfaceSubtle ?? this.surfaceSubtle,
      fg: fg ?? this.fg,
      fgMuted: fgMuted ?? this.fgMuted,
      fgDisabled: fgDisabled ?? this.fgDisabled,
      border: border ?? this.border,
      borderStrong: borderStrong ?? this.borderStrong,
      primary: primary ?? this.primary,
      primaryHover: primaryHover ?? this.primaryHover,
      onPrimary: onPrimary ?? this.onPrimary,
      primaryText: primaryText ?? this.primaryText,
      focusRing: focusRing ?? this.focusRing,
      danger: danger ?? this.danger,
      dangerHover: dangerHover ?? this.dangerHover,
      onDanger: onDanger ?? this.onDanger,
      dangerText: dangerText ?? this.dangerText,
      infoText: infoText ?? this.infoText,
      statusGreenBg: statusGreenBg ?? this.statusGreenBg,
      statusGreenFg: statusGreenFg ?? this.statusGreenFg,
      statusGreenSolid: statusGreenSolid ?? this.statusGreenSolid,
      statusYellowBg: statusYellowBg ?? this.statusYellowBg,
      statusYellowFg: statusYellowFg ?? this.statusYellowFg,
      statusYellowSolid: statusYellowSolid ?? this.statusYellowSolid,
      statusRedBg: statusRedBg ?? this.statusRedBg,
      statusRedFg: statusRedFg ?? this.statusRedFg,
      statusRedSolid: statusRedSolid ?? this.statusRedSolid,
      statusUnknownBg: statusUnknownBg ?? this.statusUnknownBg,
      statusUnknownFg: statusUnknownFg ?? this.statusUnknownFg,
      statusUnknownSolid: statusUnknownSolid ?? this.statusUnknownSolid,
    );
  }

  @override
  EvColors lerp(ThemeExtension<EvColors>? other, double t) {
    if (other is! EvColors) return this;
    return EvColors(
      canvas: Color.lerp(canvas, other.canvas, t)!,
      surface: Color.lerp(surface, other.surface, t)!,
      surfaceSubtle: Color.lerp(surfaceSubtle, other.surfaceSubtle, t)!,
      fg: Color.lerp(fg, other.fg, t)!,
      fgMuted: Color.lerp(fgMuted, other.fgMuted, t)!,
      fgDisabled: Color.lerp(fgDisabled, other.fgDisabled, t)!,
      border: Color.lerp(border, other.border, t)!,
      borderStrong: Color.lerp(borderStrong, other.borderStrong, t)!,
      primary: Color.lerp(primary, other.primary, t)!,
      primaryHover: Color.lerp(primaryHover, other.primaryHover, t)!,
      onPrimary: Color.lerp(onPrimary, other.onPrimary, t)!,
      primaryText: Color.lerp(primaryText, other.primaryText, t)!,
      focusRing: Color.lerp(focusRing, other.focusRing, t)!,
      danger: Color.lerp(danger, other.danger, t)!,
      dangerHover: Color.lerp(dangerHover, other.dangerHover, t)!,
      onDanger: Color.lerp(onDanger, other.onDanger, t)!,
      dangerText: Color.lerp(dangerText, other.dangerText, t)!,
      infoText: Color.lerp(infoText, other.infoText, t)!,
      statusGreenBg: Color.lerp(statusGreenBg, other.statusGreenBg, t)!,
      statusGreenFg: Color.lerp(statusGreenFg, other.statusGreenFg, t)!,
      statusGreenSolid: Color.lerp(statusGreenSolid, other.statusGreenSolid, t)!,
      statusYellowBg: Color.lerp(statusYellowBg, other.statusYellowBg, t)!,
      statusYellowFg: Color.lerp(statusYellowFg, other.statusYellowFg, t)!,
      statusYellowSolid: Color.lerp(statusYellowSolid, other.statusYellowSolid, t)!,
      statusRedBg: Color.lerp(statusRedBg, other.statusRedBg, t)!,
      statusRedFg: Color.lerp(statusRedFg, other.statusRedFg, t)!,
      statusRedSolid: Color.lerp(statusRedSolid, other.statusRedSolid, t)!,
      statusUnknownBg: Color.lerp(statusUnknownBg, other.statusUnknownBg, t)!,
      statusUnknownFg: Color.lerp(statusUnknownFg, other.statusUnknownFg, t)!,
      statusUnknownSolid: Color.lerp(statusUnknownSolid, other.statusUnknownSolid, t)!,
    );
  }
}

const EvColors evColorsLight = EvColors(
  canvas: Color(0xFFFAFAFA),
  surface: Color(0xFFFFFFFF),
  surfaceSubtle: Color(0xFFF4F4F5),
  fg: Color(0xFF171717),
  fgMuted: Color(0xFF52525B),
  fgDisabled: Color(0xFFA1A1AA),
  border: Color(0xFFE4E4E7),
  borderStrong: Color(0xFF71717A),
  primary: Color(0xFFF9CE12),
  primaryHover: Color(0xFFE6BC00),
  onPrimary: Color(0xFF171717),
  primaryText: Color(0xFF7A5C00),
  focusRing: Color(0xFF171717),
  danger: Color(0xFFB91C1C),
  dangerHover: Color(0xFF991B1B),
  onDanger: Color(0xFFFFFFFF),
  dangerText: Color(0xFFB91C1C),
  infoText: Color(0xFF004F91),
  statusGreenBg: Color(0xFFDCFCE7),
  statusGreenFg: Color(0xFF166534),
  statusGreenSolid: Color(0xFF15803D),
  statusYellowBg: Color(0xFFFEF3C7),
  statusYellowFg: Color(0xFF92400E),
  statusYellowSolid: Color(0xFFB86E00),
  statusRedBg: Color(0xFFFEE2E2),
  statusRedFg: Color(0xFF991B1B),
  statusRedSolid: Color(0xFFDC2626),
  statusUnknownBg: Color(0xFFF4F4F5),
  statusUnknownFg: Color(0xFF3F3F46),
  statusUnknownSolid: Color(0xFF71717A),
);

const EvColors evColorsDark = EvColors(
  canvas: Color(0xFF0F0F10),
  surface: Color(0xFF18181B),
  surfaceSubtle: Color(0xFF27272A),
  fg: Color(0xFFF4F4F5),
  fgMuted: Color(0xFFA1A1AA),
  fgDisabled: Color(0xFF52525B),
  border: Color(0xFF3F3F46),
  borderStrong: Color(0xFF71717A),
  primary: Color(0xFFF9CE12),
  primaryHover: Color(0xFFFFD83D),
  onPrimary: Color(0xFF171717),
  primaryText: Color(0xFFF9CE12),
  focusRing: Color(0xFFF9CE12),
  danger: Color(0xFFF87171),
  dangerHover: Color(0xFFFCA5A5),
  onDanger: Color(0xFF171717),
  dangerText: Color(0xFFF87171),
  infoText: Color(0xFF60A5FA),
  statusGreenBg: Color(0xFF052E16),
  statusGreenFg: Color(0xFF86EFAC),
  statusGreenSolid: Color(0xFF22C55E),
  statusYellowBg: Color(0xFF451A03),
  statusYellowFg: Color(0xFFFCD34D),
  statusYellowSolid: Color(0xFFF59E0B),
  statusRedBg: Color(0xFF450A0A),
  statusRedFg: Color(0xFFFCA5A5),
  statusRedSolid: Color(0xFFEF4444),
  statusUnknownBg: Color(0xFF27272A),
  statusUnknownFg: Color(0xFFD4D4D8),
  statusUnknownSolid: Color(0xFFA1A1AA),
);

/// Шкала отступов, сетка 4 (space.*).
abstract final class EvSpace {
  static const double s0 = 0;
  static const double s1 = 4;
  static const double s2 = 8;
  static const double s3 = 12;
  static const double s4 = 16;
  static const double s5 = 20;
  static const double s6 = 24;
  static const double s8 = 32;
  static const double s10 = 40;
  static const double s12 = 48;
  static const double s16 = 64;
}

/// Радиусы скругления (radius.*).
abstract final class EvRadius {
  static const double none = 0;
  static const double sm = 4;
  static const double md = 8;
  static const double lg = 12;
  static const double xl = 20;
  static const double full = 9999;
}

/// Размеры: тап-зоны, контролы, иконки (size.*).
abstract final class EvSize {
  static const double tapTargetMin = 44;
  static const double controlMobile = 48;
  static const double controlWeb = 40;
  static const double controlWebSm = 32;
  static const double bottomNav = 64;
  static const double iconSm = 16;
  static const double iconMd = 20;
  static const double iconLg = 24;
}

/// Длительности анимаций (duration.*).
abstract final class EvDuration {
  static const Duration fast = Duration(milliseconds: 120);
  static const Duration normal = Duration(milliseconds: 200);
  static const Duration slow = Duration(milliseconds: 320);
}

/// Типографика мобильного приложения (typography.mobile.*).
/// Шрифт Inter подключается ассетом в главе 18; до этого — системный (SF Pro).
abstract final class EvTypeMobile {
  static const String fontFamily = 'Inter';
  static const TextStyle display = TextStyle(
    fontFamily: fontFamily,
    fontSize: 28,
    height: 1.2143,
    fontWeight: FontWeight.w700,
    letterSpacing: -0.56,
  );
  static const TextStyle h1 = TextStyle(
    fontFamily: fontFamily,
    fontSize: 24,
    height: 1.25,
    fontWeight: FontWeight.w700,
    letterSpacing: -0.24,
  );
  static const TextStyle h2 = TextStyle(
    fontFamily: fontFamily,
    fontSize: 20,
    height: 1.4,
    fontWeight: FontWeight.w600,
    letterSpacing: 0,
  );
  static const TextStyle h3 = TextStyle(
    fontFamily: fontFamily,
    fontSize: 17,
    height: 1.4118,
    fontWeight: FontWeight.w600,
    letterSpacing: 0,
  );
  static const TextStyle body = TextStyle(
    fontFamily: fontFamily,
    fontSize: 16,
    height: 1.5,
    fontWeight: FontWeight.w400,
    letterSpacing: 0,
  );
  static const TextStyle bodySm = TextStyle(
    fontFamily: fontFamily,
    fontSize: 14,
    height: 1.4286,
    fontWeight: FontWeight.w400,
    letterSpacing: 0,
  );
  static const TextStyle label = TextStyle(
    fontFamily: fontFamily,
    fontSize: 16,
    height: 1.25,
    fontWeight: FontWeight.w600,
    letterSpacing: 0,
  );
  static const TextStyle caption = TextStyle(
    fontFamily: fontFamily,
    fontSize: 12,
    height: 1.3333,
    fontWeight: FontWeight.w500,
    letterSpacing: 0.12,
  );
}
