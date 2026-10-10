// Справка на экране (глава 9): что прикрепится к обращению, что будет дальше после отправки заявки.
// Подпись + иконка «информация» на приглушённой подложке — тот же вид, что в форме обращения (глава 7).
import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

class InfoNote extends StatelessWidget {
  const InfoNote({super.key, required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    final c = context.evColors;
    return Container(
      padding: const EdgeInsets.all(EvSpace.s3),
      decoration: BoxDecoration(
        color: c.surfaceSubtle,
        borderRadius: const BorderRadius.all(Radius.circular(EvRadius.md)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.info_outline, size: EvSize.iconMd, color: c.infoText),
          const SizedBox(width: EvSpace.s2),
          Expanded(child: Text(text, style: Theme.of(context).textTheme.bodyMedium)),
        ],
      ),
    );
  }
}
