import 'package:flutter/material.dart';

import 'theme/app_theme.dart';
import 'ui/bottom_nav.dart';
import 'ui/status_badge.dart';

// Каркас, Глава 4; тема и компоненты — Глава 6. Реальный флоу онбординга/авторизации — Глава 18.
void main() {
  runApp(const EvServiceDeskApp());
}

class EvServiceDeskApp extends StatelessWidget {
  const EvServiceDeskApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'EV-ServiceDesk',
      theme: evTheme(Brightness.light),
      darkTheme: evTheme(Brightness.dark),
      home: const _HomeScreen(),
    );
  }
}

class _HomeScreen extends StatefulWidget {
  const _HomeScreen();

  @override
  State<_HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<_HomeScreen> {
  EvSection _section = EvSection.car;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('EV-ServiceDesk')),
      // Витрина дизайн-системы до прототипа экранов (Глава 7).
      body: ListView(
        padding: const EdgeInsets.all(EvSpace.s4),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(EvSpace.s4),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Статусы агрегатов', style: Theme.of(context).textTheme.titleMedium),
                  const SizedBox(height: EvSpace.s3),
                  Wrap(
                    spacing: EvSpace.s2,
                    runSpacing: EvSpace.s2,
                    children: [for (final s in AggregateStatus.values) StatusBadge(status: s)],
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: EvSpace.s4),
          FilledButton(onPressed: () {}, child: const Text('Создать тикет')),
          const SizedBox(height: EvSpace.s2),
          OutlinedButton(onPressed: () {}, child: const Text('Добавить авто')),
          const SizedBox(height: EvSpace.s4),
          const TextField(decoration: InputDecoration(labelText: 'VIN', helperText: '17 символов')),
        ],
      ),
      bottomNavigationBar: EvBottomNav(
        current: _section,
        onSelected: (s) => setState(() => _section = s),
      ),
    );
  }
}
