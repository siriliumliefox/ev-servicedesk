// История ТО постранично (глава 18) — в карточке авто вся, в карточке агрегата — история агрегата: его замены
// и работы по нему с меткой вида записи (глава 19, ADR 0023 п. 2).
import 'package:flutter/material.dart';

import '../../app/app_state.dart';
import '../../data/models.dart';
import '../../theme/app_theme.dart';
import '../../ui/format.dart';
import '../../ui/states.dart';

/// «Показать ещё» догружает следующую страницу; ошибка догрузки не стирает загруженное.
class MaintenanceHistory extends StatefulWidget {
  const MaintenanceHistory({super.key, required this.vehicleId, required this.empty, this.aggregateTypeCode});

  final int vehicleId;

  /// null — вся история авто.
  final String? aggregateTypeCode;

  /// Записей нет.
  final Widget empty;

  @override
  State<MaintenanceHistory> createState() => _MaintenanceHistoryState();
}

class _MaintenanceHistoryState extends State<MaintenanceHistory> {
  final List<MaintenanceRecord> _items = [];
  int _page = 0;
  bool _hasMore = true;
  bool _loading = false;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _loadMore();
  }

  Future<void> _loadMore() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final page = await AppScope.read(context).repository.maintenanceRecordsPage(
            widget.vehicleId,
            page: _page + 1,
            aggregateTypeCode: widget.aggregateTypeCode,
          );
      if (!mounted) return;
      setState(() {
        _items.addAll(page.items);
        _page = page.page;
        _hasMore = page.hasMore;
      });
    } on Exception catch (e) {
      if (mounted) setState(() => _error = e);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_items.isEmpty) {
      if (_loading) {
        return const Padding(padding: EdgeInsets.all(EvSpace.s6), child: Center(child: CircularProgressIndicator()));
      }
      if (_error != null) return ErrorState(error: _error!, onRetry: _loadMore);
      return widget.empty;
    }
    final c = context.evColors;
    return Column(
      children: [
        Card(
          child: Column(
            children: [
              for (final (i, r) in _items.indexed) ...[
                if (i > 0) const Divider(height: 1),
                ListTile(
                  key: Key('record-${r.id}'),
                  leading: Icon(r.kind == MaintenanceKind.replacement ? Icons.autorenew : Icons.build_circle_outlined),
                  title: Text(formatDate(r.performedAt)),
                  subtitle: Text(
                    [r.kind.label, formatKm(r.mileageAtService), if (r.description != null) r.description!].join(' · '),
                  ),
                ),
              ],
            ],
          ),
        ),
        if (_error != null)
          Padding(
            padding: const EdgeInsets.only(top: EvSpace.s2),
            child: Text('$_error', style: TextStyle(color: c.dangerText)),
          ),
        if (_hasMore)
          Padding(
            padding: const EdgeInsets.only(top: EvSpace.s2),
            child: TextButton(
              key: const Key('more-records'),
              onPressed: _loading ? null : _loadMore,
              child: _loading ? const ButtonProgress() : Text(_error == null ? 'Показать ещё' : 'Повторить'),
            ),
          ),
      ],
    );
  }
}
