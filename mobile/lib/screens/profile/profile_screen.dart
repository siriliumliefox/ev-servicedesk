// Профиль (глава 18, ADR 0022 п. 11): телефон, выход с устройства, отзыв согласия на обработку ПД (99-З, ст. 10).
import 'package:flutter/material.dart';

import '../../app/app_state.dart';
import '../../data/repository.dart';
import '../../theme/app_theme.dart';
import '../../ui/fact_row.dart';
import '../../ui/format.dart';
import '../../ui/states.dart';

class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key});

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  bool _busy = false;

  Future<void> _run(Future<void> Function(AppState app) action) async {
    setState(() => _busy = true);
    try {
      await action(AppScope.read(context));
    } on Exception catch (e) {
      if (mounted) showErrorSnack(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _withdraw() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Отозвать согласие?'),
        content: const Text(
          'Вы выйдете на всех устройствах, а ваши персональные данные будут удалены. '
          'Продолжить работу в приложении можно будет только с новым согласием.',
        ),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Отмена')),
          FilledButton(
            key: const Key('confirm-withdraw'),
            style: FilledButton.styleFrom(backgroundColor: context.evColors.dangerText),
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Отозвать'),
          ),
        ],
      ),
    );
    if (confirmed ?? false) await _run((app) => app.withdrawPdConsent());
  }

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('Профиль')),
      body: ListView(
        padding: const EdgeInsets.all(EvSpace.s4),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(EvSpace.s4),
              child: AsyncView<Profile>(
                load: app.repository.me,
                builder: (context, profile, _) =>
                    FactRow(label: 'Телефон', value: profile.phone == null ? '—' : formatPhone(profile.phone!)),
              ),
            ),
          ),
          const SizedBox(height: EvSpace.s6),
          FilledButton.tonalIcon(
            key: const Key('sign-out'),
            onPressed: _busy ? null : () => _run((app) => app.signOut()),
            icon: const Icon(Icons.logout),
            label: const Text('Выйти'),
          ),
          const SizedBox(height: EvSpace.s2),
          TextButton(
            key: const Key('withdraw-consent'),
            onPressed: _busy ? null : _withdraw,
            child: Text(
              'Отозвать согласие на обработку персональных данных',
              textAlign: TextAlign.center,
              style: TextStyle(color: context.evColors.dangerText),
            ),
          ),
        ],
      ),
    );
  }
}
