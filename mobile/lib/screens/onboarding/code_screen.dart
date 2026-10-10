// Онбординг, шаг 2: SMS-код + согласие на обработку ПД (POST /auth/phone/verify-code, 99-З ст. 5).
// Ограничение попыток — на сервере (ТЗ раздел 7); повторная отправка — после ttl.
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../app/app_state.dart';
import '../../data/prototype_repository.dart';
import '../../data/repository.dart';
import '../../theme/app_theme.dart';
import '../../ui/format.dart';
import '../../ui/states.dart';
import 'add_vehicle_screen.dart';

/// Редакция политики обработки ПД, с которой соглашается пользователь (pd_policy_version).
const pdPolicyVersion = '2026-10';

class CodeScreen extends StatefulWidget {
  const CodeScreen({super.key, required this.phone, required this.ttlSeconds});

  final String phone;
  final int ttlSeconds;

  @override
  State<CodeScreen> createState() => _CodeScreenState();
}

class _CodeScreenState extends State<CodeScreen> {
  final _controller = TextEditingController();
  bool _consent = false;
  String? _error;
  bool _busy = false;
  late int _resendIn = widget.ttlSeconds;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _startTimer();
  }

  void _startTimer() {
    _timer?.cancel();
    _timer = Timer.periodic(const Duration(seconds: 1), (t) {
      if (_resendIn <= 1) t.cancel();
      setState(() => _resendIn--);
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _controller.dispose();
    super.dispose();
  }

  Future<void> _resend() async {
    try {
      final ttl = await AppScope.read(context).repository.requestCode(widget.phone);
      setState(() {
        _resendIn = ttl;
        _error = null;
      });
      _startTimer();
    } on Exception catch (e) {
      if (mounted) showErrorSnack(context, e);
    }
  }

  Future<void> _submit() async {
    if (_controller.text.length != 4) {
      setState(() => _error = 'Введите 4 цифры из SMS');
      return;
    }
    if (!_consent) {
      setState(() => _error = 'Чтобы продолжить, примите согласие на обработку персональных данных');
      return;
    }
    final app = AppScope.read(context);
    setState(() {
      _error = null;
      _busy = true;
    });
    try {
      await app.repository.verifyCode(widget.phone, _controller.text, pdPolicyVersion: pdPolicyVersion);
      final vehicles = await app.repository.vehicles();
      if (!mounted) return;
      if (vehicles.isEmpty) {
        // Новый клиент: третий шаг — привязка авто по VIN (можно пропустить).
        await Navigator.of(context).push(MaterialPageRoute<void>(
          builder: (_) => AddVehicleScreen(onboarding: true, onAdded: (_) => app.signIn()),
        ));
      } else {
        await app.signIn();
      }
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } on Exception catch (e) {
      if (mounted) showErrorSnack(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _showPolicy() {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (context) => const Padding(
        padding: EdgeInsets.fromLTRB(EvSpace.s6, 0, EvSpace.s6, EvSpace.s8),
        child: Text(
          'Политика обработки персональных данных (ред. $pdPolicyVersion)\n\n'
          'Мы обрабатываем номер телефона и VIN автомобиля, чтобы показывать статус ТО, '
          'отвечать на обращения и присылать уведомления. Согласие можно отозвать в профиле.\n\n'
          'Полный текст — глава 13 (юридическая проработка).',
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final c = context.evColors;
    final text = Theme.of(context).textTheme;
    final isPrototype = AppScope.of(context).prototype != null;
    return Scaffold(
      appBar: AppBar(),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(EvSpace.s6),
          children: [
            Text('Код из SMS', style: text.headlineMedium),
            const SizedBox(height: EvSpace.s2),
            Text('Отправили на ${formatPhone(widget.phone)}', style: text.bodyLarge?.copyWith(color: c.fgMuted)),
            const SizedBox(height: EvSpace.s6),
            TextField(
              key: const Key('code'),
              controller: _controller,
              autofocus: true,
              keyboardType: TextInputType.number,
              autofillHints: const [AutofillHints.oneTimeCode],
              inputFormatters: [FilteringTextInputFormatter.digitsOnly, LengthLimitingTextInputFormatter(4)],
              style: EvTypeMobile.h2.copyWith(letterSpacing: EvSpace.s2),
              decoration: InputDecoration(
                labelText: 'Код',
                errorText: _error,
                errorMaxLines: 3,
                helperText: isPrototype ? 'Прототип: код ${PrototypeRepository.demoCode}' : null,
              ),
            ),
            const SizedBox(height: EvSpace.s2),
            Align(
              alignment: Alignment.centerLeft,
              child: _resendIn > 0
                  ? Padding(
                      padding: const EdgeInsets.symmetric(vertical: EvSpace.s3),
                      child: Text('Отправить код повторно через $_resendIn с',
                          style: text.bodyMedium?.copyWith(color: c.fgMuted)),
                    )
                  : TextButton(onPressed: _resend, child: const Text('Отправить код повторно')),
            ),
            const SizedBox(height: EvSpace.s4),
            CheckboxListTile(
              key: const Key('consent'),
              value: _consent,
              onChanged: (v) => setState(() => _consent = v ?? false),
              controlAffinity: ListTileControlAffinity.leading,
              contentPadding: EdgeInsets.zero,
              title: const Text('Согласен(на) на обработку персональных данных'),
              subtitle: Align(
                alignment: Alignment.centerLeft,
                child: TextButton(
                  onPressed: _showPolicy,
                  style: TextButton.styleFrom(padding: EdgeInsets.zero),
                  child: const Text('Политика обработки ПД'),
                ),
              ),
            ),
            const SizedBox(height: EvSpace.s6),
            FilledButton(
              onPressed: _busy ? null : _submit,
              child: _busy ? const ButtonProgress() : const Text('Войти'),
            ),
          ],
        ),
      ),
    );
  }
}
