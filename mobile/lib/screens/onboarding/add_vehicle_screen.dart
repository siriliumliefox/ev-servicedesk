// Добавление авто по VIN (POST /vehicles): модель определяет VIN-декодер; если не смог —
// 422 VIN_DECODE_FAILED и выбор модели из списка (GET /vehicle-models); 409 — VIN привязан к другому аккаунту.
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../app/app_state.dart';
import '../../data/models.dart';
import '../../data/repository.dart';
import '../../theme/app_theme.dart';
import '../../ui/states.dart';

/// VIN: 17 символов, латиница и цифры без I, O, Q (схема VehicleCreateRequest).
final vinPattern = RegExp(r'^[A-HJ-NPR-Z0-9]{17}$');

class AddVehicleScreen extends StatefulWidget {
  const AddVehicleScreen({super.key, required this.onAdded, this.onboarding = false});

  final ValueChanged<Vehicle> onAdded;

  /// Шаг онбординга: можно пропустить и добавить авто позже.
  final bool onboarding;

  @override
  State<AddVehicleScreen> createState() => _AddVehicleScreenState();
}

class _AddVehicleScreenState extends State<AddVehicleScreen> {
  final _controller = TextEditingController();
  String? _error;
  bool _busy = false;
  List<VehicleModel>? _models; // не null — декодер не распознал VIN, нужен выбор модели
  int? _modelId;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final vin = _controller.text.trim().toUpperCase();
    if (!vinPattern.hasMatch(vin)) {
      setState(() => _error = 'VIN — 17 символов: латинские буквы (кроме I, O, Q) и цифры');
      return;
    }
    if (_models != null && _modelId == null) {
      setState(() => _error = 'Выберите модель автомобиля');
      return;
    }
    final app = AppScope.read(context);
    setState(() {
      _error = null;
      _busy = true;
    });
    try {
      final vehicle = await app.repository.addVehicle(vin, vehicleModelId: _modelId);
      if (!mounted) return;
      widget.onAdded(vehicle);
    } on ApiException catch (e) {
      if (e.code == 'VIN_DECODE_FAILED') {
        try {
          final models = await app.repository.vehicleModels();
          setState(() {
            _models = models;
            _error = null;
          });
        } on Exception catch (e) {
          if (mounted) showErrorSnack(context, e);
        }
      } else {
        setState(() => _error = e.message);
      }
    } on Exception catch (e) {
      if (mounted) showErrorSnack(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.evColors;
    final text = Theme.of(context).textTheme;
    final app = AppScope.of(context);
    return Scaffold(
      appBar: AppBar(
        title: widget.onboarding ? null : const Text('Добавить авто'),
        actions: [
          if (widget.onboarding) TextButton(onPressed: app.signIn, child: const Text('Пропустить')),
        ],
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(EvSpace.s6),
          children: [
            if (widget.onboarding) ...[
              Text('Добавьте автомобиль', style: text.headlineMedium),
              const SizedBox(height: EvSpace.s2),
            ],
            Text(
              'По VIN определим марку, модель и комплектацию и покажем статус агрегатов.',
              style: text.bodyLarge?.copyWith(color: c.fgMuted),
            ),
            const SizedBox(height: EvSpace.s6),
            TextField(
              key: const Key('vin'),
              controller: _controller,
              textCapitalization: TextCapitalization.characters,
              autocorrect: false,
              inputFormatters: [
                FilteringTextInputFormatter.allow(RegExp('[A-Za-z0-9]')),
                LengthLimitingTextInputFormatter(17),
                _UpperCase(),
              ],
              onChanged: (_) {
                if (_models == null) return;
                setState(() {
                  _models = null;
                  _modelId = null;
                });
              },
              decoration: InputDecoration(
                labelText: 'VIN',
                errorText: _error,
                errorMaxLines: 2,
                helperText: '17 символов. Указан в техпаспорте и под лобовым стеклом',
                helperMaxLines: 2,
              ),
            ),
            if (_models != null) ...[
              const SizedBox(height: EvSpace.s4),
              Text(
                'Не удалось определить модель по VIN — выберите её из списка.',
                style: text.bodyMedium?.copyWith(color: c.infoText),
              ),
              const SizedBox(height: EvSpace.s3),
              DropdownButtonFormField<int>(
                isExpanded: true,
                key: const Key('model'),
                initialValue: _modelId,
                decoration: const InputDecoration(labelText: 'Модель'),
                items: [
                  for (final m in _models!)
                    DropdownMenuItem(value: m.id, child: Text([m.title, if (m.trim != null) m.trim].join(' · '))),
                ],
                onChanged: (id) => setState(() => _modelId = id),
              ),
            ],
            const SizedBox(height: EvSpace.s6),
            FilledButton(
              onPressed: _busy ? null : _submit,
              child: _busy ? const ButtonProgress() : const Text('Добавить'),
            ),
          ],
        ),
      ),
    );
  }
}

class _UpperCase extends TextInputFormatter {
  @override
  TextEditingValue formatEditUpdate(TextEditingValue oldValue, TextEditingValue newValue) =>
      newValue.copyWith(text: newValue.text.toUpperCase());
}
