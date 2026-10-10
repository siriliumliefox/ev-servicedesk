// Переключатель авто в шапке (шторка «Мои автомобили»): «Авто» и «Обучение» (U-06, глава 9).
// Выбор меняет выбранное авто всего приложения (AppState.selectVehicle).
import 'package:flutter/material.dart';

import '../../app/app_state.dart';
import '../../data/models.dart';
import '../../theme/app_theme.dart';
import '../../ui/format.dart';
import '../onboarding/add_vehicle_screen.dart';

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
