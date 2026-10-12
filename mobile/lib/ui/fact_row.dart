// Строка «подпись — значение» в карточках (агрегат, авто).
import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

class FactRow extends StatelessWidget {
  const FactRow({super.key, required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: EvSpace.s1),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(child: Text(label, style: text.bodyMedium?.copyWith(color: context.evColors.fgMuted))),
          const SizedBox(width: EvSpace.s4),
          Expanded(child: Text(value, style: text.bodyLarge, textAlign: TextAlign.end)),
        ],
      ),
    );
  }
}
