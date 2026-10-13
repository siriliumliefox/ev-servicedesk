// Карточка агрегата (боттом-шит): статус, ресурс, последняя замена, история агрегата, запись на замену.
// «Нет данных» — явный статус, а не ошибка (глава 5, сценарий unknown без истории). История агрегата — его замены
// и работы по нему (осмотр, долив) с меткой вида записи (глава 19, ADR 0023 п. 2).
import 'package:flutter/material.dart';

import '../../data/models.dart';
import '../../theme/app_theme.dart';
import '../../ui/status_badge.dart';
import '../../ui/fact_row.dart';
import '../../ui/format.dart';
import 'maintenance_history.dart';
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

  /// Запись — та же форма обращения в режиме записи: авто и агрегат известны, время — пожеланием (глава 9).
  void _book(BuildContext context, ServiceBooking booking) {
    final nav = Navigator.of(context);
    nav.pop();
    nav.push(MaterialPageRoute<void>(
      builder: (_) => TicketCreateScreen(
        vehicleId: vehicle.id,
        booking: booking,
        description: '${booking.title}: ${status.aggregateTypeName}',
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
          FactRow(label: 'Остаток ресурса', value: _remaining(s)),
          if (s.lastReplacedAt != null)
            FactRow(
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
                onPressed: () => _book(context, ServiceBooking.replacement),
                icon: const Icon(Icons.event_available),
                label: const Text('Записаться на замену'),
              )
            : OutlinedButton.icon(
                key: const Key('book-service'),
                onPressed: () => _book(context, ServiceBooking.maintenance),
                icon: const Icon(Icons.event_available),
                label: const Text('Записаться на ТО'),
              ),
        const SizedBox(height: EvSpace.s6),
        Text('История агрегата', style: text.titleMedium),
        const SizedBox(height: EvSpace.s2),
        MaintenanceHistory(
          vehicleId: vehicle.id,
          aggregateTypeCode: s.aggregateTypeCode,
          empty: Padding(
            padding: const EdgeInsets.symmetric(vertical: EvSpace.s2),
            child: Text('Замен и работ пока не было', style: TextStyle(color: c.fgMuted)),
          ),
        ),
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
