// «Поддержка»: вкладки «Неполадки» (деревья решений) и «Обращения» (тикеты/чат) + «Новое обращение».
// Правило 3-х кликов: форма тикета — 2 тапа («Поддержка» → «Новое обращение»).
import 'package:flutter/material.dart';

import '../../app/app_state.dart';
import '../../data/models.dart';
import '../../theme/app_theme.dart';
import '../../ui/demo_panel.dart';
import '../../ui/format.dart';
import '../../ui/states.dart';
import '../learning/learning_screen.dart';
import 'decision_tree_screen.dart';
import 'ticket_chat_screen.dart';
import 'ticket_create_screen.dart';

class SupportScreen extends StatelessWidget {
  const SupportScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final vehicle = app.vehicle;
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Поддержка'),
          actions: const [DemoButton()],
          bottom: const TabBar(tabs: [Tab(text: 'Неполадки'), Tab(text: 'Обращения')]),
        ),
        floatingActionButton: vehicle == null
            ? null
            : FloatingActionButton.extended(
                key: const Key('new-ticket'),
                // Авто не подставляется: при нескольких авто клиент выбирает его в форме.
                onPressed: () => Navigator.of(context).push(MaterialPageRoute<void>(
                  builder: (_) => const TicketCreateScreen(),
                )),
                icon: const Icon(Icons.add_comment_outlined),
                label: const Text('Новое обращение'),
              ),
        body: TabBarView(
          children: [
            _Troubleshooting(modelId: vehicle?.vehicleModel.id, revision: app.revision),
            _Tickets(revision: app.revision, hasVehicle: vehicle != null),
          ],
        ),
      ),
    );
  }
}

class _Troubleshooting extends StatelessWidget {
  const _Troubleshooting({required this.modelId, required this.revision});

  final int? modelId;
  final int revision;

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    return AsyncView<List<KnowledgeArticle>>(
      reloadKey: (modelId, revision),
      load: () => app.repository.articles(modelId ?? 0, ArticleType.troubleshooting),
      isEmpty: (items) => items.isEmpty,
      empty: const EmptyState(icon: Icons.build_outlined, title: 'Инструкций по неполадкам пока нет'),
      builder: (context, items, reload) => RefreshIndicator(
        onRefresh: reload,
        child: ListView(
          // Отступ снизу — под кнопку «Новое обращение».
          padding: const EdgeInsets.fromLTRB(EvSpace.s4, EvSpace.s4, EvSpace.s4, EvSpace.s16 + EvSpace.s8),
          children: [
            Text(
              'Выберите проблему — подскажем, что сделать. Если не поможет, создадим обращение инженеру.',
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(color: context.evColors.fgMuted),
            ),
            const SizedBox(height: EvSpace.s4),
            for (final a in items) ...[
              ArticleCard(
                article: a,
                icon: Icons.build_outlined,
                onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(
                  builder: (_) => DecisionTreeScreen(article: a),
                )),
              ),
              const SizedBox(height: EvSpace.s3),
            ],
          ],
        ),
      ),
    );
  }
}

class _Tickets extends StatelessWidget {
  const _Tickets({required this.revision, required this.hasVehicle});

  final int revision;
  final bool hasVehicle;

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    return AsyncView<List<Ticket>>(
      reloadKey: revision,
      load: app.repository.tickets,
      isEmpty: (items) => items.isEmpty,
      empty: EmptyState(
        icon: Icons.forum_outlined,
        title: 'Обращений пока нет',
        message: hasVehicle
            ? 'Если что-то не работает, начните с вкладки «Неполадки» или создайте обращение'
            : 'Добавьте авто, чтобы создать обращение — мы прикрепим модель и версию прошивки',
      ),
      builder: (context, items, reload) => RefreshIndicator(
        onRefresh: reload,
        child: ListView.separated(
          padding: const EdgeInsets.fromLTRB(0, EvSpace.s2, 0, EvSpace.s16 + EvSpace.s8),
          itemCount: items.length,
          separatorBuilder: (_, __) => const Divider(height: 1),
          itemBuilder: (context, i) {
            final t = items[i];
            return ListTile(
              key: Key('ticket-${t.id}'),
              title: Text('№${t.id} · ${t.category.label}'),
              // Описание из дерева неполадок многострочное — ограничено, чтобы дата была видна всегда.
              subtitle: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(t.description, maxLines: 2, overflow: TextOverflow.ellipsis),
                  Text(formatDateTime(t.createdAt), key: Key('ticket-${t.id}-date')),
                ],
              ),
              isThreeLine: true,
              trailing: TicketStatusChip(status: t.status),
              onTap: () async {
                await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => TicketChatScreen(ticket: t)));
                await reload();
              },
            );
          },
        ),
      ),
    );
  }
}

/// Статус тикета — подпись + иконка (не только цвет).
class TicketStatusChip extends StatelessWidget {
  const TicketStatusChip({super.key, required this.status});

  final TicketStatus status;

  @override
  Widget build(BuildContext context) {
    final c = context.evColors;
    final (icon, bg, fg) = switch (status) {
      TicketStatus.newTicket => (Icons.inbox_outlined, c.surfaceSubtle, c.infoText),
      TicketStatus.inProgress => (Icons.autorenew, c.statusYellowBg, c.statusYellowFg),
      TicketStatus.waitingVendor => (Icons.hourglass_empty, c.surfaceSubtle, c.fgMuted),
      TicketStatus.resolved => (Icons.check_circle_outline, c.statusGreenBg, c.statusGreenFg),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: EvSpace.s2, vertical: EvSpace.s1),
      decoration: BoxDecoration(color: bg, borderRadius: const BorderRadius.all(Radius.circular(EvRadius.full))),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: EvSize.iconSm, color: fg),
          const SizedBox(width: EvSpace.s1),
          Text(status.label, style: EvTypeMobile.caption.copyWith(color: fg)),
        ],
      ),
    );
  }
}
