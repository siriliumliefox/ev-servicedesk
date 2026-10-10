// Нижняя навигация клиентского приложения (Глава 6; разделы — ТЗ раздел 9, Глава 7 / ADR 0011):
// «Авто» / «Обучение» / «Поддержка» / «Новости». Неполадки и тикеты — в «Поддержке»,
// уведомления — в «Новостях» (одна лента /notifications, счётчик непрочитанных на пункте).
// Высота — size.bottom-nav (64), каждый пункт ≥ 44×44 (тест test/design_system_test.dart).
import 'package:flutter/material.dart';

enum EvSection {
  car('Авто', Icons.directions_car_outlined, Icons.directions_car),
  learning('Обучение', Icons.school_outlined, Icons.school),
  support('Поддержка', Icons.support_agent_outlined, Icons.support_agent),
  news('Новости', Icons.notifications_outlined, Icons.notifications);

  const EvSection(this.label, this.icon, this.selectedIcon);

  final String label;
  final IconData icon;
  final IconData selectedIcon;
}

class EvBottomNav extends StatelessWidget {
  const EvBottomNav({super.key, required this.current, required this.onSelected, this.badges = const {}});

  final EvSection current;
  final ValueChanged<EvSection> onSelected;

  /// Счётчики на пунктах (непрочитанные уведомления).
  final Map<EvSection, int> badges;

  @override
  Widget build(BuildContext context) {
    return NavigationBar(
      selectedIndex: current.index,
      onDestinationSelected: (i) => onSelected(EvSection.values[i]),
      labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
      destinations: [
        for (final s in EvSection.values)
          NavigationDestination(
            icon: _withBadge(Icon(s.icon), badges[s]),
            selectedIcon: _withBadge(Icon(s.selectedIcon), badges[s]),
            label: s.label,
            tooltip: (badges[s] ?? 0) > 0 ? '${s.label}: непрочитанных ${badges[s]}' : s.label,
          ),
      ],
    );
  }

  static Widget _withBadge(Widget icon, int? count) =>
      (count ?? 0) > 0 ? Badge(label: Text('$count'), child: icon) : icon;
}
