// Панель «Демо» прототипа (глава 7): переключение сценариев для ревью — нет сети,
// набор авто на аккаунте, тема, выход к онбордингу. Только для PrototypeRepository.
import 'package:flutter/material.dart';

import '../app/app_state.dart';
import '../data/prototype_repository.dart';
import '../theme/app_theme.dart';

class DemoButton extends StatelessWidget {
  const DemoButton({super.key});

  @override
  Widget build(BuildContext context) {
    if (AppScope.of(context).prototype == null) return const SizedBox.shrink();
    return IconButton(
      tooltip: 'Сценарии прототипа',
      icon: const Icon(Icons.tune),
      onPressed: () => showModalBottomSheet<void>(
        context: context,
        isScrollControlled: true,
        builder: (_) => const DemoPanel(),
      ),
    );
  }
}

class DemoPanel extends StatelessWidget {
  const DemoPanel({super.key});

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final proto = app.prototype!;
    final text = Theme.of(context).textTheme;
    final c = context.evColors;
    return SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(EvSpace.s4, 0, EvSpace.s4, EvSpace.s6),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('Сценарии прототипа', style: text.titleLarge),
            const SizedBox(height: EvSpace.s4),
            SwitchListTile(
              key: const Key('demo-offline'),
              contentPadding: EdgeInsets.zero,
              title: const Text('Нет сети'),
              subtitle: const Text('Все запросы завершаются ошибкой подключения'),
              value: proto.offline,
              onChanged: app.setOffline,
            ),
            const SizedBox(height: EvSpace.s3),
            Text('Авто на аккаунте', style: text.titleMedium),
            const SizedBox(height: EvSpace.s2),
            SegmentedButton<AccountScenario>(
              showSelectedIcon: false,
              segments: [
                for (final s in AccountScenario.values) ButtonSegment(value: s, label: Text(s.label)),
              ],
              selected: {proto.account},
              onSelectionChanged: (s) => app.setAccountScenario(s.single),
            ),
            const SizedBox(height: EvSpace.s4),
            Text('Тема', style: text.titleMedium),
            const SizedBox(height: EvSpace.s2),
            SegmentedButton<ThemeMode>(
              showSelectedIcon: false,
              segments: const [
                ButtonSegment(value: ThemeMode.system, label: Text('Системная')),
                ButtonSegment(value: ThemeMode.light, label: Text('Светлая')),
                ButtonSegment(value: ThemeMode.dark, label: Text('Тёмная')),
              ],
              selected: {app.themeMode},
              onSelectionChanged: (s) => app.setThemeMode(s.single),
            ),
            const SizedBox(height: EvSpace.s4),
            if (app.signedIn)
              OutlinedButton.icon(
                onPressed: () {
                  Navigator.of(context).pop();
                  app.signOut();
                },
                icon: const Icon(Icons.logout),
                label: const Text('Выйти — к онбордингу'),
              ),
            const SizedBox(height: EvSpace.s4),
            Text(
              'Код из SMS — ${PrototypeRepository.demoCode}. VIN определяется по началу: LLX… — Li Auto, '
              'L6T… — Zeekr, LDP… — Voyah; другой VIN — выбор модели из списка; '
              '${PrototypeRepository.takenVin} — уже привязан к другому аккаунту.',
              style: text.bodyMedium?.copyWith(color: c.fgMuted),
            ),
          ],
        ),
      ),
    );
  }
}
