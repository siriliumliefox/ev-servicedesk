// Каркас после входа: четыре раздела нижней навигации (ТЗ раздел 9), состояние вкладок сохраняется.
import 'package:flutter/material.dart';

import '../app/app_state.dart';
import '../ui/bottom_nav.dart';
import 'car/car_screen.dart';
import 'learning/learning_screen.dart';
import 'news/news_screen.dart';
import 'support/support_screen.dart';

/// Раздел — в AppState: его переключает и нажатие на push (ADR 0024 п. 4).
class HomeShell extends StatelessWidget {
  const HomeShell({super.key});

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    return Scaffold(
      body: IndexedStack(
        index: app.section.index,
        children: const [CarScreen(), LearningScreen(), SupportScreen(), NewsScreen()],
      ),
      bottomNavigationBar: EvBottomNav(
        current: app.section,
        onSelected: app.selectSection,
        badges: {EvSection.news: app.unreadNews},
      ),
    );
  }
}
