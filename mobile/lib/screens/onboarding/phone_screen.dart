// Онбординг, шаг 1: телефон → запрос SMS-кода (POST /auth/phone/request-code).
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../app/app_state.dart';
import '../../theme/app_theme.dart';
import '../../ui/demo_panel.dart';
import '../../ui/states.dart';
import 'code_screen.dart';

class PhoneScreen extends StatefulWidget {
  const PhoneScreen({super.key});

  @override
  State<PhoneScreen> createState() => _PhoneScreenState();
}

class _PhoneScreenState extends State<PhoneScreen> {
  final _controller = TextEditingController();
  String? _error;
  bool _busy = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  /// Беларусь: +375 и 9 цифр (код оператора + номер).
  String? get _phone {
    final digits = _controller.text.replaceAll(RegExp(r'\D'), '');
    return digits.length == 9 ? '+375$digits' : null;
  }

  Future<void> _submit() async {
    final phone = _phone;
    if (phone == null) {
      setState(() => _error = 'Введите 9 цифр номера, например 29 123-45-67');
      return;
    }
    setState(() {
      _error = null;
      _busy = true;
    });
    try {
      final ttl = await AppScope.read(context).repository.requestCode(phone);
      if (!mounted) return;
      await Navigator.of(context).push(MaterialPageRoute<void>(
        builder: (_) => CodeScreen(phone: phone, ttlSeconds: ttl),
      ));
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
    return Scaffold(
      appBar: AppBar(actions: const [DemoButton()]),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(EvSpace.s6),
          children: [
            Align(
              alignment: Alignment.centerLeft,
              child: Container(
                width: EvSpace.s16,
                height: EvSpace.s16,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: c.primary,
                  borderRadius: const BorderRadius.all(Radius.circular(EvRadius.lg)),
                ),
                child: Icon(Icons.electric_car, size: EvSpace.s10, color: c.onPrimary),
              ),
            ),
            const SizedBox(height: EvSpace.s6),
            Text('Цифровой паспорт автомобиля', style: text.headlineMedium),
            const SizedBox(height: EvSpace.s2),
            Text(
              'Статус агрегатов, история ТО, обучение и поддержка ETS AUTO в одном приложении.',
              style: text.bodyLarge?.copyWith(color: c.fgMuted),
            ),
            const SizedBox(height: EvSpace.s8),
            TextField(
              key: const Key('phone'),
              controller: _controller,
              keyboardType: TextInputType.phone,
              autofillHints: const [AutofillHints.telephoneNumberNational],
              inputFormatters: [FilteringTextInputFormatter.digitsOnly, LengthLimitingTextInputFormatter(9)],
              onSubmitted: (_) => _submit(),
              decoration: InputDecoration(
                labelText: 'Номер телефона',
                prefixText: '+375 ',
                hintText: '29 123 45 67',
                errorText: _error,
                helperText: 'Пришлём SMS с кодом для входа или регистрации',
                // Подсказка и ошибка переносятся, а не обрезаются многоточием на узких экранах (глава 9).
                helperMaxLines: 3,
                errorMaxLines: 3,
              ),
            ),
            const SizedBox(height: EvSpace.s6),
            FilledButton(
              onPressed: _busy ? null : _submit,
              child: _busy ? const ButtonProgress() : const Text('Получить код'),
            ),
          ],
        ),
      ),
    );
  }
}
