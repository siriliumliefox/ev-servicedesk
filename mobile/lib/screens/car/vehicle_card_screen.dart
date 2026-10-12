// Карточка авто (глава 18): модель, VIN, прошивка, пробег (только вверх) и история ТО постранично.
import 'package:flutter/material.dart';

import '../../app/app_state.dart';
import '../../data/models.dart';
import '../../theme/app_theme.dart';
import '../../ui/fact_row.dart';
import '../../ui/format.dart';
import '../../ui/states.dart';
import 'maintenance_history.dart';

class VehicleCardScreen extends StatelessWidget {
  const VehicleCardScreen({super.key, required this.vehicleId});

  final int vehicleId;

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final vehicle = app.vehicles.where((v) => v.id == vehicleId).firstOrNull;
    if (vehicle == null) return const Scaffold(body: SizedBox.shrink());
    final text = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(title: Text(vehicle.vehicleModel.title)),
      body: ListView(
        padding: const EdgeInsets.all(EvSpace.s4),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(EvSpace.s4),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  FactRow(
                      label: 'Модель',
                      value: [
                        vehicle.vehicleModel.title,
                        if (vehicle.vehicleModel.trim != null) vehicle.vehicleModel.trim!
                      ].join(' ')),
                  FactRow(label: 'VIN', value: vehicle.vinMasked),
                  FactRow(label: 'Прошивка', value: vehicle.currentFirmwareVersion ?? 'нет данных'),
                  const Divider(height: EvSpace.s6),
                  Row(
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text('Пробег', style: text.bodyMedium?.copyWith(color: context.evColors.fgMuted)),
                            Text(formatKm(vehicle.mileage), key: const Key('mileage'), style: text.titleLarge),
                          ],
                        ),
                      ),
                      OutlinedButton(
                        key: const Key('update-mileage'),
                        onPressed: () => _updateMileage(context, vehicle),
                        child: const Text('Обновить'),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: EvSpace.s6),
          Text('История ТО', style: text.titleMedium),
          const SizedBox(height: EvSpace.s2),
          MaintenanceHistory(
            key: ValueKey((vehicle.id, app.revision)),
            vehicleId: vehicle.id,
            empty: const EmptyState(
              icon: Icons.history,
              title: 'Работ пока не было',
              message: 'Записи появятся после ТО в сервисном центре',
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _updateMileage(BuildContext context, Vehicle vehicle) async {
    final updated = await showDialog<Vehicle>(context: context, builder: (_) => _MileageDialog(vehicle: vehicle));
    if (updated == null || !context.mounted) return;
    AppScope.read(context).vehicleUpdated(updated);
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Пробег обновлён')));
  }
}

/// Ввод пробега: целое число не меньше текущего; уменьшение — только через сервисный центр (ADR 0006).
class _MileageDialog extends StatefulWidget {
  const _MileageDialog({required this.vehicle});

  final Vehicle vehicle;

  @override
  State<_MileageDialog> createState() => _MileageDialogState();
}

class _MileageDialogState extends State<_MileageDialog> {
  final _controller = TextEditingController();
  String? _error;
  bool _busy = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final mileage = int.tryParse(_controller.text.replaceAll(RegExp(r'\s'), ''));
    if (mileage == null || mileage > 2000000) {
      setState(() => _error = 'Введите пробег в километрах');
      return;
    }
    if (mileage < widget.vehicle.mileage) {
      setState(() => _error = 'Не меньше текущего: ${formatKm(widget.vehicle.mileage)}');
      return;
    }
    setState(() {
      _error = null;
      _busy = true;
    });
    try {
      final updated = await AppScope.read(context).repository.updateMileage(widget.vehicle.id, mileage);
      if (mounted) Navigator.of(context).pop(updated);
    } on Exception catch (e) {
      // Текст для пользователя — у исключения (ApiException — по коду контракта, OfflineException — «нет сети»).
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Пробег'),
      content: TextField(
        key: const Key('mileage-input'),
        controller: _controller,
        autofocus: true,
        keyboardType: TextInputType.number,
        decoration: InputDecoration(
          suffixText: 'км',
          helperText: 'Сейчас ${formatKm(widget.vehicle.mileage)}',
          errorText: _error,
          errorMaxLines: 3,
        ),
        onSubmitted: (_) => _submit(),
      ),
      actions: [
        TextButton(onPressed: _busy ? null : () => Navigator.of(context).pop(), child: const Text('Отмена')),
        FilledButton(
          key: const Key('save-mileage'),
          onPressed: _busy ? null : _submit,
          child: _busy ? const ButtonProgress() : const Text('Сохранить'),
        ),
      ],
    );
  }
}
