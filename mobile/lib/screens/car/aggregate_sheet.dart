// Карточка агрегата (боттом-шит): статус, ресурс, последняя замена, история ТО, запись на замену.
// «Нет данных» — явный статус, а не ошибка (глава 5, сценарий unknown без истории).
import 'package:flutter/material.dart';

import '../../app/app_state.dart';
import '../../data/models.dart';
import '../../theme/app_theme.dart';
import '../../ui/status_badge.dart';
import '../../ui/format.dart';
import '../../ui/states.dart';
import '../support/ticket_create_screen.dart';

Future<void> showAggregateSheet(BuildContext context,
        {required Vehicle vehicle, required AggregateStatusItem status}) =>
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (_) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.7,
        maxChildSize: 0.95,
        builder: (context, scroll) => AggregateSheet(vehicle: vehicle, status: status, scrollController: scroll),
      ),
    );

class AggregateSheet extends StatelessWidget {
  const AggregateSheet({super.key, required this.vehicle, required this.status, this.scrollController});

  final Vehicle vehicle;
  final AggregateStatusItem status;
  final ScrollController? scrollController;

  void _book(BuildContext context) {
    final nav = Navigator.of(context);
    nav.pop();
    nav.push(MaterialPageRoute<void>(
      builder: (_) => TicketCreateScreen(
        vehicleId: vehicle.id,
        category: TicketCategory.maintenance,
        description: 'Запись на замену: ${status.aggregateTypeName}',
      ),
    ));
  }

  @override
  Widget build(BuildContext context) {
    final c = context.evColors;
    final text = Theme.of(context).textTheme;
    final s = status;
    final (_, _, solid) = s.status.colors(c);
    final needsService = s.status != AggregateStatus.green;
    return ListView(
      controller: scrollController,
      padding: const EdgeInsets.fromLTRB(EvSpace.s4, 0, EvSpace.s4, EvSpace.s8),
      children: [
        Text(s.aggregateTypeName, style: text.titleLarge),
        const SizedBox(height: EvSpace.s1),
        Text('${vehicle.vehicleModel.title} · ${vehicle.vinMasked}',
            style: text.bodyMedium?.copyWith(color: c.fgMuted)),
        const SizedBox(height: EvSpace.s4),
        Align(alignment: Alignment.centerLeft, child: StatusBadge(status: s.status)),
        const SizedBox(height: EvSpace.s4),
        if (s.status == AggregateStatus.unknown)
          Text(
            'Нет данных о последней замене — статус не рассчитан. Запишитесь на ТО: мастер отметит замену, '
            'и статус появится.',
            style: text.bodyLarge,
          )
        else ...[
          Semantics(
            label: 'Израсходовано ${s.percentage!.round()} % интервала',
            excludeSemantics: true,
            child: ClipRRect(
              borderRadius: const BorderRadius.all(Radius.circular(EvRadius.full)),
              child: LinearProgressIndicator(
                value: (s.percentage! / 100).clamp(0, 1),
                minHeight: EvSpace.s2,
                color: solid,
                backgroundColor: c.surfaceSubtle,
              ),
            ),
          ),
          const SizedBox(height: EvSpace.s2),
          Text('Израсходовано ${s.percentage!.round()} % интервала',
              style: text.bodyMedium?.copyWith(color: c.fgMuted)),
          const SizedBox(height: EvSpace.s4),
          _Fact(label: 'Остаток ресурса', value: _remaining(s)),
          if (s.lastReplacedAt != null)
            _Fact(
              label: 'Последняя замена',
              value: [
                formatDate(s.lastReplacedAt!),
                if (s.lastReplacedMileage != null) formatKm(s.lastReplacedMileage!),
              ].join(' · '),
            ),
        ],
        const SizedBox(height: EvSpace.s4),
        needsService
            ? FilledButton.icon(
                key: const Key('book-service'),
                onPressed: () => _book(context),
                icon: const Icon(Icons.event_available),
                label: const Text('Записаться на замену'),
              )
            : OutlinedButton.icon(
                key: const Key('book-service'),
                onPressed: () => _book(context),
                icon: const Icon(Icons.event_available),
                label: const Text('Записаться на ТО'),
              ),
        const SizedBox(height: EvSpace.s6),
        Text('История замен', style: text.titleMedium),
        const SizedBox(height: EvSpace.s2),
        _History(vehicleId: vehicle.id, code: s.aggregateTypeCode),
      ],
    );
  }

  static String _remaining(AggregateStatusItem s) {
    final parts = <String>[
      if (s.remainingKm != null)
        s.remainingKm! >= 0 ? formatKm(s.remainingKm!) : 'перепробег ${formatKm(-s.remainingKm!)}',
      if (s.remainingDays != null)
        s.remainingDays! >= 0 ? formatDays(s.remainingDays!) : 'просрочено на ${formatDays(s.remainingDays!)}',
    ];
    return parts.isEmpty ? '—' : parts.join(' или ');
  }
}

class _Fact extends StatelessWidget {
  const _Fact({required this.label, required this.value});

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

class _History extends StatelessWidget {
  const _History({required this.vehicleId, required this.code});

  final int vehicleId;
  final String code;

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    return AsyncView<List<MaintenanceRecord>>(
      load: () async =>
          (await app.repository.maintenanceRecords(vehicleId)).where((r) => r.aggregateTypeCode == code).toList(),
      isEmpty: (items) => items.isEmpty,
      empty: Padding(
        padding: const EdgeInsets.symmetric(vertical: EvSpace.s2),
        child: Text('Замен пока не было', style: TextStyle(color: context.evColors.fgMuted)),
      ),
      builder: (context, items, _) => Column(
        children: [
          for (final r in items)
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.build_circle_outlined),
              title: Text(formatDate(r.performedAt)),
              subtitle: Text([formatKm(r.mileageAtService), if (r.description != null) r.description!].join(' · ')),
            ),
        ],
      ),
    );
  }
}
