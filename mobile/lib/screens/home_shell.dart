// Каркас после входа: четыре раздела нижней навигации (ТЗ раздел 9), состояние вкладок сохраняется.
import 'package:flutter/material.dart';

import '../app/app_state.dart';
import '../ui/bottom_nav.dart';
import 'car/car_screen.dart';
import 'learning/learning_screen.dart';
import 'news/news_screen.dart';
import 'support/support_screen.dart';

class HomeShell extends StatefulWidget {
  const HomeShell({super.key});

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  EvSection _section = EvSection.car;

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    return Scaffold(
      body: IndexedStack(
        index: _section.index,
        children: const [CarScreen(), LearningScreen(), SupportScreen(), NewsScreen()],
      ),
      bottomNavigationBar: EvBottomNav(
        current: _section,
        onSelected: (s) => setState(() => _section = s),
        badges: {EvSection.news: app.unreadNotifications},
      ),
    );
  }
}
