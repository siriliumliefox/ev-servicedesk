// Бейдж статуса агрегата «светофор» (Глава 5 — алгоритм, Глава 6 — дизайн-система).
// Статус передаётся цветом, формой иконки и подписью (ТЗ раздел 6: «не только цветом»).
// Подписи совпадают с web-shared/src/StatusBadge.tsx и глоссарием.
import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

/// Значения AggregateStatus.status из OpenAPI.
enum AggregateStatus { green, yellow, red, unknown }

extension AggregateStatusView on AggregateStatus {
  String get label => switch (this) {
        AggregateStatus.green => 'Заменено',
        AggregateStatus.yellow => 'Скоро менять',
        AggregateStatus.red => 'Требуется замена',
        AggregateStatus.unknown => 'Нет данных',
      };

  /// Своя форма у каждого статуса: круг с галочкой, треугольник, восьмиугольник, круг с вопросом.
  IconData get icon => switch (this) {
        AggregateStatus.green => Icons.check_circle_outline,
        AggregateStatus.yellow => Icons.warning_amber_rounded,
        AggregateStatus.red => Icons.dangerous_outlined,
        AggregateStatus.unknown => Icons.help_outline,
      };

  /// (фон, текст/иконка, заливка для схемы авто).
  (Color, Color, Color) colors(EvColors c) => switch (this) {
        AggregateStatus.green => (c.statusGreenBg, c.statusGreenFg, c.statusGreenSolid),
        AggregateStatus.yellow => (c.statusYellowBg, c.statusYellowFg, c.statusYellowSolid),
        AggregateStatus.red => (c.statusRedBg, c.statusRedFg, c.statusRedSolid),
        AggregateStatus.unknown => (c.statusUnknownBg, c.statusUnknownFg, c.statusUnknownSolid),
      };
}

class StatusBadge extends StatelessWidget {
  const StatusBadge({super.key, required this.status});

  final AggregateStatus status;

  @override
  Widget build(BuildContext context) {
    final (bg, fg, _) = status.colors(context.evColors);
    return Container(
      padding: const EdgeInsets.fromLTRB(EvSpace.s2, EvSpace.s1, EvSpace.s3, EvSpace.s1),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: const BorderRadius.all(Radius.circular(EvRadius.full)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(status.icon, size: EvSize.iconMd, color: fg),
          const SizedBox(width: EvSpace.s2),
          Text(status.label, style: EvTypeMobile.bodySm.copyWith(color: fg, fontWeight: FontWeight.w600)),
        ],
      ),
    );
  }
}
