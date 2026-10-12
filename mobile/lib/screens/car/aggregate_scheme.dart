// Интерактивная схема автомобиля (вид сверху, перед — вверху): зоны-агрегаты со статусом «светофор».
// ТЗ раздел 6: читается от 360 px, зона тапа ≥ 44×44; статус — цвет + форма иконки + подпись (Semantics).
// Контур — SVG-ассет, зоны — виджеты поверх него: тап-зона и Semantics не зависят от рисунка (ADR 0023 п. 1).
import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

import '../../data/models.dart';
import '../../theme/app_theme.dart';
import '../../ui/status_badge.dart';

/// Положение зоны на схеме (доли ширины/высоты) — по месту агрегата в авто. Агрегаты, добавленные в админ-панели
/// без своего места на схеме, показываются только в списке под схемой.
/// Под капотом — агрегаты ДВС (у электромобиля их нет в регламенте модели), за лобовым стеклом — пара климата,
/// у задней оси — редуктор: схема симметрична и с ДВС, и без него. Воздушный фильтр — ниже пары масла: подписи
/// пары при крупном шрифте (×1.3) переносятся на вторую строку и не должны наезжать на его зону (ADR 0023 п. 6).
const aggregateSchemePositions = <String, Offset>{
  'engine_oil': Offset(0.31, 0.11),
  'oil_filter': Offset(0.69, 0.11),
  'air_filter': Offset(0.5, 0.32),
  'ac_refrigerant': Offset(0.31, 0.58),
  'cabin_filter': Offset(0.69, 0.58),
  'gearbox_oil': Offset(0.5, 0.83),
};

class AggregateScheme extends StatelessWidget {
  const AggregateScheme({super.key, required this.statuses, required this.onTap});

  final List<AggregateStatusItem> statuses;
  final ValueChanged<AggregateStatusItem> onTap;

  static const _zone = EvSize.controlMobile; // 48 ≥ 44

  /// Подпись — полное название агрегата (как в списке и карточке, глава 9), до 2 строк; ширина одна для всех зон —
  /// под самое длинное слово шрифтом Inter («кондиционера»). Пары под капотом разнесены так, что подписи
  /// не сходятся и не выходят за кузов.
  static const _labelWidth = 108.0;

  /// Подписи на схеме растут с системным размером текста до 1.3 — дальше зоны сошлись бы; список под схемой
  /// масштабируется без ограничения (ADR 0023 п. 6).
  static const maxLabelTextScale = 1.3;

  static const contourAsset = 'assets/scheme/car_top.svg';

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
                  Positioned.fill(
                    child: SvgPicture.asset(contourAsset, colorMapper: _ContourColors(c), excludeFromSemantics: true),
                  ),
                  for (final s in statuses)
                    if (aggregateSchemePositions[s.aggregateTypeCode] case final at?)
                      Positioned(
                        left: at.dx * box.maxWidth - _labelWidth / 2,
                        top: at.dy * box.maxHeight - _zone / 2,
                        width: _labelWidth,
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
            MediaQuery.withClampedTextScaling(
              maxScaleFactor: AggregateScheme.maxLabelTextScale,
              child: Container(
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
            ),
          ],
        ),
      ),
    );
  }
}

/// Цвета контура из токенов темы вместо заглушек SVG — по id элемента (assets/scheme/car_top.svg).
/// Равенство по цветам: от него зависит кэш разобранного SVG (светлая и тёмная тема — разные записи).
class _ContourColors extends ColorMapper {
  _ContourColors(EvColors c)
      : outline = c.borderStrong,
        body = c.surfaceSubtle,
        glass = c.border;

  final Color outline;
  final Color body;
  final Color glass;

  @override
  Color substitute(String? id, String elementName, String attributeName, Color color) => switch (id) {
        'body' when attributeName == 'fill' => body,
        'body' => outline,
        final String id when id.startsWith('wheel-') => outline,
        final String id when id.startsWith('glass-') => glass,
        _ => color,
      };

  @override
  bool operator ==(Object other) =>
      other is _ContourColors && other.outline == outline && other.body == body && other.glass == glass;

  @override
  int get hashCode => Object.hash(outline, body, glass);
}
