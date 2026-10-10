// Главный экран «Авто»: переключатель авто + интерактивная схема агрегатов + список статусов.
// Правило 3-х кликов: статус агрегата — 1 тап по зоне схемы или строке списка.
import 'package:flutter/material.dart';

import '../../app/app_state.dart';
import '../../data/models.dart';
import '../../theme/app_theme.dart';
import '../../ui/status_badge.dart';
import '../../ui/demo_panel.dart';
import '../../ui/format.dart';
import '../../ui/states.dart';
import 'aggregate_scheme.dart';
import 'aggregate_sheet.dart';
import 'vehicle_switcher.dart';

class CarScreen extends StatelessWidget {
  const CarScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final vehicle = app.vehicle;
    return Scaffold(
      appBar: AppBar(
        titleSpacing: EvSpace.s2,
        title: vehicle == null ? const Text('Мой авто') : VehicleSwitcher(vehicle: vehicle),
        actions: const [DemoButton()],
      ),
      body: _body(context, app, vehicle),
    );
  }

  Widget _body(BuildContext context, AppState app, Vehicle? vehicle) {
    if (app.loadingVehicles && app.vehicles.isEmpty) return const Center(child: CircularProgressIndicator());
    if (app.vehiclesError != null) return ErrorState(error: app.vehiclesError!, onRetry: app.refresh);
    if (vehicle == null) {
      return EmptyState(
        icon: Icons.directions_car_outlined,
        title: 'Добавьте автомобиль',
        message: 'Привяжите авто по VIN — покажем статус агрегатов, историю ТО и инструкции для вашей модели',
        action: FilledButton.icon(
          onPressed: () => openAddVehicle(context),
          icon: const Icon(Icons.add),
          label: const Text('Добавить авто'),
        ),
      );
    }
    return AsyncView<List<AggregateStatusItem>>(
      key: ValueKey(vehicle.id),
      reloadKey: (vehicle.id, app.revision),
      load: () => app.repository.aggregateStatuses(vehicle.id),
      builder: (context, statuses, reload) => RefreshIndicator(
        onRefresh: reload,
        child: ListView(
          padding: const EdgeInsets.all(EvSpace.s4),
          children: [
            _Summary(vehicle: vehicle, statuses: statuses),
            const SizedBox(height: EvSpace.s4),
            AggregateScheme(
              statuses: statuses,
              onTap: (s) => showAggregateSheet(context, vehicle: vehicle, status: s),
            ),
            const SizedBox(height: EvSpace.s6),
            Text('Агрегаты', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: EvSpace.s2),
            Card(
              child: Column(
                children: [
                  for (final (i, s) in _byUrgency(statuses).indexed) ...[
                    if (i > 0) const Divider(height: 1),
                    ListTile(
                      key: Key('row-${s.aggregateTypeCode}'),
                      title: Text(s.aggregateTypeName),
                      trailing: StatusBadge(status: s.status),
                      onTap: () => showAggregateSheet(context, vehicle: vehicle, status: s),
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// Сначала то, что требует внимания: красный → жёлтый → нет данных → зелёный.
  static List<AggregateStatusItem> _byUrgency(List<AggregateStatusItem> items) {
    const order = [AggregateStatus.red, AggregateStatus.yellow, AggregateStatus.unknown, AggregateStatus.green];
    return [...items]..sort((a, b) => order.indexOf(a.status).compareTo(order.indexOf(b.status)));
  }
}

/// Сводка над схемой (U-01): «Нет данных» — не норма. Нет данных ни по одному агрегату (новое авто без истории ТО) —
/// отдельная подсказка; по части — счётчик рядом с остальными; «Все агрегаты в норме» — только если все «Заменено».
/// Пустой список (у модели нет агрегатов в регламенте) — тоже «нет данных», а не «в норме».
(String headline, String? hint) aggregateSummary(List<AggregateStatusItem> statuses) {
  int count(AggregateStatus status) => statuses.where((s) => s.status == status).length;
  final unknown = count(AggregateStatus.unknown);
  if (unknown == statuses.length) {
    return (
      statuses.isEmpty ? 'Нет данных о замене' : 'Нет данных о замене: $unknown',
      'Статусы появятся после ТО в сервисе',
    );
  }
  final red = count(AggregateStatus.red);
  final yellow = count(AggregateStatus.yellow);
  final attention = [
    if (red > 0) 'Требуется замена: $red',
    if (yellow > 0) 'Скоро менять: $yellow',
    if (unknown > 0) 'Нет данных: $unknown',
  ];
  // Счётчик не разрывается переносом (неразрывные пробелы): строка переносится только между счётчиками.
  return (attention.isEmpty ? 'Все агрегаты в норме' : attention.map(_noBreak).join(' · '), null);
}

String _noBreak(String s) => s.replaceAll(' ', '\u00A0');

class _Summary extends StatelessWidget {
  const _Summary({required this.vehicle, required this.statuses});

  final Vehicle vehicle;
  final List<AggregateStatusItem> statuses;

  @override
  Widget build(BuildContext context) {
    final c = context.evColors;
    final text = Theme.of(context).textTheme;
    final (headline, hint) = aggregateSummary(statuses);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(EvSpace.s4),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              [
                'Пробег ${formatKm(vehicle.mileage)}',
                if (vehicle.currentFirmwareVersion != null) 'прошивка ${vehicle.currentFirmwareVersion}',
              ].join(' · '),
              style: text.bodyMedium?.copyWith(color: c.fgMuted),
            ),
            const SizedBox(height: EvSpace.s1),
            Text(headline, key: const Key('summary'), style: text.titleMedium),
            if (hint != null) Text(hint, style: text.bodyMedium?.copyWith(color: c.fgMuted)),
          ],
        ),
      ),
    );
  }
}
