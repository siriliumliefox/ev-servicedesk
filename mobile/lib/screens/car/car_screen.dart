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
import '../onboarding/add_vehicle_screen.dart';
import 'aggregate_scheme.dart';
import 'aggregate_sheet.dart';

void openAddVehicle(BuildContext context) {
  final app = AppScope.read(context);
  Navigator.of(context).push(MaterialPageRoute<void>(
    builder: (context) => AddVehicleScreen(
      onAdded: (v) {
        app.vehicleAdded(v);
        Navigator.of(context).pop();
      },
    ),
  ));
}

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

class _Summary extends StatelessWidget {
  const _Summary({required this.vehicle, required this.statuses});

  final Vehicle vehicle;
  final List<AggregateStatusItem> statuses;

  @override
  Widget build(BuildContext context) {
    final c = context.evColors;
    final text = Theme.of(context).textTheme;
    final red = statuses.where((s) => s.status == AggregateStatus.red).length;
    final yellow = statuses.where((s) => s.status == AggregateStatus.yellow).length;
    final attention = [
      if (red > 0) 'Требуется замена: $red',
      if (yellow > 0) 'Скоро менять: $yellow',
    ];
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
            Text(
              attention.isEmpty ? 'Все агрегаты в норме' : attention.join(' · '),
              style: text.titleMedium,
            ),
          ],
        ),
      ),
    );
  }
}

/// Переключатель авто в шапке: модель + VIN (маска) → список авто аккаунта и «Добавить авто».
class VehicleSwitcher extends StatelessWidget {
  const VehicleSwitcher({super.key, required this.vehicle});

  final Vehicle vehicle;

  @override
  Widget build(BuildContext context) {
    final c = context.evColors;
    final text = Theme.of(context).textTheme;
    final count = AppScope.of(context).vehicles.length;
    return Semantics(
      button: true,
      label: 'Автомобиль ${vehicle.vehicleModel.title}, ${count > 1 ? 'всего $count, ' : ''}сменить или добавить',
      excludeSemantics: true,
      child: InkWell(
        key: const Key('vehicle-switcher'),
        borderRadius: const BorderRadius.all(Radius.circular(EvRadius.md)),
        onTap: () => _open(context),
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: EvSize.tapTargetMin),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: EvSpace.s2),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Flexible(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(vehicle.vehicleModel.title, style: text.titleMedium, overflow: TextOverflow.ellipsis),
                      Text(
                        count > 1 ? '${vehicle.vinMasked} · авто: $count' : vehicle.vinMasked,
                        style: text.bodySmall?.copyWith(color: c.fgMuted),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: EvSpace.s1),
                const Icon(Icons.expand_more),
              ],
            ),
          ),
        ),
      ),
    );
  }

  void _open(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      builder: (sheetContext) {
        final app = AppScope.of(sheetContext);
        return SafeArea(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: EvSpace.s4),
                child: Text('Мои автомобили', style: Theme.of(sheetContext).textTheme.titleLarge),
              ),
              const SizedBox(height: EvSpace.s2),
              for (final v in app.vehicles)
                ListTile(
                  leading: const Icon(Icons.directions_car_outlined),
                  title: Text([v.vehicleModel.title, if (v.vehicleModel.trim != null) v.vehicleModel.trim].join(' · ')),
                  subtitle: Text('${v.vinMasked} · ${formatKm(v.mileage)}'),
                  trailing: v.id == vehicle.id ? const Icon(Icons.check) : null,
                  selected: v.id == vehicle.id,
                  onTap: () {
                    app.selectVehicle(v.id);
                    Navigator.of(sheetContext).pop();
                  },
                ),
              ListTile(
                leading: const Icon(Icons.add),
                title: const Text('Добавить авто'),
                onTap: () {
                  Navigator.of(sheetContext).pop();
                  openAddVehicle(context);
                },
              ),
              const SizedBox(height: EvSpace.s2),
            ],
          ),
        );
      },
    );
  }
}
