// Нижняя навигация клиентского приложения (Глава 6; разделы — Глава 7 / ТЗ).
// Высота — size.bottom-nav (64), каждый пункт ≥ 44×44 (тест test/design_system_test.dart).
import 'package:flutter/material.dart';

enum EvSection {
  car('Мой авто', Icons.directions_car_outlined, Icons.directions_car),
  learning('Обучение', Icons.school_outlined, Icons.school),
  troubleshooting('Неполадки', Icons.build_outlined, Icons.build),
  tickets('Тикеты', Icons.chat_bubble_outline, Icons.chat_bubble),
  notifications('Уведомления', Icons.notifications_outlined, Icons.notifications);

  const EvSection(this.label, this.icon, this.selectedIcon);

  final String label;
  final IconData icon;
  final IconData selectedIcon;
}

class EvBottomNav extends StatelessWidget {
  const EvBottomNav({super.key, required this.current, required this.onSelected});

  final EvSection current;
  final ValueChanged<EvSection> onSelected;

  @override
  Widget build(BuildContext context) {
    return NavigationBar(
      selectedIndex: current.index,
      onDestinationSelected: (i) => onSelected(EvSection.values[i]),
      labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
      destinations: [
        for (final s in EvSection.values)
          NavigationDestination(icon: Icon(s.icon), selectedIcon: Icon(s.selectedIcon), label: s.label),
      ],
    );
  }
}
