// Интерактивная схема автомобиля (вид сверху, перед — вверху): зоны-агрегаты со статусом «светофор».
// ТЗ раздел 6: читается от 360 px, зона тапа ≥ 44×44; статус — цвет + форма иконки + подпись (Semantics).
import 'package:flutter/material.dart';

import '../../data/models.dart';
import '../../theme/app_theme.dart';
import '../../ui/status_badge.dart';

/// Положение зоны на схеме (доли ширины/высоты). Агрегаты, добавленные в админ-панели
/// без своего места на схеме, показываются только в списке под схемой.
/// Боковые зоны отнесены к краям, чтобы полные названия у центральных зон помещались без перекрытия.
const aggregateSchemePositions = <String, Offset>{
  'ac_refrigerant': Offset(0.5, 0.08),
  'engine_oil': Offset(0.19, 0.16),
  'oil_filter': Offset(0.81, 0.16),
  'air_filter': Offset(0.5, 0.33),
  'cabin_filter': Offset(0.5, 0.53),
  'gearbox_oil': Offset(0.5, 0.82),
};

class AggregateScheme extends StatelessWidget {
  const AggregateScheme({super.key, required this.statuses, required this.onTap});

  final List<AggregateStatusItem> statuses;
  final ValueChanged<AggregateStatusItem> onTap;

  static const _zone = EvSize.controlMobile; // 48 ≥ 44

  /// Подпись — полное название агрегата (как в списке и карточке, глава 9), до 2 строк.
  /// Ширина — под самое длинное слово: «кондиционера» у центральной зоны, «Масляный» у боковой.
  static const _labelWidth = 104.0;
  static const _sideLabelWidth = 76.0;

  /// Центральные зоны (по оси авто) шире: соседей сбоку у них нет.
  static double _labelWidthAt(Offset position) => position.dx == 0.5 ? _labelWidth : _sideLabelWidth;

  @override
  Widget build(BuildContext context) {
    final c = context.evColors;
    return Semantics(
      label: 'Схема автомобиля',
      container: true,
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 300),
          child: AspectRatio(
            aspectRatio: 0.62,
            child: LayoutBuilder(builder: (context, box) {
              return Stack(
                clipBehavior: Clip.none,
                children: [
                  Positioned.fill(child: CustomPaint(painter: _CarPainter(c))),
                  for (final s in statuses)
                    if (aggregateSchemePositions[s.aggregateTypeCode] case final at?)
                      Positioned(
                        left: at.dx * box.maxWidth - _labelWidthAt(at) / 2,
                        top: at.dy * box.maxHeight - _zone / 2,
                        width: _labelWidthAt(at),
                        child: _Zone(status: s, onTap: () => onTap(s)),
                      ),
                ],
              );
            }),
          ),
        ),
      ),
    );
  }
}

class _Zone extends StatelessWidget {
  const _Zone({required this.status, required this.onTap});

  final AggregateStatusItem status;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = context.evColors;
    final (_, _, solid) = status.status.colors(c);
    return Semantics(
      button: true,
      label: '${status.aggregateTypeName}: ${status.status.label}',
      excludeSemantics: true,
      child: InkWell(
        key: Key('zone-${status.aggregateTypeCode}'),
        onTap: onTap,
        customBorder: const RoundedRectangleBorder(borderRadius: BorderRadius.all(Radius.circular(EvRadius.md))),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: AggregateScheme._zone,
              height: AggregateScheme._zone,
              decoration: BoxDecoration(
                color: solid,
                shape: BoxShape.circle,
                border: Border.all(color: c.surface, width: 3),
              ),
              child: Icon(status.status.icon, color: c.surface, size: EvSize.iconLg),
            ),
            const SizedBox(height: EvSpace.s1),
            // Подложка — подпись читается поверх контура кузова и колёс.
            Container(
              padding: const EdgeInsets.symmetric(horizontal: EvSpace.s1),
              decoration: BoxDecoration(
                color: c.surface.withValues(alpha: 0.9),
                borderRadius: const BorderRadius.all(Radius.circular(EvRadius.sm)),
              ),
              child: Text(
                status.aggregateTypeName,
                textAlign: TextAlign.center,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: EvTypeMobile.caption.copyWith(color: c.fg),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Контур авто сверху: кузов, колёса, лобовое и заднее стекло.
class _CarPainter extends CustomPainter {
  _CarPainter(this.c);

  final EvColors c;

  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width;
    final h = size.height;
    final body = RRect.fromRectAndCorners(
      Rect.fromLTWH(w * 0.1, h * 0.02, w * 0.8, h * 0.96),
      topLeft: Radius.circular(w * 0.3),
      topRight: Radius.circular(w * 0.3),
      bottomLeft: Radius.circular(w * 0.2),
      bottomRight: Radius.circular(w * 0.2),
    );
    final wheel = Paint()..color = c.borderStrong;
    for (final y in [0.18, 0.74]) {
      for (final x in [0.04, 0.86]) {
        canvas.drawRRect(
          RRect.fromRectAndRadius(Rect.fromLTWH(w * x, h * y, w * 0.1, h * 0.13), Radius.circular(w * 0.03)),
          wheel,
        );
      }
    }
    canvas.drawRRect(body, Paint()..color = c.surfaceSubtle);
    canvas.drawRRect(
      body,
      Paint()
        ..color = c.borderStrong
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2,
    );
    final glass = Paint()..color = c.border;
    // Лобовое стекло и заднее стекло.
    canvas.drawPath(
      Path()
        ..moveTo(w * 0.22, h * 0.4)
        ..quadraticBezierTo(w * 0.5, h * 0.35, w * 0.78, h * 0.4)
        ..lineTo(w * 0.72, h * 0.44)
        ..quadraticBezierTo(w * 0.5, h * 0.41, w * 0.28, h * 0.44)
        ..close(),
      glass,
    );
    canvas.drawPath(
      Path()
        ..moveTo(w * 0.26, h * 0.7)
        ..quadraticBezierTo(w * 0.5, h * 0.73, w * 0.74, h * 0.7)
        ..lineTo(w * 0.78, h * 0.74)
        ..quadraticBezierTo(w * 0.5, h * 0.78, w * 0.22, h * 0.74)
        ..close(),
      glass,
    );
  }

  @override
  bool shouldRepaint(_CarPainter old) => old.c != c;
}
