// Лента уведомлений (GET /notifications) для центра уведомлений и вкладки «Новости» (ADR 0024 п. 6): фильтр по типу
// на клиенте (в контракте его нет), непрочитанные — точкой и жирным, открытие отмечает прочитанным
// (PATCH /notifications/{id}/read). Тикетов в ленте нет — их видно в переписке (ADR 0019 п. 13).
import 'package:flutter/material.dart';

import '../../app/app_state.dart';
import '../../data/models.dart';
import '../../theme/app_theme.dart';
import '../../ui/demo_panel.dart';
import '../../ui/format.dart';
import '../../ui/states.dart';
import '../support/ticket_create_screen.dart';

/// Центр уведомлений: все типы — прошивки, ТО, новости, акции. Открывается колокольчиком и нажатием на push.
class NotificationCenterScreen extends StatelessWidget {
  const NotificationCenterScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Уведомления'), actions: const [DemoButton()]),
      body: const NotificationFeed(
        types: NotificationType.values,
        emptyTitle: 'Уведомлений пока нет',
        emptyMessage: 'Здесь появятся уведомления о прошивках, ТО, новости и акции для вашего авто',
      ),
    );
  }
}

class NotificationFeed extends StatefulWidget {
  const NotificationFeed({
    super.key,
    required this.types,
    required this.emptyTitle,
    required this.emptyMessage,
  });

  final List<NotificationType> types;
  final String emptyTitle;
  final String emptyMessage;

  @override
  State<NotificationFeed> createState() => _NotificationFeedState();
}

class _NotificationFeedState extends State<NotificationFeed> {
  NotificationType? _filter;

  static IconData _icon(NotificationType t) => switch (t) {
        NotificationType.firmware => Icons.system_update_outlined,
        NotificationType.maintenance => Icons.build_circle_outlined,
        NotificationType.news => Icons.campaign_outlined,
        NotificationType.promo => Icons.local_offer_outlined,
      };

  Future<void> _open(NotificationItem n, Future<void> Function() reload) async {
    final app = AppScope.read(context);
    showNotificationSheet(context, n);
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
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          padding: const EdgeInsets.symmetric(horizontal: EvSpace.s4, vertical: EvSpace.s2),
          child: Row(
            children: [
              for (final t in <NotificationType?>[null, ...widget.types]) ...[
                ChoiceChip(
                  key: Key('filter-${t?.name ?? 'all'}'),
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
            // Вкладка «Новости» снова выбрана, закрыт экран поверх центра — список с сервера, а не прежний (M3).
            reloadOnShow: true,
            load: () async =>
                (await app.repository.notifications()).where((n) => widget.types.contains(n.type)).toList(),
            builder: (context, all, reload) {
              final items = _filter == null ? all : all.where((n) => n.type == _filter).toList();
              return RefreshIndicator(
                onRefresh: () async {
                  await reload();
                  await app.refreshUnread();
                },
                child: items.isEmpty
                    ? EmptyState(
                        icon: Icons.notifications_none,
                        title: _filter == null ? widget.emptyTitle : 'В разделе «${_filter!.label}» пока пусто',
                        message: widget.emptyMessage,
                      )
                    : ListView.separated(
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
    );
  }
}

/// Уведомление целиком — из ленты и при нажатии на push (ADR 0024 п. 4).
void showNotificationSheet(BuildContext context, NotificationItem item) =>
    showModalBottomSheet<void>(context: context, builder: (_) => _NotificationSheet(item: item));

class _NotificationSheet extends StatelessWidget {
  const _NotificationSheet({required this.item});

  final NotificationItem item;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final vehicles = AppScope.read(context).vehicles;
    final vehicleId = item.vehicleId;
    // Напоминание о ТО — сразу записаться (та же форма, что из карточки агрегата, глава 9).
    final canBook =
        item.type == NotificationType.maintenance && vehicleId != null && vehicles.any((v) => v.id == vehicleId);
    // Прошивка — запись на обновление авто этой модели (#113); несколько таких авто — выбор в форме.
    final firmwareVehicles = item.type == NotificationType.firmware
        ? [
            for (final v in vehicles)
              if (v.vehicleModel.id == item.targetVehicleModelId) v.id
          ]
        : const <int>[];
    return SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(EvSpace.s6, 0, EvSpace.s6, EvSpace.s6),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('${item.type.label} · ${formatDateTime(item.createdAt)}',
                style: text.bodyMedium?.copyWith(color: context.evColors.fgMuted)),
            const SizedBox(height: EvSpace.s2),
            Text(item.title, key: const Key('notification-title'), style: text.titleLarge),
            if (item.body.isNotEmpty) ...[
              const SizedBox(height: EvSpace.s3),
              Text(item.body, style: text.bodyLarge),
            ],
            if (canBook) ...[
              const SizedBox(height: EvSpace.s6),
              FilledButton.icon(
                key: const Key('book-maintenance'),
                onPressed: () => Navigator.of(context)
                  ..pop()
                  ..push(MaterialPageRoute<void>(
                    builder: (_) => TicketCreateScreen(vehicleId: vehicleId, booking: ServiceBooking.maintenance),
                  )),
                icon: const Icon(Icons.event_available_outlined),
                label: const Text('Записаться на ТО'),
              ),
            ],
            if (firmwareVehicles.isNotEmpty) ...[
              const SizedBox(height: EvSpace.s6),
              FilledButton.icon(
                key: const Key('book-firmware'),
                onPressed: () => Navigator.of(context)
                  ..pop()
                  ..push(MaterialPageRoute<void>(
                    builder: (_) => TicketCreateScreen(
                      vehicleId: firmwareVehicles.length == 1 ? firmwareVehicles.single : null,
                      booking: ServiceBooking.firmware,
                      description: '${ServiceBooking.firmware.title}: ${item.title}',
                    ),
                  )),
                icon: const Icon(Icons.system_update_outlined),
                label: const Text('Записаться на обновление'),
              ),
            ],
          ],
        ),
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
