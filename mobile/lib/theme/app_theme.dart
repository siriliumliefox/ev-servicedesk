// Тема Material 3 на дизайн-токенах (Глава 6, ADR 0010).
// Цвета, шкалы и размеры — tokens.g.dart (генерируется из design/tokens.json).
import 'package:flutter/material.dart';

import 'tokens.g.dart';

export 'tokens.g.dart';

ThemeData evTheme(Brightness brightness) {
  final c = brightness == Brightness.dark ? evColorsDark : evColorsLight;

  final scheme = ColorScheme(
    brightness: brightness,
    primary: c.primary,
    onPrimary: c.onPrimary,
    secondary: c.primaryText,
    onSecondary: c.surface,
    error: c.danger,
    onError: c.onDanger,
    surface: c.surface,
    onSurface: c.fg,
    onSurfaceVariant: c.fgMuted,
    surfaceContainerHighest: c.surfaceSubtle,
    outline: c.borderStrong,
    outlineVariant: c.border,
  );

  final text = const TextTheme(
    displaySmall: EvTypeMobile.display,
    headlineMedium: EvTypeMobile.h1,
    titleLarge: EvTypeMobile.h2,
    titleMedium: EvTypeMobile.h3,
    bodyLarge: EvTypeMobile.body,
    bodyMedium: EvTypeMobile.bodySm,
    labelLarge: EvTypeMobile.label,
    bodySmall: EvTypeMobile.caption,
    labelSmall: EvTypeMobile.caption,
  ).apply(bodyColor: c.fg, displayColor: c.fg);

  const controlShape = RoundedRectangleBorder(
    borderRadius: BorderRadius.all(Radius.circular(EvRadius.md)),
  );
  const controlSize = Size(EvSize.tapTargetMin, EvSize.controlMobile);
  const controlPadding = EdgeInsets.symmetric(horizontal: EvSpace.s5);

  OutlineInputBorder inputBorder(Color color, [double width = 1]) => OutlineInputBorder(
        borderRadius: const BorderRadius.all(Radius.circular(EvRadius.md)),
        borderSide: BorderSide(color: color, width: width),
      );

  return ThemeData(
    useMaterial3: true,
    brightness: brightness,
    colorScheme: scheme,
    textTheme: text,
    fontFamily: EvTypeMobile.fontFamily,
    scaffoldBackgroundColor: c.canvas,
    // Тап-зона ≥ 44×44 (ТЗ раздел 6): Material расширяет мелкие контролы до 48.
    materialTapTargetSize: MaterialTapTargetSize.padded,
    visualDensity: VisualDensity.standard,
    extensions: [c],
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: c.primary,
        foregroundColor: c.onPrimary,
        disabledBackgroundColor: c.surfaceSubtle,
        disabledForegroundColor: c.fgDisabled,
        minimumSize: controlSize,
        padding: controlPadding,
        shape: controlShape,
        textStyle: EvTypeMobile.label,
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: c.fg,
        side: BorderSide(color: c.borderStrong),
        minimumSize: controlSize,
        padding: controlPadding,
        shape: controlShape,
        textStyle: EvTypeMobile.label,
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: c.primaryText,
        minimumSize: controlSize,
        padding: controlPadding,
        shape: controlShape,
        textStyle: EvTypeMobile.label,
      ),
    ),
    iconButtonTheme: IconButtonThemeData(
      style: IconButton.styleFrom(
        minimumSize: const Size.square(EvSize.tapTargetMin),
        foregroundColor: c.fg,
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: c.surface,
      contentPadding: const EdgeInsets.symmetric(horizontal: EvSpace.s4, vertical: EvSpace.s3),
      constraints: const BoxConstraints(minHeight: EvSize.controlMobile),
      border: inputBorder(c.borderStrong),
      enabledBorder: inputBorder(c.borderStrong),
      focusedBorder: inputBorder(c.focusRing, 2),
      errorBorder: inputBorder(c.dangerText),
      focusedErrorBorder: inputBorder(c.dangerText, 2),
      labelStyle: EvTypeMobile.bodySm.copyWith(color: c.fgMuted),
      hintStyle: EvTypeMobile.body.copyWith(color: c.fgMuted),
      helperStyle: EvTypeMobile.caption.copyWith(color: c.fgMuted),
      errorStyle: EvTypeMobile.caption.copyWith(color: c.dangerText),
    ),
    cardTheme: CardThemeData(
      color: c.surface,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: const BorderRadius.all(Radius.circular(EvRadius.lg)),
        side: BorderSide(color: c.border),
      ),
    ),
    navigationBarTheme: NavigationBarThemeData(
      height: EvSize.bottomNav,
      backgroundColor: c.surface,
      indicatorColor: c.primary,
      surfaceTintColor: Colors.transparent,
      labelTextStyle: WidgetStateProperty.resolveWith(
        (states) => EvTypeMobile.caption.copyWith(
          color: states.contains(WidgetState.selected) ? c.fg : c.fgMuted,
          fontWeight: states.contains(WidgetState.selected) ? FontWeight.w600 : null,
        ),
      ),
      iconTheme: WidgetStateProperty.resolveWith(
        (states) => IconThemeData(
          size: EvSize.iconLg,
          color: states.contains(WidgetState.selected) ? c.onPrimary : c.fgMuted,
        ),
      ),
    ),
    bottomSheetTheme: BottomSheetThemeData(
      backgroundColor: c.surface,
      showDragHandle: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(EvRadius.xl)),
      ),
    ),
    // Выбор категории/фильтра (глава 7): выбранный — брендовая заливка с тёмным текстом, как индикатор навигации.
    chipTheme: ChipThemeData(
      backgroundColor: c.surface,
      selectedColor: c.primary,
      checkmarkColor: c.onPrimary,
      side: WidgetStateBorderSide.resolveWith(
        (states) => BorderSide(color: states.contains(WidgetState.selected) ? c.primary : c.borderStrong),
      ),
      labelStyle: EvTypeMobile.bodySm.copyWith(color: c.fg, fontWeight: FontWeight.w600),
      secondaryLabelStyle: EvTypeMobile.bodySm.copyWith(color: c.onPrimary, fontWeight: FontWeight.w600),
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.all(Radius.circular(EvRadius.md))),
    ),
    // Вкладки: жёлтый на белом — 1.5:1, поэтому текст fg, подчёркивание primary-text (≥ 3:1 в обеих темах).
    tabBarTheme: TabBarThemeData(
      labelColor: c.fg,
      unselectedLabelColor: c.fgMuted,
      indicatorColor: c.primaryText,
      dividerColor: c.border,
      labelStyle: EvTypeMobile.label,
      unselectedLabelStyle: EvTypeMobile.label.copyWith(fontWeight: FontWeight.w500),
    ),
    dividerTheme: DividerThemeData(color: c.border, space: EvSpace.s4, thickness: 1),
    focusColor: c.focusRing.withValues(alpha: 0.12),
  );
}

/// Доступ к семантическим цветам: `context.evColors.statusRedFg`.
extension EvThemeContext on BuildContext {
  EvColors get evColors => Theme.of(this).extension<EvColors>()!;
}
