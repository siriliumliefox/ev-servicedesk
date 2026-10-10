// «Новости»: лента уведомлений (GET /notifications) — прошивки, ТО, новости, акции; фильтр по типу,
// непрочитанные выделены точкой и жирным; открытие отмечает прочитанным (POST /notifications/{id}/read).
import 'package:flutter/material.dart';

import '../../app/app_state.dart';
import '../../data/models.dart';
import '../../theme/app_theme.dart';
import '../../ui/demo_panel.dart';
import '../../ui/format.dart';
import '../../ui/states.dart';

class NewsScreen extends StatefulWidget {
  const NewsScreen({super.key});

  @override
  State<NewsScreen> createState() => _NewsScreenState();
}

class _NewsScreenState extends State<NewsScreen> {
  NotificationType? _filter;

  static IconData _icon(NotificationType t) => switch (t) {
        NotificationType.firmware => Icons.system_update_outlined,
        NotificationType.maintenance => Icons.build_circle_outlined,
        NotificationType.news => Icons.campaign_outlined,
        NotificationType.promo => Icons.local_offer_outlined,
      };

  Future<void> _open(NotificationItem n, Future<void> Function() reload) async {
    final app = AppScope.read(context);
    showModalBottomSheet<void>(
      context: context,
      builder: (context) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(EvSpace.s6, 0, EvSpace.s6, EvSpace.s6),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('${n.type.label} · ${formatDateTime(n.createdAt)}',
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(color: context.evColors.fgMuted)),
              const SizedBox(height: EvSpace.s2),
              Text(n.title, style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: EvSpace.s3),
              Text(n.body, style: Theme.of(context).textTheme.bodyLarge),
            ],
          ),
        ),
      ),
    );
    if (n.isRead) return;
    try {
      await app.repository.markNotificationRead(n.id);
      await reload();
      await app.refreshUnread();
    } on Exception {
      // Отметка о прочтении повторится при следующем открытии.
    }
  }

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('Новости'), actions: const [DemoButton()]),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: EvSpace.s4, vertical: EvSpace.s2),
            child: Row(
              children: [
                for (final t in <NotificationType?>[null, ...NotificationType.values]) ...[
                  ChoiceChip(
                    label: Text(t?.label ?? 'Все'),
                    selected: _filter == t,
                    onSelected: (_) => setState(() => _filter = t),
                  ),
                  const SizedBox(width: EvSpace.s2),
                ],
              ],
            ),
          ),
          Expanded(
            child: AsyncView<List<NotificationItem>>(
              reloadKey: app.revision,
              load: app.repository.notifications,
              builder: (context, all, reload) {
                final items = _filter == null ? all : all.where((n) => n.type == _filter).toList();
                if (items.isEmpty) {
                  return EmptyState(
                    icon: Icons.notifications_none,
                    title: _filter == null ? 'Пока нет новостей' : 'В разделе «${_filter!.label}» пока пусто',
                    message: 'Здесь появятся уведомления о прошивках, ТО и акциях для вашего авто',
                  );
                }
                return RefreshIndicator(
                  onRefresh: reload,
                  child: ListView.separated(
                    itemCount: items.length,
                    separatorBuilder: (_, __) => const Divider(height: 1),
                    itemBuilder: (context, i) => _Tile(
                      item: items[i],
                      icon: _icon(items[i].type),
                      onTap: () => _open(items[i], reload),
                    ),
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

class _Tile extends StatelessWidget {
  const _Tile({required this.item, required this.icon, required this.onTap});

  final NotificationItem item;
  final IconData icon;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = context.evColors;
    final text = Theme.of(context).textTheme;
    final unread = !item.isRead;
    return Semantics(
      label: unread ? 'Не прочитано' : null,
      child: ListTile(
        key: Key('notification-${item.id}'),
        leading: Icon(icon, color: unread ? c.primaryText : c.fgMuted),
        title: Text(item.title, style: text.bodyLarge?.copyWith(fontWeight: unread ? FontWeight.w600 : null)),
        subtitle: Text('${item.type.label} · ${formatDate(item.createdAt)}'),
        trailing: unread
            ? Container(
                width: EvSpace.s3,
                height: EvSpace.s3,
                decoration: BoxDecoration(color: c.primaryText, shape: BoxShape.circle),
              )
            : null,
        onTap: onTap,
      ),
    );
  }
}
